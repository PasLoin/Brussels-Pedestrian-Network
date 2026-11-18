import functools
import http.server
import json
import math
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import build_site
from browser_coverage import track
from edit_fake_osm import DEV_HOST, FakeOsm
from map_fixtures import CATCH_MAP_ERRORS, empty_pmtiles

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

if sync_playwright is None:
    if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
        raise RuntimeError("REQUIRE_BROWSER_TESTS=1 but playwright is not installed")
    pytest.skip("playwright not installed", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "node_modules" / "maplibre-gl" / "package.json").is_file():
    if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
        raise RuntimeError("the site libraries come from node_modules: run npm ci")
    pytest.skip("npm dev dependencies not installed", allow_module_level=True)

BLANK_STYLE = json.dumps({"version": 8, "sources": {}, "layers": [{"id": "bg", "type": "background", "paint": {"background-color": "#eee"}}]})
CENTER = (4.4300, 50.8460)
FAR_SOUTH = (4.3550, 50.7950)
FAR_WEST = (4.3200, 50.8600)
FAR_EAST = (4.4600, 50.8250)


def _square(x0, y0, size):
    return [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]


COMMUNES = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"name": "Woluwe-Saint-Lambert - Sint-Lambrechts-Woluwe", "name_fr": "Woluwe-Saint-Lambert", "name_nl": "Sint-Lambrechts-Woluwe"},
         "geometry": {"type": "Polygon", "coordinates": [_square(4.41, 50.83, 0.04)]}},
        {"type": "Feature", "properties": {"name": "Uccle - Ukkel", "name_fr": "Uccle", "name_nl": "Ukkel"},
         "geometry": {"type": "Polygon", "coordinates": [_square(4.33, 50.78, 0.04)]}},
    ],
}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    site = tmp_path_factory.mktemp("site")
    build_site.build(site)
    (site / "communes.geojson").write_text(json.dumps(COMMUNES), encoding="utf-8")
    (site / "pedestrian.pmtiles").write_bytes(empty_pmtiles())
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(site))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def fake():
    return FakeOsm()


def street(fr, nl):
    return {"highway": "residential", "name": f"{fr} - {nl}", "name:fr": fr, "name:nl": nl}


def line_at(center, dx=0.0, dy=0.0, length=0.0009):
    x, y = center[0] + dx, center[1] + dy
    return [(x - length / 2, y), (x, y + 0.00002), (x + length / 2, y)]


def bbox_of(coords):
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def intent_for(fake, way_id, set_tags=None):
    way = fake.ways[way_id]
    coords = [(fake.nodes[n]["lon"], fake.nodes[n]["lat"]) for n in way["nodes"]]
    closed = way["nodes"][0] == way["nodes"][-1]
    ends = {"closed": True, "nodes": list(way["nodes"])} if closed else {"closed": False, "first": way["nodes"][0], "last": way["nodes"][-1]}
    return {
        "wayId": way_id,
        "set": set_tags or {"sidewalk:both": "separate"},
        "unset": [],
        "preconditions": {"highway": way["tags"]["highway"], "noSidewalkKeys": True},
        "seenVersion": way["version"],
        "ends": ends,
        "nodeCoords": [[n, fake.nodes[n]["lon"], fake.nodes[n]["lat"]] for n in dict.fromkeys(way["nodes"])],
        "bbox": bbox_of(coords),
        "lengthM": 70,
        "name": way["tags"].get("name", ""),
        "addedAt": 1,
    }


BLANK_PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082")

class Session:
    def __init__(self, browser, server, fake, logged_in=True, queue=None, auth_env="dev", center=CENTER, zoom=17.5, editing=True, settings=None, page_name="devtest.html"):
        self.fake = fake
        self.aborted = []
        self.aborted_auth = []
        self.settings = {"reviewZoom": "null", "minLookMs": "0", "paceMaxMeters": "1000000", "paceBlockMeters": "1000000", **(settings or {})}
        self.problems = []
        self.coverage = []
        self.origin = server
        self.context = browser.new_context(viewport={"width": 1134, "height": 763}, locale="fr-BE")
        self.context.route("**/*", self._route)
        seed = {}
        if logged_in:
            seed["__osmAuth"] = json.dumps({"accessToken": "token", "issuedAt": "2026-11-09", "scopes": ["read_prefs", "write_api"]})
            seed["bpn.authEnv"] = auth_env
        if queue is not None:
            seed["bpn.queue.dev"] = json.dumps(queue)
        self.context.add_init_script(CATCH_MAP_ERRORS)
        self.context.add_init_script(
            "document.addEventListener('securitypolicyviolation', e => console.error('CSP ' + e.violatedDirective + ' ' + e.blockedURI));"
            f"if (!localStorage.getItem('test.seeded')) {{ for (const [k, v] of Object.entries({json.dumps(seed)})) localStorage.setItem(k, v);"
            " localStorage.setItem('test.seeded', '1'); }"
        )
        self.url = f"{server}test-api/{page_name}#{zoom}/{center[1]}/{center[0]}"
        self.page = self.open(editing)

    def _route(self, route):
        url = route.request.url
        if "geoservices-vector.irisnet.be" in url or "geoservices-grid.irisnet.be" in url:
            return route.fulfill(body=BLANK_PNG, content_type="image/png", headers={"Access-Control-Allow-Origin": "*"})
        if "tiles.openfreemap.org/styles/liberty" in url:
            return route.fulfill(body=BLANK_STYLE, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
        if DEV_HOST in url:
            return self.fake.handle(route)
        if self.settings and url.split("?")[0].endswith("/edit/env.js"):
            body = route.fetch().text()
            for key, value in self.settings.items():
                body, n = re.subn(rf"^(\s*{key}): [^,]+,", rf"\1: {value},", body, flags=re.M)
                assert n == 1, key
            return route.fulfill(body=body, content_type="application/javascript")
        if url.startswith("http://127.0.0.1"):
            return route.continue_()
        self.aborted.append(url)
        self.aborted_auth.append((url, route.request.headers.get("authorization", "")))
        return route.abort()

    def open(self, editing=True):
        page = self.context.new_page()
        save = track(self.context, page, self.origin)
        if save:
            self.coverage.append(save)
        page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.problems.append(m.text) if m.type == "error" and m.text.startswith(("CSP", "MapLibre error")) else None)
        page.goto(self.url)
        wait(page, "() => window.BPNEdit !== undefined && window.BPNMap !== undefined")
        if editing:
            enter_edit(page)
        return page

    def close(self):
        for save in self.coverage:
            save()
        self.context.close()
        assert self.problems == []


@pytest.fixture
def session(browser, server, fake):
    opened = []

    def make(**kwargs):
        s = Session(browser, server, fake, **kwargs)
        opened.append(s)
        return s

    yield make
    for s in opened:
        s.close()


def enter_edit(page):
    if not page.evaluate("BPNEdit.isActive()"):
        page.click("#edit-enter")
    wait(page, "() => document.getElementById('edit-status').textContent.length > 0")


def wait(page, expr, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(expr):
            return
        time.sleep(0.1)
    raise AssertionError(f"timeout: {expr}\n{page.inner_text('#edit-panel') if page.query_selector('#edit-panel') else ''}")


def queue_text(page):
    return page.inner_text("#edit-queue")


def queue_ids(page):
    raw = page.evaluate("localStorage.getItem('bpn.queue.dev')")
    return [i["wayId"] for i in json.loads(raw or "[]")]


def wait_idle(page):
    time.sleep(0.15)
    wait(page, "() => !document.getElementById('edit-queue').textContent.includes('Traitement en cours')")


def prepare(page):
    page.click('[data-edit-action="plan"]')
    wait_idle(page)


def send(page, source="survey"):
    if source and not page.is_checked(f'input[name="cs-source"][value="{source}"]'):
        page.check(f'input[name="cs-source"][value="{source}"]')
    page.click('[data-edit-action="send"]')
    wait_idle(page)


def find_way_pixel(page, lon, lat, way_id):
    return page.evaluate(
        f"""async () => {{
          const {{ store }} = await import('/map/store.js');
          const m = store.map;
          const p = m.project([{lon}, {lat}]);
          for (let r = 0; r <= 30; r += 1) {{
            for (const [dx, dy] of [[0, -r], [0, r], [-r, 0], [r, 0]]) {{
              const hit = m.queryRenderedFeatures([p.x + dx, p.y + dy], {{ layers: ['edit-candidates'] }});
              if (hit.some(f => f.properties.osm_id === {way_id})) return [p.x + dx, p.y + dy];
            }}
          }}
          return null;
        }}"""
    )


def click_way(page, lon, lat, way_id, expect_form=True):
    end = time.time() + 10
    pt = find_way_pixel(page, lon, lat, way_id)
    while pt is None:
        assert time.time() < end, f"way {way_id} never rendered"
        time.sleep(0.1)
        pt = find_way_pixel(page, lon, lat, way_id)
    page.mouse.click(*pt)
    if expect_form:
        wait(page, f"() => document.getElementById('edit-detail').textContent.includes('w{way_id}') && !!document.querySelector('[data-edit-action=choose]')")


def wait_candidates(page, count):
    wait(page, f"() => document.getElementById('edit-status').textContent.includes('{count} candidat')")


def uploaded_tags(fake, index=0, way_id=None):
    root = ET.fromstring(fake.uploads[index]["xml"])
    for way in root.iter("way"):
        if way_id is None or int(way.get("id")) == way_id:
            return {t.get("k"): t.get("v") for t in way.iter("tag")}
    return None


def test_click_and_one_value_queues_the_way_with_its_geometry(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"), version=5)
    fake.add_way(102, line_at(CENTER, dy=-0.0004), {**street("Rue Faite", "Gedaanstraat"), "sidewalk:both": "no"})
    fake.add_way(103, line_at(CENTER, dy=0.0004), {"highway": "tertiary", "name": "Grand-Route"})
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    assert "éditable" in s.page.inner_text("#edit-detail")
    s.page.click('[data-side="both"][data-value="separate"]')
    wait(s.page, "() => document.getElementById('edit-queue').textContent.includes('File d\\'édition (1)')")
    stored = json.loads(s.page.evaluate("localStorage.getItem('bpn.queue.dev')"))[0]
    assert stored["set"] == {"sidewalk:both": "separate"}
    assert stored["ends"] == {"closed": False, "first": 10100, "last": 10102}
    assert [n[0] for n in stored["nodeCoords"]] == [10100, 10101, 10102]
    assert fake.count("way_full") == 1


def test_different_sides_queue_only_once_both_are_chosen(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    s.page.click('[data-edit-action="mode"][data-mode="sides"]')
    s.page.click('[data-side="left"][data-value="yes"]')
    assert queue_ids(s.page) == []
    s.page.click('[data-side="right"][data-value="no"]')
    wait(s.page, "() => document.getElementById('edit-queue').textContent.includes('sidewalk:right=no')")
    assert json.loads(s.page.evaluate("localStorage.getItem('bpn.queue.dev')"))[0]["set"] == {"sidewalk:left": "yes", "sidewalk:right": "no"}


def test_a_queued_way_is_written_with_only_the_sidewalk_key_added(session, fake):
    fake.add_way(101, line_at(CENTER), {**street("Rue Test", "Teststraat"), "lit": "yes", "maxspeed": "30"}, version=5)
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    send(s.page)
    assert "1 changeset envoyé" in queue_text(s.page)
    assert uploaded_tags(fake) == {**street("Rue Test", "Teststraat"), "lit": "yes", "maxspeed": "30", "sidewalk:both": "separate"}
    assert fake.ways[101]["version"] == 6
    assert queue_ids(s.page) == []
    assert fake.open_changesets() == []


def test_d1_a_node_moved_far_drops_the_way_with_the_distance(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    fake.move_node(10101, CENTER[0], CENTER[1] + 0.0036)
    prepare(s.page)
    assert "un nœud a été déplacé de 398 m" in queue_text(s.page)
    assert queue_ids(s.page) == []
    assert fake.count("create") == 0


def test_d1_a_small_realignment_is_sent(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    fake.move_node(10101, CENTER[0] + 0.00003, CENTER[1] + 0.00004)
    prepare(s.page)
    send(s.page)
    assert len(fake.uploads) == 1


def test_d2_a_node_added_before_sending_uses_the_fresh_node_list(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    fake.add_node(999, CENTER[0] + 0.0002, CENTER[1] + 0.00001)
    nodes = fake.ways[101]["nodes"]
    fake.edit_way(101, nodes=[nodes[0], nodes[1], 999, nodes[2]])
    prepare(s.page)
    send(s.page)
    root = ET.fromstring(fake.uploads[0]["xml"])
    assert [int(nd.get("ref")) for nd in root.iter("nd")] == [10100, 10101, 999, 10102]


def test_d2_a_node_added_while_sending_triggers_one_retry(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)

    def add_node(f):
        f.add_node(999, CENTER[0] + 0.0002, CENTER[1] + 0.00001)
        nodes = f.ways[101]["nodes"]
        f.edit_way(101, nodes=[nodes[0], nodes[1], 999, nodes[2]])

    fake.inject("upload", hook=add_node)
    send(s.page)
    text = queue_text(s.page)
    assert "relu et renvoyé une fois" in text
    assert "1 changeset envoyé" in text
    assert len(fake.uploads) == 1
    assert fake.ways[101]["tags"]["sidewalk:both"] == "separate"
    assert fake.open_changesets() == []


def test_d3_a_reversed_way_is_never_written_backwards(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101, {"sidewalk:left": "yes", "sidewalk:right": "no"})])
    fake.edit_way(101, nodes=list(reversed(fake.ways[101]["nodes"])))
    prepare(s.page)
    assert "géométrie modifiée depuis" in queue_text(s.page)
    assert fake.count("create") == 0
    assert queue_ids(s.page) == []


def test_d3_a_reversal_during_sending_is_caught_by_the_retry(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101, {"sidewalk:left": "yes", "sidewalk:right": "no"})])
    prepare(s.page)
    fake.inject("upload", hook=lambda f: f.edit_way(101, nodes=list(reversed(f.ways[101]["nodes"]))))
    send(s.page)
    assert "géométrie modifiée depuis" in queue_text(s.page)
    assert fake.uploads == []
    assert "sidewalk:left" not in fake.ways[101]["tags"]
    assert fake.open_changesets() == []


def test_d4_a_split_way_is_dropped(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    fake.edit_way(101, nodes=fake.ways[101]["nodes"][:2])
    prepare(s.page)
    assert "géométrie modifiée depuis" in queue_text(s.page)
    assert fake.count("create") == 0


def test_d6_a_deleted_way_is_dropped_and_the_detail_says_so(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue Deux", "Tweestraat"))
    s = session(queue=[intent_for(fake, 101)])
    wait_candidates(s.page, 2)
    fake.delete_way(102)
    fake.delete_way(101)
    click_way(s.page, CENTER[0], CENTER[1] - 0.0004, 102, expect_form=False)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('n\\'existe plus sur OSM')")
    prepare(s.page)
    assert "supprimé sur OSM" in queue_text(s.page)
    assert queue_ids(s.page) == []


def test_d7_d8_ways_fixed_or_reclassified_meanwhile_are_dropped(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue Deux", "Tweestraat"))
    s = session(queue=[intent_for(fake, 101), intent_for(fake, 102)])
    fake.edit_way(101, tags={**fake.ways[101]["tags"], "sidewalk": "no"})
    fake.edit_way(102, tags={**fake.ways[102]["tags"], "highway": "living_street"})
    prepare(s.page)
    assert queue_text(s.page).count("déjà corrigé depuis") == 2
    assert queue_ids(s.page) == []


def test_d9_another_tag_changed_while_sending_is_kept_alongside(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", hook=lambda f: f.edit_way(101, tags={**f.ways[101]["tags"], "maxspeed": "20"}))
    send(s.page)
    assert "relu et renvoyé une fois" in queue_text(s.page)
    assert fake.ways[101]["tags"]["maxspeed"] == "20"
    assert fake.ways[101]["tags"]["sidewalk:both"] == "separate"


def test_d10_the_same_queue_sent_from_two_tabs_is_written_once(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    other = s.open()
    prepare(s.page)
    send(s.page)
    prepare(other)
    assert "déjà corrigé depuis" in queue_text(other)
    assert len(fake.uploads) == 1
    other.close()


def test_d11_tricky_names_and_long_values_round_trip_unchanged(session, fake):
    tags = {**street("Rue \"A\" & l'École 🚶", "A-straat <b>"), "note": "x" * 255}
    fake.add_way(101, line_at(CENTER), tags)
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    send(s.page)
    assert uploaded_tags(fake) == {**tags, "sidewalk:both": "separate"}


def test_d12_a_reversed_loop_is_detected_on_its_full_node_list(session, fake):
    x, y = CENTER
    fake.add_way(101, [(x, y), (x + 0.0005, y), (x + 0.0005, y + 0.0004), (x, y + 0.0004)], street("Clos A", "A-gaarde"))
    loop = fake.ways[101]["nodes"]
    fake.ways[101]["nodes"] = loop + [loop[0]]
    s = session(queue=[intent_for(fake, 101, {"sidewalk:left": "no", "sidewalk:right": "yes"})])
    fake.edit_way(101, nodes=list(reversed(fake.ways[101]["nodes"])))
    prepare(s.page)
    assert "géométrie modifiée depuis" in queue_text(s.page)


def test_n1_offline_while_loading_candidates_shows_an_error_without_looping(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    fake.inject("map", abort=True, times=5)
    s = session()
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('pas de connexion réseau')")
    time.sleep(1.0)
    assert fake.count("map") == 1
    fake.faults.clear()
    move_map(s.page, 17.6, CENTER[1], CENTER[0])
    wait_candidates(s.page, 1)


def test_n2_offline_while_preparing_keeps_the_queue(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    fake.inject("ways", abort=True)
    prepare(s.page)
    assert "pas de connexion réseau" in queue_text(s.page)
    assert queue_ids(s.page) == [101]


def test_n3_cut_between_changeset_creation_and_upload_closes_the_empty_changeset(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", abort=True)
    send(s.page)
    assert "pas de connexion réseau" in queue_text(s.page)
    assert queue_ids(s.page) == [101]
    assert fake.uploads == []
    assert fake.open_changesets() == []


def test_n4_a_lost_response_after_a_successful_upload_never_writes_twice(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", abort=True, after=True)
    send(s.page)
    assert "pas de connexion réseau" in queue_text(s.page)
    assert len(fake.uploads) == 1
    prepare(s.page)
    assert "déjà corrigé depuis" in queue_text(s.page)
    assert len(fake.uploads) == 1
    assert queue_ids(s.page) == []


def test_n5_maintenance_mode_creates_nothing_and_keeps_the_queue(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("create", status=503, body="Database offline for maintenance")
    send(s.page)
    assert "en maintenance (lecture seule)" in queue_text(s.page)
    assert fake.creates == []
    assert queue_ids(s.page) == [101]


def test_n6_a_server_error_is_not_retried(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", status=500, body="Internal Server Error")
    send(s.page)
    assert "le serveur OSM a renvoyé une erreur" in queue_text(s.page)
    assert fake.count("upload") == 1
    assert queue_ids(s.page) == [101]
    assert fake.open_changesets() == []


def test_n7_a_slow_server_cannot_be_hit_twice_by_a_double_click(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    s.page.check('input[name="cs-source"][value="survey"]')
    hold_api(s.page, "/changeset/create", 1500)
    s.page.click('[data-edit-action="send"]')
    s.page.wait_for_timeout(300)
    assert s.page.evaluate("document.querySelector('[data-edit-action=\"send\"]').disabled")
    s.page.evaluate("document.querySelector('[data-edit-action=\"send\"]').click()")
    wait_idle(s.page)
    assert len(fake.creates) == 1


def test_n8_a_failure_on_the_second_changeset_keeps_the_rest_queued(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue A", "Astraat"))
    fake.add_way(102, line_at(FAR_SOUTH), street("Rue B", "Bstraat"))
    fake.add_way(103, line_at(FAR_WEST), street("Rue C", "Cstraat"))
    s = session(queue=[intent_for(fake, 101), intent_for(fake, 102), intent_for(fake, 103)])
    prepare(s.page)
    assert "3 changesets vont être créés" in queue_text(s.page)
    fake.inject("create", status=500, skip=1)
    send(s.page)
    assert [u["ways"] for u in fake.uploads] == [[101]]
    assert queue_ids(s.page) == [102, 103]


def test_l1_a_rate_limited_account_keeps_what_was_not_sent(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue A", "Astraat"))
    fake.add_way(102, line_at(FAR_SOUTH), street("Rue B", "Bstraat"))
    s = session(queue=[intent_for(fake, 101), intent_for(fake, 102)])
    prepare(s.page)
    fake.inject("create", status=429, body="Changeset rate limit exceeded", skip=1)
    send(s.page)
    assert "compte récent" in queue_text(s.page)
    assert [u["ways"] for u in fake.uploads] == [[101]]
    assert queue_ids(s.page) == [102]


def test_l2_download_limit_empties_the_candidate_layer(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session()
    wait_candidates(s.page, 1)
    wait_settled(s.page, fake)
    before = fake.count("map")
    fake.inject("map", status=509, body="You have downloaded too much data")
    move_map(s.page, 17.6, CENTER[1], CENTER[0] + 0.05)
    wait_for_calls(s.page, fake, "map", before)
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('trop de données téléchargées')")
    assert s.page.evaluate("async () => { const { store } = await import('/map/store.js'); return store.map.querySourceFeatures('edit-candidates').length; }") == 0
    calls = fake.count("map")
    assert int(s.page.evaluate("localStorage.getItem('bpn.apiPause.dev')")) > 0
    move_map(s.page, 17.6, CENTER[1], CENTER[0] + 0.10)
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('appels suspendus')")
    assert fake.count("map") == calls


def requested_areas(fake):
    areas = []
    for name, url in fake.calls:
        if name == "map":
            w, south, e, n = (float(v) for v in parse_qs(urlparse(url).query)["bbox"][0].split(","))
            areas.append((e - w) * (n - south))
    return areas


def test_l3_a_too_large_area_is_never_requested(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session()
    wait_candidates(s.page, 1)
    s.page.set_viewport_size({"width": 10000, "height": 8000})
    wait(s.page, "async () => { const { store } = await import('/map/store.js'); return store.map.getCanvas().clientWidth === 10000; }")
    move_map(s.page, 17, CENTER[1] + 0.0001, CENTER[0])
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('trop grande ou trop dense')")
    time.sleep(0.6)
    assert requested_areas(fake)
    assert max(requested_areas(fake)) <= 0.001
    assert s.page.evaluate("async () => { const { store } = await import('/map/store.js'); return store.map.querySourceFeatures('edit-candidates').length; }") == 0


@pytest.mark.parametrize("count,changesets", [(50, 1), (51, 2)])
def test_l4_fifty_ways_fit_in_one_changeset_fifty_one_need_two(session, fake, count, changesets):
    queue = []
    for i in range(count):
        wid = 1000 + i
        fake.add_way(wid, line_at(CENTER, dx=(i % 10) * 0.0004, dy=(i // 10) * 0.0004, length=0.0003), street(f"Rue {i}", f"{i}straat"))
        queue.append(intent_for(fake, wid))
    s = session(queue=queue)
    prepare(s.page)
    label = "1 changeset va être créé" if changesets == 1 else f"{changesets} changesets vont être créés"
    assert label in queue_text(s.page)


def test_l5_too_many_areas_are_refused_before_creating_anything(session, fake):
    for i, center in enumerate([CENTER, FAR_SOUTH, FAR_WEST, FAR_EAST]):
        fake.add_way(101 + i, line_at(center), street(f"Rue {i}", f"{i}straat"))
    s = session(queue=[intent_for(fake, 101 + i) for i in range(4)])
    prepare(s.page)
    assert "4 zones" in queue_text(s.page)
    assert s.page.query_selector('[data-edit-action="send"]') is None
    assert fake.creates == []


def test_s1_a_revoked_authorisation_keeps_the_queue(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("create", status=401, body="Couldn't authenticate you")
    send(s.page)
    assert "session OSM a expiré" in queue_text(s.page)
    assert queue_ids(s.page) == [101]
    assert s.page.evaluate("localStorage.getItem('__osmAuth')") is None
    assert "Se connecter à OSM" in s.page.inner_text("#edit-auth")


def test_s2_a_blocked_account_is_not_retried(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("create", status=403, body="Your access to the API has been blocked")
    send(s.page)
    assert "compte est peut-être bloqué" in queue_text(s.page)
    assert fake.count("create") == 1
    assert queue_ids(s.page) == [101]


def test_s3_logging_out_in_another_tab_stops_the_send(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    other = s.open()
    other.click('[data-edit-action="logout"]')
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Se connecter à OSM')")
    assert s.page.is_disabled('[data-edit-action="send"]')
    s.page.wait_for_timeout(300)
    assert fake.creates == []
    assert "Se connecter à OSM" in s.page.inner_text("#edit-auth")
    assert queue_ids(s.page) == [101]
    other.close()


def test_s5_a_token_from_another_environment_is_purged_on_load(session, fake):
    s = session(auth_env="prod")
    assert s.page.evaluate("localStorage.getItem('__osmAuth')") is None
    assert "Connecté" not in s.page.inner_text("#edit-auth")


def dev_client_id():
    source = (Path(__file__).resolve().parent.parent / "edit" / "env.js").read_text(encoding="utf-8")
    return re.search(r'dev: Object\.freeze\(\{[^}]*?clientId: "([^"]+)"', source, re.S).group(1)


def test_logging_out_revokes_the_token_on_the_oauth_server(session, fake):
    s = session()
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connecté')")
    s.page.click('[data-edit-action="logout"]')
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Se connecter à OSM')")
    assert s.page.evaluate("localStorage.getItem('__osmAuth')") is None
    assert len(fake.revoked) == 1
    form = fake.revoked[0]["form"]
    assert form["token"] == "token"
    assert form["token_type_hint"] == "access_token"
    assert form["client_id"] == dev_client_id()
    assert fake.revoked[0]["content_type"].startswith("application/x-www-form-urlencoded")
    assert s.page.query_selector("[data-edit-revoke]") is None


def test_a_revocation_that_fails_says_so_and_links_to_the_authorised_applications(session, fake):
    s = session()
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connecté')")
    fake.inject("revoke", status=503, body="Service Unavailable")
    s.page.click('[data-edit-action="logout"]')
    wait(s.page, "() => document.querySelector('[data-edit-revoke]') !== null")
    assert s.page.evaluate("localStorage.getItem('__osmAuth')") is None
    notice = s.page.inner_text("[data-edit-revoke]")
    assert "n'a pas confirmé la révocation" in notice
    href = s.page.get_attribute("[data-edit-revoke] a", "href")
    assert href == f"https://{DEV_HOST}/oauth2/authorized_applications"
    assert "Se connecter à OSM" in s.page.inner_text("#edit-auth")


def test_a_revoked_session_also_revokes_the_token(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("create", status=401, body="Couldn't authenticate you")
    send(s.page)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Se connecter à OSM')")
    assert [r["form"]["token"] for r in fake.revoked] == ["token"]


def test_a_tampered_queue_entry_is_dropped_and_never_uploaded(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    fake.add_way(102, line_at(CENTER, dy=0.0005), street("Rue Autre", "Anderestraat"))
    bad_value = intent_for(fake, 101, {"sidewalk:both": "<b>no</b>"})
    bad_unset = {**intent_for(fake, 102, {"sidewalk:both": "no"}), "unset": ["sidewalk:left"]}
    s = session(queue=[bad_value, bad_unset])
    prepare(s.page)
    text = queue_text(s.page)
    assert text.count("intention invalide") == 2
    assert "<b>" not in s.page.inner_html("#edit-queue").replace("&lt;b&gt;", "")
    assert fake.count("ways") == 0
    assert fake.count("way") == 0
    assert s.page.query_selector('[data-edit-action="send"]') is None
    assert fake.creates == [] and fake.uploads == []
    assert queue_ids(s.page) == []


def test_each_changeset_carries_its_own_comment_and_reviewer_tags(session, fake):
    for i in range(3):
        fake.add_way(101 + i, line_at(CENTER, dy=i * 0.0005), street(f"Rue Nord {i}", f"Noordstraat {i}"))
    fake.add_way(201, line_at(FAR_SOUTH), street("Rue Sud", "Zuidstraat"))
    s = session(queue=[intent_for(fake, w) for w in (101, 102, 103, 201)])
    prepare(s.page)
    s.page.fill('input[name="cs-hashtags"]', "#test")
    s.page.fill('input[name="cs-remark"]', "vérifié sur place")
    send(s.page)
    comments = [c["tags"]["comment"] for c in fake.creates]
    assert comments == [
        "Woluwe-Saint-Lambert - Sint-Lambrechts-Woluwe : add sidewalk tags on 3 residential streets - vérifié sur place #test",
        "Rue Sud/Zuidstraat - add sidewalk tags - vérifié sur place #test",
    ]
    tags = fake.creates[0]["tags"]
    assert tags["created_by"].startswith("BrusselsPedestrianNetwork ")
    assert tags["osm_api_js_version"] == "4.0.1"
    assert tags["source"] == "survey"
    assert tags["hashtags"] == "#test"
    assert tags["locale"] == "fr"
    assert tags["changesets_count"] == "12"
    assert fake.creates[1]["tags"]["changesets_count"] == "13"
    assert tags["host"].endswith("/test-api/devtest.html")
    assert tags["imagery_used"] == "UrbIS Ortho"
    assert "bpn:osm-api-js" not in tags


def selected_way(page):
    return page.evaluate("() => { const m = document.getElementById('edit-detail').textContent.match(/w(\\d+)/); return m ? Number(m[1]) : null; }")


def wait_selected(page, way_id):
    wait(page, f"() => document.getElementById('edit-detail').textContent.includes('w{way_id}') && !!document.querySelector('[data-edit-action=choose]')")


def three_streets(fake):
    fake.add_way(101, line_at(CENTER), street("Rue A", "Astraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue B", "Bstraat"))
    fake.add_way(103, line_at(CENTER, dy=-0.0009), street("Rue C", "Cstraat"))


def test_a_neighbourhood_is_tagged_from_the_keyboard_alone(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    s.page.keyboard.press("s")
    wait_selected(s.page, 102)
    assert queue_ids(s.page) == [101]
    s.page.keyboard.press("p")
    wait_selected(s.page, 103)
    assert json.loads(s.page.evaluate("localStorage.getItem('bpn.skipped.dev')")) == [102]
    s.page.keyboard.press("d")
    s.page.keyboard.press("y")
    assert queue_ids(s.page) == [101]
    s.page.keyboard.press("n")
    wait(s.page, "() => document.getElementById('edit-nav').textContent.includes('Tous les candidats de la vue ont été parcourus')")
    stored = json.loads(s.page.evaluate("localStorage.getItem('bpn.queue.dev')"))
    assert [(i["wayId"], i["set"]) for i in stored] == [(101, {"sidewalk:both": "separate"}), (103, {"sidewalk:left": "yes", "sidewalk:right": "no"})]
    s.page.keyboard.press("Escape")
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose]')")
    assert "1 rue passée" in s.page.inner_text("#edit-nav")


def test_tab_and_typing_never_trigger_an_edit(session, fake):
    three_streets(fake)
    s = session(queue=[])
    wait_candidates(s.page, 3)
    s.page.keyboard.press("Tab")
    s.page.keyboard.press("Tab")
    time.sleep(0.3)
    assert selected_way(s.page) is None
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    s.page.keyboard.press("s")
    wait_selected(s.page, 102)
    s.page.fill('input[name="cs-remark"]', "")
    s.page.focus('input[name="cs-remark"]')
    s.page.keyboard.type("syn dp")
    s.page.keyboard.press("ArrowRight")
    time.sleep(0.3)
    assert s.page.input_value('input[name="cs-remark"]') == "syn dp"
    assert queue_ids(s.page) == [101]
    assert selected_way(s.page) == 102
    assert s.page.evaluate("localStorage.getItem('bpn.skipped.dev')") in (None, "[]")


def test_skipped_streets_are_left_out_until_shown_again(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    s.page.click('[data-edit-action="skip"]')
    wait_selected(s.page, 102)
    s.page.keyboard.press("Escape")
    s.page.reload()
    wait_candidates(s.page, 3)
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 102)
    s.page.keyboard.press("Escape")
    s.page.click('[data-edit-action="reset-skipped"]')
    assert s.page.evaluate("localStorage.getItem('bpn.skipped.dev')") == "[]"
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)


def test_the_panel_can_be_docked_left_or_at_the_bottom_and_stays_there(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue A", "Astraat"))
    s = session()
    wait_candidates(s.page, 1)
    box = lambda: s.page.evaluate("(() => { const r = document.getElementById('edit-dock').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")
    assert box()[0] > 700
    s.page.click('#edit-dock-position [data-dock="left"]')
    assert s.page.get_attribute("#edit-dock", "data-position") == "left"
    assert box()[2] < 400
    assert s.page.evaluate("document.getElementById('header').classList.contains('closed')")
    assert s.page.evaluate("localStorage.getItem('bpn.dockPosition')") == "left"
    s.page.reload()
    wait_candidates(s.page, 1)
    assert s.page.get_attribute("#edit-dock", "data-position") == "left"
    assert s.page.get_attribute('#edit-dock-position [data-dock="left"]', "aria-pressed") == "true"
    s.page.click('#edit-dock-position [data-dock="bottom"]')
    left, top, right, bottom = box()
    assert top > 300 and 200 < left and right < 934
    basemap = s.page.evaluate("document.getElementById('basemap-control').getBoundingClientRect().right")
    assert left > basemap
    s.page.focus('#edit-dock-position [data-dock="right"]')
    s.page.keyboard.press("Enter")
    assert s.page.get_attribute("#edit-dock", "data-position") == "right"


@pytest.mark.parametrize("position", ["right", "left", "bottom"])
def test_a_way_hidden_under_the_panel_is_brought_into_view(session, fake, position):
    offsets = {"right": (0.0016, 0.0), "left": (-0.0016, 0.0), "bottom": (0.0, -0.0007)}
    dx, dy = offsets[position]
    fake.add_way(101, line_at(CENTER, dx=dx, dy=dy, length=0.0005), street("Rue Cachée", "Verborgenstraat"))
    s = session()
    wait_candidates(s.page, 1)
    s.page.click(f'#edit-dock-position [data-dock="{position}"]')
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    time.sleep(0.8)
    info = s.page.evaluate(f"""async () => {{
      const {{ store }} = await import('/map/store.js');
      const p = store.map.project([{CENTER[0] + dx}, {CENTER[1] + dy}]);
      const r = document.getElementById('edit-dock').getBoundingClientRect();
      return {{ x: p.x, y: p.y, dock: [r.left, r.top, r.right, r.bottom] }};
    }}""")
    left, top, right, bottom = info["dock"]
    if position == "right":
        assert info["x"] < left - 12
    elif position == "left":
        assert info["x"] > right + 12
    else:
        assert info["y"] < top - 12


def test_a_visible_way_does_not_move_the_map(session, fake):
    fake.add_way(101, line_at(CENTER, dx=-0.0004), street("Rue Visible", "Zichtbaarstraat"))
    s = session()
    wait_candidates(s.page, 1)
    before = s.page.evaluate("location.hash")
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    time.sleep(0.6)
    assert s.page.evaluate("location.hash") == before


def locked(page):
    return page.evaluate("() => !!document.querySelector('[data-edit-action=choose][disabled]')")


def map_eval(page, body):
    return page.evaluate(f"async () => {{ const {{ store }} = await import('/map/store.js'); const m = store.map; {body} }}")


def move_map(page, zoom, lat, lon):
    center = map_eval(page, f"m.jumpTo({{ center: [{lon}, {lat}], zoom: {zoom} }}); const c = m.getCenter(); return [c.lng, c.lat, m.getZoom()];")
    assert abs(center[0] - lon) < 1e-6 and abs(center[1] - lat) < 1e-6 and abs(center[2] - zoom) < 1e-6, center


def wait_for_calls(page, fake, endpoint, above, timeout=10):
    end = time.time() + timeout
    while time.time() < end and fake.count(endpoint) <= above:
        page.wait_for_timeout(50)
    assert fake.count(endpoint) > above, (endpoint, fake.count(endpoint), page.inner_text("#edit-status"))


def wait_settled(page, fake, endpoint="map", quiet=0.6, timeout=10):
    end = time.time() + timeout
    seen, since = fake.count(endpoint), time.time()
    while time.time() < end:
        page.wait_for_timeout(50)
        if fake.count(endpoint) != seen:
            seen, since = fake.count(endpoint), time.time()
        elif time.time() - since >= quiet:
            return
    raise AssertionError(f"{endpoint} calls never settled")


def whole_way_inside(page, coords):
    return map_eval(page, f"""
      const dock = document.getElementById('edit-dock');
      const r = dock.getBoundingClientRect();
      const c = m.getCanvas();
      const right = dock.classList.contains('open') ? r.left : c.clientWidth;
      return {json.dumps(coords)}.every(p => {{ const q = m.project(p); return q.x >= 0 && q.y >= 0 && q.x <= right && q.y <= c.clientHeight; }});""")


def test_a_long_street_seen_whole_once_can_then_be_edited_zoomed_in(session, fake):
    long_line = line_at(CENTER, length=0.012)
    fake.add_way(101, long_line, street("Longue Rue", "Lange Straat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    assert whole_way_inside(s.page, long_line)
    seen = json.loads(s.page.evaluate("localStorage.getItem('bpn.reviewed.dev')"))
    assert seen["101"]["whole"] is True and seen["101"]["v"] == 1
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0] + 0.004}, {CENTER[1]}], zoom: 19 }}); return true;")
    time.sleep(0.5)
    assert not locked(s.page)
    assert "pas encore été vue en entier" not in s.page.inner_text("#edit-detail")
    s.page.keyboard.press("s")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")
    assert queue_ids(s.page) == [101]


def test_a_street_never_seen_whole_stays_locked_until_shown(session, fake):
    long_line = line_at(CENTER, length=0.012)
    fake.add_way(101, long_line, street("Longue Rue", "Lange Straat"))
    s = session()
    wait_candidates(s.page, 1)
    s.page.evaluate("""async () => {
      const { store } = await import('/map/store.js');
      store.map.easeTo = () => {};
    }""")
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('pas encore été vue en entier')")
    assert locked(s.page)
    s.page.keyboard.press("s")
    time.sleep(0.3)
    assert queue_ids(s.page) == []
    s.page.reload()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    assert whole_way_inside(s.page, long_line)


def test_a_street_seen_whole_is_not_zoomed_out_again_when_selected_later(session, fake):
    long_line = line_at(CENTER, length=0.012)
    fake.add_way(101, long_line, street("Longue Rue", "Lange Straat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    s.page.keyboard.press("Escape")
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0]}, {CENTER[1]}], zoom: 19 }}); return true;")
    time.sleep(0.6)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    time.sleep(0.5)
    assert abs(map_eval(s.page, "return m.getZoom();") - 19) < 0.01
    assert not locked(s.page)


def test_a_review_zoom_asks_to_go_along_the_whole_street_close_up(session, fake):
    line = line_at(CENTER, length=0.0016)
    fake.add_way(101, line, street("Rue Proche", "Nabijstraat"))
    s = session()
    s.url = s.url.replace("devtest.html#", "devtest.html?review-zoom=18.6#")
    s.page.close()
    s.page = s.open()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => !!document.querySelector('[data-edit-action=review-next]')")
    assert "zoom 18,6" in s.page.inner_text("#edit-detail")
    assert locked(s.page)
    for _ in range(12):
        if not s.page.query_selector('[data-edit-action="review-next"]'):
            break
        s.page.click('[data-edit-action="review-next"]')
        time.sleep(0.5)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    assert map_eval(s.page, "return m.getZoom();") >= 18.6
    assert json.loads(s.page.evaluate("localStorage.getItem('bpn.reviewed.dev')"))["101"]["detail"] is True
    s.page.keyboard.press("y")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")


def chip_top(page):
    return page.evaluate("document.querySelector('[data-side=both][data-value=yes]').getBoundingClientRect().top")


def test_the_choices_do_not_move_when_the_close_look_ends(session, fake):
    line = line_at(CENTER, length=0.0016)
    fake.add_way(101, line, street("Rue Proche", "Nabijstraat"))
    s = session(settings={"reviewZoom": "18.6"})
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => !!document.querySelector('[data-edit-action=review-next]')")
    before = chip_top(s.page)
    gate = s.page.evaluate("document.querySelector('.edit-gate').getBoundingClientRect().bottom")
    assert gate <= before
    for _ in range(12):
        if not s.page.query_selector('[data-edit-action="review-next"]'):
            break
        s.page.click('[data-edit-action="review-next"]')
        time.sleep(0.5)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    assert s.page.query_selector(".edit-gate-done")
    assert abs(chip_top(s.page) - before) < 1


def test_a_queued_street_reopens_from_the_queue_with_its_choice(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    s.page.click('[data-side="both"][data-value="separate"]')
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")
    s.page.keyboard.press("Escape")
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose]')")
    s.page.click('[data-edit-action="open-queued"][data-way-id="101"]')
    wait_selected(s.page, 101)
    wait(s.page, "() => document.querySelector('[data-side=both][data-value=separate]').getAttribute('aria-pressed') === 'true'")
    s.page.click('[data-side="both"][data-value="no"]')
    wait(s.page, "() => document.getElementById('edit-queue').textContent.includes('sidewalk:both=no')")
    stored = json.loads(s.page.evaluate("localStorage.getItem('bpn.queue.dev')"))
    assert [(i["wayId"], i["set"]) for i in stored] == [(101, {"sidewalk:both": "no"})]


def hold_api(page, fragment, ms, times=1):
    page.evaluate(f"""() => {{
      const inner = window.fetch;
      let left = {times};
      window.fetch = async (input, init) => {{
        const url = typeof input === 'string' ? input : input.url;
        const held = left > 0 && url.includes({json.dumps(fragment)});
        if (held) left -= 1;
        const response = await inner(input, init);
        if (held) await new Promise(r => setTimeout(r, {ms}));
        return response;
      }};
    }}""")


def hold_way_reads(page, way_id, ms):
    hold_api(page, f"/way/{way_id}/full", ms)


def test_escape_while_the_next_street_is_loading_cancels_it(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    hold_way_reads(s.page, 102, 1500)
    s.page.click('[data-side="both"][data-value="separate"]')
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('Lecture du way sur OSM')")
    s.page.keyboard.press("Escape")
    time.sleep(2.0)
    assert s.page.query_selector("[data-edit-action=choose]") is None
    assert "Lecture du way" not in s.page.inner_text("#edit-detail")
    assert map_eval(s.page, "return m.querySourceFeatures('edit-selection').length;") == 0
    assert queue_ids(s.page) == [101]


def test_a_slow_answer_for_an_earlier_click_never_replaces_the_latest_street(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    hold_way_reads(s.page, 101, 1500)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('Lecture du way sur OSM')")
    click_way(s.page, CENTER[0], CENTER[1] - 0.0004 + 0.00001, 102)
    time.sleep(2.0)
    wait_selected(s.page, 102)
    assert "w101" not in s.page.inner_text("#edit-detail")


def selection_queued(page):
    return map_eval(page, "const f = m.querySourceFeatures('edit-selection')[0]; return f ? f.properties.queued : null;")


def test_the_selected_street_is_yellow_then_green_once_queued(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue B", "Bstraat"))
    s = session()
    wait_candidates(s.page, 2)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "async () => { const { store } = await import('/map/store.js'); return store.map.querySourceFeatures('edit-selection').length > 0; }")
    assert selection_queued(s.page) is False
    assert map_eval(s.page, "return m.getPaintProperty('edit-candidates-selected', 'line-color')") == ["case", ["boolean", ["get", "queued"], False], "#16a34a", "#f5c518"]
    s.page.click('[data-edit-action="mode"][data-mode="sides"]')
    s.page.click('[data-side="left"][data-value="yes"]')
    s.page.click('[data-side="right"][data-value="no"]')
    wait_selected(s.page, 102)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "async () => { const { store } = await import('/map/store.js'); const f = store.map.querySourceFeatures('edit-selection')[0]; return !!f && f.properties.queued === true; }")


def test_a_street_that_would_open_a_fourth_zone_is_locked_before_any_edit(session, fake):
    fake.add_way(201, line_at(FAR_SOUTH), street("Rue Sud", "Zuidstraat"))
    fake.add_way(202, line_at(FAR_WEST), street("Rue Ouest", "Weststraat"))
    fake.add_way(203, line_at(FAR_EAST), street("Rue Est", "Ooststraat"))
    fake.add_way(101, line_at(CENTER), street("Rue Centre", "Centrumstraat"))
    s = session(queue=[intent_for(fake, w) for w in (201, 202, 203)])
    wait(s.page, "() => document.getElementById('edit-queue').textContent.includes('3 changesets sur 3')")
    assert "Limite atteinte" in queue_text(s.page)
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    assert locked(s.page)
    assert "au-delà des 3 changesets autorisés" in s.page.inner_text("#edit-detail")
    s.page.keyboard.press("n")
    time.sleep(0.3)
    assert queue_ids(s.page) == [201, 202, 203]
    s.page.click('#edit-detail [data-edit-action="plan"]')
    wait_idle(s.page)
    assert "3 changesets vont être créés" in queue_text(s.page)
    send(s.page)
    assert "3 changesets envoyés" in queue_text(s.page)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    s.page.keyboard.press("n")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")


def test_a_street_in_a_zone_already_queued_can_still_be_added_at_the_limit(session, fake):
    fake.add_way(201, line_at(FAR_SOUTH), street("Rue Sud", "Zuidstraat"))
    fake.add_way(202, line_at(FAR_WEST), street("Rue Ouest", "Weststraat"))
    fake.add_way(101, line_at(CENTER), street("Rue Centre", "Centrumstraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue Voisine", "Buurstraat"))
    s = session(queue=[intent_for(fake, w) for w in (201, 202, 101)])
    wait_candidates(s.page, 2)
    assert "Limite atteinte" in queue_text(s.page)
    click_way(s.page, CENTER[0], CENTER[1] - 0.0004 + 0.00001, 102)
    assert not locked(s.page)
    s.page.keyboard.press("y")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('102')")


def test_an_over_long_source_is_refused_in_the_form_before_anything_is_sent(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    s.page.check('input[name="cs-source"][value="survey"]')
    s.page.fill('input[name="cs-source-other"]', "é" * 250)
    wait(s.page, "() => document.querySelector('[data-field-error=source]').textContent.includes('Sources trop longues : 257 caractères')")
    assert s.page.is_disabled('[data-edit-action="send"]')
    s.page.fill('input[name="cs-source-other"]', "é" * 240)
    wait(s.page, "() => document.querySelector('[data-field-error=source]').textContent === ''")
    assert not s.page.is_disabled('[data-edit-action="send"]')
    assert s.page.get_attribute('input[name="cs-hashtags"]', "maxlength") == "255"
    s.page.fill('input[name="cs-hashtags"]', " ".join(f"x{i}" for i in range(70)))
    wait(s.page, "() => document.querySelector('[data-field-error=hashtags]').textContent.includes('Hashtags trop longs')")
    assert s.page.is_disabled('[data-edit-action="send"]')
    s.page.evaluate("document.querySelector('[data-edit-action=send]').disabled = false")
    s.page.click('[data-edit-action="send"]')
    wait_idle(s.page)
    assert "Hashtags trop longs" in queue_text(s.page)
    assert fake.creates == []


def test_a_second_conflict_is_named_from_versions_whatever_the_api_says(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.conflict_text = "Un texte que personne ne sait analyser"
    bump = lambda f: f.edit_way(101, tags={**f.ways[101]["tags"], "maxspeed": str(f.ways[101]["version"])})
    fake.inject("upload", hook=bump, times=2)
    send(s.page)
    text = queue_text(s.page)
    assert "w101 a été modifié sur OSM entre-temps" in text
    assert queue_ids(s.page) == []
    assert fake.uploads == []
    assert fake.open_changesets() == []
    assert fake.count("close") >= 2


def map_zoom(page):
    return map_eval(page, "return m.getZoom();")


def test_after_a_long_street_the_next_one_brings_the_map_back_close(session, fake):
    long_line = line_at(CENTER, length=0.012)
    short_line = line_at(CENTER, dy=-0.0004)
    fake.add_way(101, long_line, street("Longue Rue", "Lange Straat"))
    fake.add_way(102, short_line, street("Rue Courte", "Korte Straat"))
    s = session()
    wait_candidates(s.page, 2)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]')")
    assert map_zoom(s.page) < 17
    s.page.keyboard.press("s")
    wait_selected(s.page, 102)
    time.sleep(0.6)
    assert 17 <= map_zoom(s.page) <= 19.0001
    assert whole_way_inside(s.page, short_line)
    assert not locked(s.page)
    s.page.keyboard.press("y")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('102')")
    assert queue_ids(s.page) == [101, 102]
    assert max(requested_areas(fake)) <= 0.001


def test_a_short_street_selected_from_far_out_is_framed_close(session, fake):
    line = line_at(CENTER)
    fake.add_way(101, line, street("Rue Test", "Teststraat"))
    s = session(zoom=15.5)
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]') && !!document.querySelector('[data-edit-action=choose]')")
    assert 17 <= map_zoom(s.page) <= 19.0001
    assert whole_way_inside(s.page, line)
    map_eval(s.page, "m.jumpTo({ zoom: 18.5 }); return true;")
    time.sleep(0.3)
    s.page.keyboard.press("Escape")
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    time.sleep(0.5)
    assert abs(map_zoom(s.page) - 18.5) < 0.01


def test_the_close_look_at_zoom_18_7_unlocks_once_the_whole_street_is_seen(session, fake):
    line = line_at(CENTER, length=0.004)
    fake.add_way(101, line, street("Rue Moyenne", "Middenstraat"))
    s = session(settings={"reviewZoom": "18.7"})
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => !!document.querySelector('[data-edit-action=review-next]')")
    assert "zoom 18,7" in s.page.inner_text("#edit-detail")
    for _ in range(20):
        if not s.page.query_selector('[data-edit-action="review-next"]'):
            break
        s.page.click('[data-edit-action="review-next"]')
        time.sleep(0.5)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    assert map_zoom(s.page) >= 18.7


def test_streets_beyond_the_first_view_are_chained_from_the_keyboard(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue A", "Astraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0006, length=0.004), street("Rue B", "Bstraat"))
    fake.add_way(103, line_at(CENTER, dy=-0.0012, length=0.0006), street("Rue C", "Cstraat"))
    fake.add_way(104, line_at(CENTER, dy=0.0010, dx=0.002, length=0.0006), street("Rue D", "Dstraat"))
    fake.add_way(105, line_at(CENTER, dy=-0.0030, dx=0.004, length=0.0006), street("Rue E", "Estraat"))
    s = session()
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('candidats dans la vue')")
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    for count in range(1, 6):
        if count > 1:
            wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]') && !document.getElementById('edit-nav').textContent.includes('Recherche')")
            time.sleep(0.4)
        s.page.keyboard.press("n")
        wait(s.page, f"() => JSON.parse(localStorage.getItem('bpn.queue.dev') || '[]').length === {count}")
    assert sorted(queue_ids(s.page)) == [101, 102, 103, 104, 105]
    assert max(requested_areas(fake)) <= 0.001


def test_keys_pressed_while_searching_for_the_next_street_change_nothing(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue A", "Astraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0045, dx=0.005, length=0.0006), street("Rue Loin", "Verstraat"))
    s = session()
    wait_candidates(s.page, 1)
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    time.sleep(0.8)
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('dans la vue')")
    hold_api(s.page, "/map.json", 1500, times=3)
    s.page.keyboard.press("n")
    wait(s.page, "() => document.getElementById('edit-nav').textContent.includes('Recherche de rues voisines')")
    s.page.keyboard.press("s")
    wait_selected(s.page, 102)
    stored = json.loads(s.page.evaluate("localStorage.getItem('bpn.queue.dev')"))
    assert [(i["wayId"], i["set"]) for i in stored] == [(101, {"sidewalk:both": "no"})]


def edit_ui(page):
    return page.evaluate("""() => ({
      active: BPNEdit.isActive(),
      body: document.body.classList.contains('is-editing'),
      dock: !document.getElementById('edit-dock').hidden,
      bar: !document.getElementById('edit-bar').hidden,
    })""")


def candidates_visible(page):
    return page.evaluate("""async () => {
      const { store } = await import('/map/store.js');
      return store.map.getLayoutProperty('edit-candidates', 'visibility') !== 'none';
    }""")


def test_the_page_opens_like_the_main_map_and_loads_nothing_until_editing(session, fake):
    three_streets(fake)
    s = session(editing=False)
    time.sleep(0.8)
    ui = edit_ui(s.page)
    assert (ui["active"], ui["body"], ui["dock"], ui["bar"]) == (False, False, False, False)
    assert fake.count("map") == 0
    s.page.keyboard.press("ArrowRight")
    s.page.keyboard.press("s")
    assert selected_way(s.page) is None and queue_ids(s.page) == []
    assert s.page.evaluate("document.getElementById('legend').classList.contains('open')")
    enter_edit(s.page)
    wait_candidates(s.page, 3)
    assert candidates_visible(s.page)
    ui = edit_ui(s.page)
    assert (ui["active"], ui["body"], ui["dock"], ui["bar"]) == (True, True, True, True)
    assert not s.page.is_visible("#header")


def test_leaving_with_an_empty_queue_needs_no_confirmation(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    s.page.click("#edit-exit")
    ui = edit_ui(s.page)
    assert (ui["active"], ui["dock"], ui["bar"]) == (False, False, False)
    assert not s.page.evaluate("document.getElementById('edit-exit-dialog').open")
    assert not candidates_visible(s.page)
    assert s.page.is_visible("#header")
    assert s.page.evaluate("document.activeElement.id") == "edit-enter"
    calls = fake.count("map")
    s.page.mouse.move(400, 400)
    s.page.mouse.down()
    s.page.mouse.move(300, 300, steps=5)
    s.page.mouse.up()
    time.sleep(0.8)
    assert fake.count("map") == calls


def test_leaving_with_pending_edits_can_keep_them_for_later(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    s.page.click("#edit-exit")
    assert s.page.evaluate("document.getElementById('edit-exit-dialog').open")
    assert "1 modification n'est pas encore envoyée" in s.page.inner_text("#edit-exit-dialog")
    s.page.click('[data-exit-choice="stay"]')
    assert edit_ui(s.page)["active"] is True
    s.page.click("#edit-exit")
    s.page.click('[data-exit-choice="keep"]')
    assert edit_ui(s.page)["active"] is False
    assert queue_ids(s.page) == [101]
    assert s.page.inner_text("#edit-enter-pending") == "1 en attente"
    enter_edit(s.page)
    assert "File d'édition (1)" in queue_text(s.page)


def test_leaving_can_discard_pending_edits(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue B", "Bstraat"))
    s = session(queue=[intent_for(fake, 101), intent_for(fake, 102)])
    s.page.click("#edit-exit")
    assert "2 modifications ne sont pas encore envoyées" in s.page.inner_text("#edit-exit-dialog")
    s.page.click('[data-exit-choice="discard"]')
    assert edit_ui(s.page)["active"] is False
    assert queue_ids(s.page) == []
    assert not s.page.is_visible("#edit-enter-pending")
    assert fake.count("create") == 0


def test_escape_in_the_exit_dialog_keeps_editing(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    s.page.click("#edit-exit")
    s.page.keyboard.press("Escape")
    assert not s.page.evaluate("document.getElementById('edit-exit-dialog').open")
    assert edit_ui(s.page)["active"] is True
    assert queue_ids(s.page) == [101]


def test_a_reload_stays_in_editing_mode_but_a_new_tab_does_not(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    s.page.reload()
    wait(s.page, "() => window.BPNEdit && BPNEdit.isActive()")
    wait_candidates(s.page, 3)
    other = s.open(editing=False)
    time.sleep(0.5)
    assert other.evaluate("BPNEdit.isActive()") is False


def test_edit_here_in_the_popup_opens_the_editor_on_that_way(session, fake):
    three_streets(fake)
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    assert s.page.evaluate("BPNEdit.canEdit({ sw: 'unknown', highway: 'residential' })") is True
    assert s.page.evaluate("BPNEdit.canEdit({ sw: 'unknown', highway: 'tertiary' })") is False
    assert s.page.evaluate("BPNEdit.canEdit({ sw: 'partial', highway: 'residential' })") is False
    html = s.page.evaluate("""() => BPNMap.clickPopups.find(c => c.ids.includes('sidewalk-roads'))
      .format({ osm_id: 102, sw: 'unknown', highway: 'residential', name: 'rue b', length_m: 70 })""")
    assert 'data-bpn-edit-way="102"' in html and "Éditer ici" in html
    other = s.page.evaluate("""() => BPNMap.clickPopups.find(c => c.ids.includes('sidewalk-roads'))
      .format({ osm_id: 103, sw: 'documented', highway: 'residential', name: 'rue c', length_m: 70 })""")
    assert "data-bpn-edit-way" not in other
    click_edit_here(s.page, 102, [list(c) for c in line_at(CENTER, dy=-0.0004)])
    wait_selected(s.page, 102)
    assert edit_ui(s.page)["active"] is True



def side_layers(page):
    return page.evaluate("""async () => {
      const { store } = await import('/map/store.js');
      const m = store.map;
      return ['edit-candidates-selected', 'edit-candidates-left', 'edit-candidates-right']
        .map(id => m.getLayer(id) ? [m.getLayoutProperty(id, 'visibility') || 'visible', m.queryRenderedFeatures({ layers: [id] }).length > 0] : null);
    }""")


def test_the_selection_and_its_sides_survive_a_basemap_change(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    s.page.click("#basemap-toggle")
    s.page.click('.basemap-option[data-id="urbis-ortho"]')
    wait(s.page, "() => localStorage.getItem('bpn-basemap') === 'urbis-ortho'")
    time.sleep(0.6)
    s.page.click('[data-edit-action="mode"][data-mode="sides"]')
    wait(s.page, "async () => { const { store } = await import('/map/store.js'); return !!store.map.getLayer('edit-candidates-left') && store.map.queryRenderedFeatures({ layers: ['edit-candidates-left'] }).length > 0; }")
    assert side_layers(s.page) == [["visible", True], ["visible", True], ["visible", True]]


def api_stats(page):
    return page.evaluate("BPNEdit.apiStats()")


def test_the_dev_meter_counts_exactly_the_calls_the_server_received(session, fake):
    three_streets(fake)
    s = session()
    s.page.evaluate("BPNEdit.resetApiStats()")
    before_map, before_full = fake.count("map"), fake.count("way_full")
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0] + 0.0002}, {CENTER[1]}], zoom: 17.5 }}); return true;")
    wait_candidates(s.page, 3)
    s.page.keyboard.press("ArrowRight")
    wait_selected(s.page, 101)
    s.page.keyboard.press("s")
    wait_selected(s.page, 102)
    time.sleep(0.8)
    stats = api_stats(s.page)
    assert stats["byKind"].get("map", 0) == fake.count("map") - before_map
    assert stats["byKind"].get("wayFull", 0) == fake.count("way_full") - before_full
    assert stats["total"] == sum(stats["byKind"].values())
    assert stats["peakInFlight"] <= 2
    assert stats["lastMinute"] == stats["total"]
    s.page.click("#edit-meter summary")
    text = s.page.inner_text("#edit-meter")
    assert f"Appels API : {stats['total']}" in text and "way/…/full" in text
    s.page.click("[data-edit-action=meter-reset]")
    wait(s.page, "() => BPNEdit.apiStats().total === 0")
    s.page.reload()
    wait(s.page, "() => window.BPNEdit && BPNEdit.isActive()")
    assert api_stats(s.page)["since"] > 0


def test_moving_inside_a_window_already_loaded_sends_no_new_map_call(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    time.sleep(0.5)
    before = fake.count("map")
    for dx, zoom in ((0.0002, 18.7), (-0.0002, 18.7), (0.0, 19.2), (0.0001, 17.2)):
        map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0]} + {dx}, {CENTER[1]}], zoom: {zoom} }}); return true;")
        time.sleep(0.5)
    assert fake.count("map") == before
    assert "candidat" in s.page.inner_text("#edit-status")
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0]} + 0.02, {CENTER[1]}], zoom: 17.5 }}); return true;")
    end = time.time() + 5
    while time.time() < end and fake.count("map") == before:
        s.page.wait_for_timeout(100)
    assert fake.count("map") == before + 1


def test_a_loaded_window_is_reloaded_once_it_is_older_than_the_reuse_limit(session, fake):
    three_streets(fake)
    s = session(settings={"candidateReuseMs": "0"})
    wait_candidates(s.page, 3)
    time.sleep(0.5)
    before = fake.count("map")
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0]} + 0.0002, {CENTER[1]}], zoom: 18.7 }}); return true;")
    end = time.time() + 5
    while time.time() < end and fake.count("map") == before:
        s.page.wait_for_timeout(100)
    assert fake.count("map") == before + 1


def test_the_meter_records_server_refusals(session, fake):
    three_streets(fake)
    fake.inject("map", status=509, body="You have downloaded too much data")
    s = session()
    wait(s.page, "() => (BPNEdit.apiStats().byStatus['509'] || 0) === 1")
    assert api_stats(s.page)["failures"] >= 1


def click_edit_here(page, tile_id, coords):
    page.evaluate("""async ([id, coords]) => {
      const { store } = await import('/map/store.js');
      store.lastClicked = { id, geometry: { type: 'LineString', coordinates: coords } };
      const html = BPNMap.clickPopups.find(c => c.ids.includes('sidewalk-roads'))
        .format({ osm_id: id, sw: 'unknown', highway: 'residential', name: 'x', length_m: 60 });
      new maplibregl.Popup().setLngLat(store.map.getCenter()).setHTML(html).addTo(store.map);
    }""", [tile_id, coords])
    page.click(f'[data-bpn-edit-way="{tile_id}"]')


def test_edit_here_on_dev_finds_the_dev_way_under_the_clicked_tile_way(session, fake):
    three_streets(fake)
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    tile_coords = [[x, y + 0.00003] for x, y in line_at(CENTER, dy=-0.0004)]
    click_edit_here(s.page, 987654321, tile_coords)
    wait_selected(s.page, 102)
    assert s.page.evaluate("BPNEdit.isActive()") is True
    assert fake.count("way_full") >= 1


def test_edit_here_on_dev_says_so_when_nothing_matches(session, fake):
    three_streets(fake)
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    far = [[x, y + 0.0002] for x, y in line_at(CENTER, dy=-0.0004)]
    click_edit_here(s.page, 987654321, far)
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('Aucune rue sans tag sidewalk ne correspond')")
    assert selected_way(s.page) is None


def test_the_left_side_line_is_drawn_left_of_the_way_direction(session, fake):
    fake.add_way(101, [(CENTER[0] - 0.0005, CENTER[1]), (CENTER[0] + 0.0005, CENTER[1])], street("Rue Est", "Ooststraat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1], 101)
    s.page.click('[data-edit-action="mode"][data-mode="sides"]')
    time.sleep(0.5)
    found = map_eval(s.page, f"""
      const p = m.project([{CENTER[0]}, {CENTER[1]}]);
      const at = (dy, id) => m.queryRenderedFeatures([[p.x - 2, p.y + dy - 2], [p.x + 2, p.y + dy + 2]], {{ layers: [id] }}).length > 0;
      const off = 9 + (16 - 9) * (m.getZoom() - 16) / 3;
      return {{ leftNorth: at(-off, 'edit-candidates-left'), leftSouth: at(off, 'edit-candidates-left'),
                rightSouth: at(off, 'edit-candidates-right'), rightNorth: at(-off, 'edit-candidates-right') }};""")
    assert found == {"leftNorth": True, "leftSouth": False, "rightSouth": True, "rightNorth": False}


def test_the_page_never_has_more_than_two_api_calls_in_flight(session, fake):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    s.page.evaluate("BPNEdit.resetApiStats()")
    statuses = s.page.evaluate("""async () => {
      const api = "https://master.apis.dev.openstreetmap.org";
      const calls = [1, 2, 3, 4, 5].map(() => fetch(`${api}/api/0.6/user/details.json`).then(r => r.status));
      return Promise.all(calls);
    }""")
    assert statuses == [200] * 5
    stats = api_stats(s.page)
    limit = s.page.evaluate("BPNEdit.maxConcurrentApi")
    assert 1 <= limit <= 2
    assert stats["byKind"]["user"] == 5
    assert stats["peakInFlight"] == limit
    assert stats["peakWaiting"] == 5 - limit
    assert stats["waiting"] == 0


def test_the_beta_page_runs_in_prod_without_a_client_and_never_touches_the_dev_server(session, fake):
    three_streets(fake)
    s = session(logged_in=False, editing=False, page_name="beta.html")
    assert s.page.evaluate("document.documentElement.dataset.editEnv") == "prod"
    assert s.page.evaluate("BPNEdit.apiStats()") is not None
    assert s.page.evaluate("BPNEdit.maxConcurrentApi") == 1
    assert not [u for u in s.aborted if "openstreetmap.org" in u]
    enter_edit(s.page)
    assert "Client OAuth non configuré" in s.page.inner_text("#edit-auth")
    assert s.page.evaluate("document.querySelector('[data-edit-action=\"login\"]')") is None
    time.sleep(0.5)
    prod_calls = [u for u in s.aborted if "openstreetmap.org" in u]
    assert prod_calls and all(u.startswith("https://api.openstreetmap.org/api/0.6/map") for u in prod_calls)
    assert fake.calls == []


def test_a_dev_login_in_another_tab_never_sends_its_token_from_the_beta_page(session, fake):
    three_streets(fake)
    s = session(logged_in=False, editing=True, page_name="beta.html")
    dev = s.context.new_page()
    dev.goto(s.origin + "test-api/devtest.html")
    wait(dev, "() => window.BPNEdit !== undefined")
    dev.evaluate("""() => {
      localStorage.setItem('__osmAuth', JSON.stringify({ accessToken: 'dev-token', issuedAt: '2026-11-16', scopes: ['read_prefs', 'write_api'] }));
      localStorage.setItem('bpn.authEnv', 'dev');
    }""")
    dev.close()
    before = len(s.aborted_auth)
    map_eval(s.page, "const c = m.getCenter(); m.jumpTo({ center: [c.lng + 0.01, c.lat + 0.005] });")
    end = time.time() + 5
    while time.time() < end and not [u for u, _ in s.aborted_auth[before:] if u.startswith("https://api.openstreetmap.org/api/0.6/map")]:
        s.page.wait_for_timeout(100)
    sent = [(u, a) for u, a in s.aborted_auth[before:] if "openstreetmap.org" in u]
    assert sent and all(u.startswith("https://api.openstreetmap.org/api/0.6/map") for u, _ in sent)
    assert all("dev-token" not in a for _, a in sent)
    assert s.page.evaluate("localStorage.getItem('bpn.authEnv')") == "dev"
    assert "dev-token" in s.page.evaluate("localStorage.getItem('__osmAuth')")
    assert "Client OAuth non configuré" in s.page.inner_text("#edit-auth")


def test_every_api_call_names_this_app_and_never_osm_api_js(session, fake):
    three_streets(fake)
    s = session()
    s.context.add_init_script("""
      window.__apiHeaders = [];
      const inner = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/api/0.6/')) {
          const headers = new Headers((init && init.headers) || (typeof input !== 'string' && input.headers) || undefined);
          window.__apiHeaders.push([url, headers.get('User-Agent')]);
        }
        return inner(input, init);
      };
    """)
    s.page.reload()
    wait_candidates(s.page, 3)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    sent = s.page.evaluate("window.__apiHeaders")
    expected = s.page.evaluate("import('/edit/env.js').then(m => m.USER_AGENT)")
    assert expected.startswith("BrusselsPedestrianNetwork/") and "github.com/PasLoin/Brussels-Pedestrian-Network" in expected
    kinds = {url.split("/api/0.6/")[1].split("?")[0].split(".")[0].split("/")[0] for url, _ in sent}
    assert {"user", "map", "way"} <= kinds, kinds
    assert all(ua == expected for _, ua in sent), sent


def with_source(tags, source_id):
    return {**tags, "@id": str(source_id), "@type": "way"}


def test_edit_here_on_dev_follows_the_original_id_carried_by_the_import(session, fake):
    fake.add_way(101, line_at(CENTER), with_source(street("Rue A", "Astraat"), 555))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), with_source(street("Rue B", "Bstraat"), 1052304744))
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    elsewhere = [[x + 0.0003, y + 0.0002] for x, y in line_at(CENTER, dy=-0.0004)]
    click_edit_here(s.page, 1052304744, elsewhere)
    wait_selected(s.page, 102)


def test_edit_here_on_dev_opens_a_way_already_tagged_there_and_says_so(session, fake):
    tags = with_source({**street("Rue B", "Bstraat"), "sidewalk:both": "separate"}, 1052304744)
    fake.add_way(102, line_at(CENTER, dy=-0.0004), tags)
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    click_edit_here(s.page, 1052304744, [list(c) for c in line_at(CENTER, dy=-0.0004)])
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('w102')")
    assert "rien à faire" in s.page.inner_text("#edit-detail")
    assert not s.page.query_selector('[data-edit-action="choose"]')


def test_edit_here_on_dev_refuses_to_guess_between_two_halves_of_a_split_way(session, fake):
    fake.add_way(101, line_at(CENTER, dx=-0.0005), with_source(street("Rue A", "Astraat"), 1052304744))
    fake.add_way(102, line_at(CENTER, dx=0.0005), with_source(street("Rue A", "Astraat"), 1052304744))
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    click_edit_here(s.page, 1052304744, [list(c) for c in line_at(CENTER, length=0.002)])
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('correspond à 2 ways sur le serveur dev')")
    assert selected_way(s.page) is None


def osm_xml(ways, negative=False):
    nodes, out_ways, nid = [], [], 1
    for way_id, coords, tags in ways:
        refs = []
        for lon, lat in coords:
            node_id = -nid if negative else nid
            nodes.append(f'<node id="{node_id}" version="1" timestamp="2026-05-20T04:45:43Z" lat="{lat}" lon="{lon}"/>')
            refs.append(node_id)
            nid += 1
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        nd_xml = "".join(f'<nd ref="{r}"/>' for r in refs)
        out_ways.append(f'<way id="{way_id}" version="1" timestamp="2026-05-21T10:00:00Z">{nd_xml}{tag_xml}</way>')
    return f'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6">{"".join(nodes)}{"".join(out_ways)}</osm>'


def upload_osm(page, text, name="map.osm"):
    page.set_input_files("#edit-data-file", files=[{"name": name, "mimeType": "application/xml", "buffer": text.encode()}])


def sidewalk_source(page):
    return map_eval(page, "const l = m.getStyle().layers.find(l => l.id === 'sidewalk-roads'); return [l.source, l['source-layer'] || null];")


def dev_features(page):
    return map_eval(page, "return m.getSource('dev-sidewalk').serialize().data.features.map(f => f.properties);")


def test_a_dev_export_replaces_the_sidewalk_layer_and_edit_here_uses_its_ids(session, fake):
    three_streets(fake)
    s = session()
    assert sidewalk_source(s.page) == ["pedestrian", "sidewalk_roads"]
    upload_osm(s.page, osm_xml([
        (101, line_at(CENTER), street("Rue Test", "Teststraat")),
        (102, line_at(CENTER, dy=-0.0004), {**street("Rue B", "Bstraat"), "sidewalk:both": "separate"}),
        (103, line_at(CENTER, dy=-0.0004, dx=0.002), {"highway": "service"}),
    ]))
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('2 rues chargées depuis map.osm')")
    assert sidewalk_source(s.page) == ["dev-sidewalk", None]
    assert s.page.evaluate("BPNEdit.devData().count") == 2
    statuses = {p["osm_id"]: p["sw"] for p in dev_features(s.page)}
    assert statuses == {101: "unknown", 102: "separate"}
    s.page.click("#edit-exit")
    fake_calls = fake.count("map")
    click_edit_here(s.page, 101, [[x + 0.001, y + 0.001] for x, y in line_at(CENTER)])
    wait_selected(s.page, 101)
    assert fake.count("map") >= fake_calls


def test_the_dev_export_survives_a_reload_and_a_basemap_change_until_reset(session, fake):
    three_streets(fake)
    s = session()
    upload_osm(s.page, osm_xml([(101, line_at(CENTER), street("Rue Test", "Teststraat"))]))
    wait(s.page, "() => !!(window.BPNEdit && BPNEdit.devData())")
    s.page.reload()
    wait(s.page, "() => !!(window.BPNEdit && BPNEdit.devData())")
    wait(s.page, "async () => { const { store } = await import('/map/store.js'); return store.mapReady && store.map.getStyle().layers.find(l => l.id === 'sidewalk-roads').source === 'dev-sidewalk'; }")
    s.page.click("#basemap-toggle")
    s.page.click('.basemap-option[data-id="urbis-ortho"]')
    wait(s.page, "() => localStorage.getItem('bpn-basemap') === 'urbis-ortho'")
    time.sleep(0.6)
    assert sidewalk_source(s.page) == ["dev-sidewalk", None]
    enter_edit(s.page)
    s.page.click('[data-edit-action="data-reset"]')
    wait(s.page, "() => BPNEdit.devData() === null")
    assert sidewalk_source(s.page) == ["pedestrian", "sidewalk_roads"]
    s.page.reload()
    wait(s.page, "async () => window.BPNEdit && (await import('/map/store.js')).store.mapReady")
    time.sleep(0.5)
    assert s.page.evaluate("BPNEdit.devData()") is None
    assert sidewalk_source(s.page) == ["pedestrian", "sidewalk_roads"]


def test_the_load_button_opens_the_file_picker_and_a_cancelled_pick_changes_nothing(session, fake):
    three_streets(fake)
    s = session()
    with s.page.expect_file_chooser() as chooser:
        s.page.click('[data-edit-action="data-load"]')
    assert chooser.value.element.get_attribute("id") == "edit-data-file"
    before = s.page.inner_text("#edit-data")
    s.page.evaluate("document.getElementById('edit-data-file').dispatchEvent(new Event('change'))")
    time.sleep(0.3)
    assert s.page.inner_text("#edit-data") == before
    assert s.page.evaluate("BPNEdit.devData()") is None
    chooser.value.set_files(files=[{"name": "map.osm", "mimeType": "application/xml", "buffer": osm_xml([(101, line_at(CENTER), street("Rue Test", "Teststraat"))]).encode()}])
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('1 rue chargée depuis map.osm')")


def test_back_to_the_prod_tiles_restores_the_sidewalk_layer_without_a_reload(session, fake):
    three_streets(fake)
    s = session()
    upload_osm(s.page, osm_xml([(101, line_at(CENTER), street("Rue Test", "Teststraat"))]))
    wait(s.page, "() => !!BPNEdit.devData()")
    s.page.click('[data-edit-action="data-reset"]')
    wait(s.page, "() => BPNEdit.devData() === null")
    assert sidewalk_source(s.page) == ["pedestrian", "sidewalk_roads"]
    assert map_eval(s.page, "return !!m.getSource('dev-sidewalk');") is False
    assert "Charger un export .osm" in s.page.inner_text("#edit-data")


def test_a_second_export_replaces_the_first_one(session, fake):
    three_streets(fake)
    s = session()
    upload_osm(s.page, osm_xml([(101, line_at(CENTER), street("Rue Test", "Teststraat"))]), name="first.osm")
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('1 rue chargée depuis first.osm')")
    upload_osm(s.page, osm_xml([
        (201, line_at(CENTER, dy=-0.0004), street("Rue B", "Bstraat")),
        (202, line_at(CENTER, dy=-0.0009), {**street("Rue C", "Cstraat"), "sidewalk:both": "no"}),
    ]), name="second.osm")
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('2 rues chargées depuis second.osm')")
    assert sidewalk_source(s.page) == ["dev-sidewalk", None]
    assert {p["osm_id"]: p["sw"] for p in dev_features(s.page)} == {201: "unknown", 202: "documented"}
    assert map_eval(s.page, "return m.getStyle().layers.filter(l => l.id === 'sidewalk-roads').length;") == 1


def test_a_file_over_fifty_megabytes_is_refused_without_being_read(session, fake):
    three_streets(fake)
    s = session()
    s.page.evaluate("""() => {
      const input = document.getElementById('edit-data-file');
      const file = new File([new Uint8Array(51 * 1048576)], 'huge.osm', { type: 'application/xml' });
      file.text = () => { window.__readHuge = true; return Promise.resolve(''); };
      Object.defineProperty(input, 'files', { value: { 0: file, length: 1 }, configurable: true });
      input.dispatchEvent(new Event('change'));
    }""")
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('Fichier trop gros : 51 Mo, 50 au plus')")
    assert s.page.evaluate("window.__readHuge === undefined")
    assert s.page.evaluate("BPNEdit.devData()") is None
    assert sidewalk_source(s.page) == ["pedestrian", "sidewalk_roads"]


def test_a_file_that_cannot_be_read_shows_the_generic_message(session, fake):
    three_streets(fake)
    s = session()
    s.page.evaluate("""() => {
      const input = document.getElementById('edit-data-file');
      const file = new File(['<osm/>'], 'broken.osm', { type: 'application/xml' });
      file.text = () => Promise.reject(new Error('disk gone'));
      Object.defineProperty(input, 'files', { value: { 0: file, length: 1 }, configurable: true });
      input.dispatchEvent(new Event('change'));
    }""")
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes(\"Le fichier n'a pas pu être lu\")")
    assert s.page.evaluate("BPNEdit.devData()") is None


def test_a_josm_file_with_unsent_objects_or_a_non_osm_file_is_refused(session, fake):
    three_streets(fake)
    s = session()
    upload_osm(s.page, osm_xml([(101, line_at(CENTER), street("Rue Test", "Teststraat"))], negative=True))
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('pas encore envoyés')")
    upload_osm(s.page, "<html><body>nope</body></html>", name="page.html")
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes(\"n'est pas un export OSM\")")
    upload_osm(s.page, osm_xml([(101, line_at(CENTER), {"highway": "footway"})]))
    wait(s.page, "() => document.getElementById('edit-data').textContent.includes('Aucune rue utilisable')")
    assert s.page.evaluate("BPNEdit.devData()") is None
    assert sidewalk_source(s.page) == ["pedestrian", "sidewalk_roads"]


def test_with_editing_disabled_no_api_call_leaves_the_page_even_with_a_token(session, fake):
    three_streets(fake)
    s = session(editing=False, settings={"editEnabled": "false"})
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    s.page.evaluate("sessionStorage.setItem('bpn.editing.dev', '1')")
    s.page.reload()
    wait(s.page, "async () => window.BPNEdit && (await import('/map/store.js')).store.mapReady")
    assert not s.page.is_visible("#edit-enter")
    assert s.page.evaluate("BPNEdit.isActive()") is False
    assert s.page.evaluate("sessionStorage.getItem('bpn.editing.dev')") is None
    s.page.evaluate("BPNEdit.enter()")
    assert s.page.evaluate("BPNEdit.isActive()") is False
    assert s.page.evaluate("BPNEdit.canEdit({ sw: 'unknown', highway: 'residential' })") is False
    html = s.page.evaluate("""() => BPNMap.clickPopups.find(c => c.ids.includes('sidewalk-roads'))
      .format({ osm_id: 101, sw: 'unknown', highway: 'residential', name: 'x', length_m: 60 })""")
    assert "data-bpn-edit-way" not in html
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0] + 0.0003}, {CENTER[1]}], zoom: 17.5 }}); return true;")
    blocked = s.page.evaluate("""() => fetch('https://master.apis.dev.openstreetmap.org/api/0.6/map.json?bbox=1,2,3,4')
      .then(() => 'sent', e => e.name)""")
    assert blocked == "ApiBlockedError"
    time.sleep(0.8)
    assert fake.calls == []
    assert "désactivée" in s.page.inner_text("#edit-auth")


def layer_visibility(page, ids):
    return map_eval(page, f"return Object.fromEntries({json.dumps(ids)}.map(id => [id, m.getLayoutProperty(id, 'visibility') || 'visible']));")


def legend_shown(page):
    return page.evaluate("""() => [...document.querySelectorAll('#legend-content .legend-item')]
      .filter(el => !el.hidden).map(el => [el.querySelector('.legend-label').textContent, el.getAttribute('aria-disabled') === 'true'])""")


WATCHED = ["flow-ped", "flow-road", "sidewalk-gaps", "missing-crossings", "sidewalk-roads",
           "highway-pedestrian", "highway-footway", "highway-path", "highway-cycleway", "highway-steps"]


def test_edit_mode_shows_only_the_orthophoto_and_the_editing_layers_then_restores_the_view(session, fake):
    three_streets(fake)
    s = session(editing=False)
    wait(s.page, "async () => (await import('/map/store.js')).store.mapReady")
    map_eval(s.page, "m.setLayoutProperty('flow-ped', 'visibility', 'visible'); m.setLayoutProperty('highway-cycleway', 'visibility', 'visible'); return true;")
    before = layer_visibility(s.page, WATCHED)
    assert s.page.evaluate("BPNMap.currentBasemap()") == "liberty"
    enter_edit(s.page)
    wait(s.page, "() => BPNMap.currentBasemap() === 'urbis-ortho'")
    assert s.page.evaluate("[...document.querySelectorAll('#basemap-menu .basemap-option')].map(b => b.dataset.id)") == ["urbis-ortho"]
    seen = layer_visibility(s.page, WATCHED)
    assert {k for k, v in seen.items() if v == "visible"} <= {"sidewalk-roads", "highway-pedestrian", "highway-footway", "highway-path"}
    assert all(seen[k] == "visible" for k in ["highway-pedestrian", "highway-footway", "highway-path"])
    assert seen["flow-ped"] == "none" and seen["highway-cycleway"] == "none"
    shown = legend_shown(s.page)
    assert shown == [["Tags sidewalk", False], ["Zone piétonne", True], ["Trottoir / allée", True], ["Sentier", True]]
    s.page.evaluate("[...document.querySelectorAll('#legend-content .legend-item')].find(el => el.textContent.includes('Sentier')).click()")
    assert layer_visibility(s.page, ["highway-path"]) == {"highway-path": "visible"}
    s.page.click("#edit-exit")
    wait(s.page, "() => BPNMap.currentBasemap() === 'liberty'")
    assert layer_visibility(s.page, WATCHED) == before
    assert len(s.page.evaluate("[...document.querySelectorAll('#basemap-menu .basemap-option')].map(b => b.dataset.id)")) > 1
    assert len(legend_shown(s.page)) > 10


def test_a_street_cannot_be_judged_on_a_drawn_basemap(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    s.page.evaluate("BPNMap.setBasemap('liberty')")
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes(\"Passez sur l'orthophoto UrbIS\")")
    assert locked(s.page)
    s.page.keyboard.press("s")
    time.sleep(0.3)
    assert queue_ids(s.page) == []
    s.page.click('[data-edit-action="basemap"]')
    wait(s.page, "() => BPNMap.currentBasemap() === 'urbis-ortho' && !document.querySelector('[data-edit-action=choose][disabled]')")
    s.page.keyboard.press("s")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")


def test_the_choice_opens_only_after_looking_at_the_street_a_few_seconds(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(settings={"minLookMs": "1500", "lookMsPerMeter": "1000", "lookMode": '"block"'})
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101, expect_form=False)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('Prenez le temps de regarder la rue')")
    assert locked(s.page)
    s.page.keyboard.press("s")
    time.sleep(0.2)
    assert queue_ids(s.page) == []
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]')")
    assert queue_ids(s.page) == []
    s.page.keyboard.press("s")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")


def queue_current(page):
    before = len(queue_ids(page))
    wait(page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]')")
    page.keyboard.press("s")
    wait(page, f"() => JSON.parse(localStorage.getItem('bpn.queue.dev') || '[]').length === {before + 1}")


def test_editing_too_fast_warns_then_pauses_when_it_happens_again(session, fake):
    for i in range(8):
        fake.add_way(101 + i, line_at(CENTER, dy=0.0004 - 0.00012 * i), street(f"Rue {i}", f"Straat {i}"))
    s = session(settings={"paceMaxMeters": "120", "paceBlockMeters": "180", "paceWindowMs": "2500", "paceCooldownMs": "3000"})
    wait_candidates(s.page, 8)
    s.page.keyboard.press("ArrowRight")
    for _ in range(2):
        queue_current(s.page)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('Vous éditez trop vite')")
    assert not locked(s.page)
    time.sleep(2.8)
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.getElementById('edit-detail').textContent.includes('Vous éditez trop vite')")
    for _ in range(3):
        queue_current(s.page)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('Vous éditez encore trop vite')")
    assert locked(s.page)
    queued = queue_ids(s.page)
    assert len(queued) == 5
    s.page.keyboard.press("s")
    time.sleep(0.3)
    assert queue_ids(s.page) == queued
    queue_current(s.page)


def test_map_loads_pause_after_the_per_minute_ceiling(session, fake):
    three_streets(fake)
    s = session(settings={"mapCallsPerMinute": "2"})
    wait_candidates(s.page, 3)
    for step in (1, 2, 3):
        move_map(s.page, 17.6, CENTER[1], CENTER[0] + 0.02 * step)
        time.sleep(0.6)
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('chargement en pause')")
    assert fake.count("map") == 2


def test_in_warn_mode_the_look_hint_waits_for_several_hasty_choices(session, fake):
    for i in range(6):
        fake.add_way(101 + i, line_at(CENTER, dy=0.0003 - 0.00012 * i), street(f"Rue {i}", f"Straat {i}"))
    s = session(settings={"minLookMs": "3000", "lookMsPerMeter": "1000", "lookQuickTolerance": "2"})
    wait_candidates(s.page, 6)
    s.page.keyboard.press("ArrowRight")
    for _ in range(2):
        wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]')")
        assert "Prenez le temps" not in s.page.inner_text("#edit-detail")
        assert not locked(s.page)
        queue_current(s.page)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('Prenez le temps de regarder la rue')")
    assert not locked(s.page)
    assert json.loads(s.page.evaluate("localStorage.getItem('bpn.look.dev')")) == [True, True]
    queue_current(s.page)

def test_a_short_segment_only_asks_for_a_short_look(session, fake):
    short = [(CENTER[0], CENTER[1]), (CENTER[0] + 0.0003, CENTER[1])]
    fake.add_way(101, short, street("Rue Courte", "Korte Straat"))
    s = session(settings={"minLookMs": "3000", "lookMsPerMeter": "30", "lookMode": '"block"'})
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0] + 0.00015, CENTER[1], 101, expect_form=False)
    wait(s.page, "() => document.getElementById('edit-detail').textContent.includes('encore 1 seconde')")
    start = time.time()
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]')")
    assert time.time() - start < 1.5


def test_api_calls_carry_the_site_origin_as_referer_and_nothing_more(session, fake, server):
    three_streets(fake)
    s = session()
    wait_candidates(s.page, 3)
    origin = server.split("/test-api")[0].rstrip("/") + "/"
    origin = "/".join(origin.split("/")[:3]) + "/"
    assert fake.referers
    assert set(fake.referers) == {origin}
    assert s.page.evaluate("document.querySelector('meta[name=referrer]').content") == "strict-origin-when-cross-origin"


def boxes(page, ids):
    return page.evaluate("""ids => Object.fromEntries(ids.map(id => {
      const r = document.getElementById(id).getBoundingClientRect();
      return [id, { left: r.left, top: r.top, right: r.right, bottom: r.bottom, shown: r.width > 0 && r.height > 0 }];
    }))""", ids)


def overlap(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


@pytest.mark.parametrize("width, height", [(390, 844), (360, 740)])
def test_on_mobile_the_layers_stay_reachable_folded_in_edit_mode(session, fake, width, height):
    three_streets(fake)
    s = session(editing=False)
    s.page.set_viewport_size({"width": width, "height": height})
    s.page.evaluate("BPNEdit.enter()")
    wait_candidates(s.page, 3)
    assert not s.page.evaluate("document.getElementById('legend').classList.contains('open')")
    b = boxes(s.page, ["edit-bar", "legend", "basemap-control", "edit-dock"])
    assert all(box["shown"] for box in b.values())
    names = list(b)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            assert not overlap(b[first], b[second]), (first, second, b)
    assert not s.page.is_visible("#zoom-badge")
    s.page.click("#legend-toggle")
    assert s.page.evaluate("document.getElementById('legend').classList.contains('open')")
    b = boxes(s.page, ["edit-bar", "legend", "edit-dock"])
    assert not overlap(b["legend"], b["edit-bar"]) and not overlap(b["legend"], b["edit-dock"]), b
    assert layer_visibility(s.page, ["sidewalk-roads"]) == {"sidewalk-roads": "none"}
    s.page.locator("#legend-content .legend-item", has_text="Tags sidewalk").click()
    assert layer_visibility(s.page, ["sidewalk-roads"]) == {"sidewalk-roads": "visible"}
    s.page.click("#legend-toggle")
    assert not s.page.evaluate("document.getElementById('legend').classList.contains('open')")


def log_in(page):
    with page.expect_popup() as popup_info:
        page.click('[data-edit-action="login"]')
    popup = popup_info.value
    return popup


def stored_token(page):
    raw = page.evaluate("localStorage.getItem('__osmAuth')")
    return json.loads(raw)["accessToken"] if raw else None


def test_the_full_oauth_login_uses_pkce_and_the_new_token(session, fake):
    s = session(logged_in=False)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Se connecter à OSM')")
    popup = log_in(s.page)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connecté en tant que Testeur')")
    end = time.time() + 10
    while not popup.is_closed() and time.time() < end:
        time.sleep(0.1)
    assert popup.is_closed()
    assert stored_token(s.page) == "fresh-token"
    assert s.page.evaluate("localStorage.getItem('bpn.authEnv')") == "dev"
    assert s.page.evaluate("localStorage.getItem('bpn.authPending')") is None
    grant = fake.authorizations[0]
    assert grant["client_id"] == dev_client_id()
    assert grant["scope"] == "read_prefs write_api"
    assert grant["response_type"] == "code"
    assert grant["code_challenge_method"] == "S256"
    assert grant["redirect_uri"].endswith("/test-api/land.html")
    assert len(grant["state"]) >= 16
    assert [e["checks"] for e in fake.exchanges] == [dict.fromkeys(["known_code", "grant_type", "client_id", "redirect_uri", "pkce"], True)]
    assert fake.authorization_headers[-1] == "Bearer fresh-token"


def test_a_denied_authorisation_stores_nothing_and_can_be_retried(session, fake):
    fake.oauth_answer = "deny"
    s = session(logged_in=False)
    popup = log_in(s.page)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connexion échouée ou annulée')")
    assert stored_token(s.page) is None
    assert fake.exchanges == []
    assert s.page.evaluate("localStorage.getItem('bpn.authPending')") is None
    if not popup.is_closed():
        popup.close()
    fake.oauth_answer = "approve"
    log_in(s.page)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connecté en tant que Testeur')")
    assert stored_token(s.page) == "fresh-token"


def test_a_forged_state_is_refused_before_any_token_exchange(session, fake):
    fake.oauth_answer = "wrong_state"
    s = session(logged_in=False)
    popup = log_in(s.page)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connexion échouée ou annulée')")
    assert fake.exchanges == []
    assert stored_token(s.page) is None
    if not popup.is_closed():
        popup.close()


def test_a_refused_code_exchange_leaves_the_user_logged_out(session, fake):
    fake.oauth_answer = "bad_grant"
    s = session(logged_in=False)
    popup = log_in(s.page)
    wait(s.page, "() => document.getElementById('edit-auth').innerText.includes('Connexion échouée ou annulée')")
    assert len(fake.exchanges) == 1
    assert stored_token(s.page) is None
    assert s.page.evaluate("localStorage.getItem('bpn.authEnv')") is None
    if not popup.is_closed():
        popup.close()
