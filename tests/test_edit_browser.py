import functools
import http.server
import json
import math
import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import build_site
from edit_fake_osm import DEV_HOST, FakeOsm

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

if sync_playwright is None:
    if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
        raise RuntimeError("REQUIRE_BROWSER_TESTS=1 but playwright is not installed")
    pytest.skip("playwright not installed", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "node_modules"
LIBS = {
    "maplibre-gl.js": MODULES / "maplibre-gl" / "dist" / "maplibre-gl.js",
    "maplibre-gl.css": MODULES / "maplibre-gl" / "dist" / "maplibre-gl.css",
    "pmtiles.js": MODULES / "pmtiles" / "dist" / "pmtiles.js",
}
if not all(path.is_file() for path in LIBS.values()):
    if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
        raise RuntimeError("maplibre-gl and pmtiles must be installed with npm ci")
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


class Session:
    def __init__(self, browser, server, fake, logged_in=True, queue=None, auth_env="dev", center=CENTER, zoom=17.5, editing=True):
        self.fake = fake
        self.problems = []
        self.context = browser.new_context(viewport={"width": 1134, "height": 763}, locale="fr-BE")
        self.context.route("**/*", self._route)
        seed = {}
        if logged_in:
            seed["__osmAuth"] = json.dumps({"accessToken": "token", "issuedAt": "2026-11-09", "scopes": ["read_prefs", "write_api"]})
            seed["bpn.authEnv"] = auth_env
        if queue is not None:
            seed["bpn.queue.dev"] = json.dumps(queue)
        self.context.add_init_script(
            "document.addEventListener('securitypolicyviolation', e => console.error('CSP ' + e.violatedDirective + ' ' + e.blockedURI));"
            f"if (!localStorage.getItem('test.seeded')) {{ for (const [k, v] of Object.entries({json.dumps(seed)})) localStorage.setItem(k, v);"
            " localStorage.setItem('test.seeded', '1'); }"
        )
        self.url = f"{server}test-api/devtest.html#{zoom}/{center[1]}/{center[0]}"
        self.page = self.open(editing)

    def _route(self, route):
        url = route.request.url
        if "unpkg.com" in url:
            name = url.rsplit("/", 1)[-1]
            if name in LIBS:
                return route.fulfill(path=str(LIBS[name]), content_type="text/css" if name.endswith(".css") else "application/javascript")
            return route.abort()
        if "tiles.openfreemap.org/styles/liberty" in url:
            return route.fulfill(body=BLANK_STYLE, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"})
        if DEV_HOST in url:
            return self.fake.handle(route)
        if url.startswith("http://127.0.0.1"):
            return route.continue_()
        return route.abort()

    def open(self, editing=True):
        page = self.context.new_page()
        page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.problems.append(m.text) if m.type == "error" and m.text.startswith("CSP") else None)
        page.goto(self.url)
        wait(page, "() => window.BPNEdit !== undefined && window.BPNMap !== undefined")
        if editing:
            enter_edit(page)
        return page

    def close(self):
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
    s.page.evaluate(f"window.location.hash = '#17.6/{CENTER[1]}/{CENTER[0]}'")
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
    fake.inject("create", delay=1.5)
    s.page.click('[data-edit-action="send"]')
    time.sleep(0.3)
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
    fake.inject("map", status=509, body="You have downloaded too much data")
    s.page.evaluate(f"window.location.hash = '#17.6/{CENTER[1]}/{CENTER[0]}'")
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('trop de données téléchargées')")
    assert s.page.evaluate("async () => { const { store } = await import('/map/store.js'); return store.map.querySourceFeatures('edit-candidates').length; }") == 0


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
    s.page.evaluate(f"window.location.hash = '#17/{CENTER[1] + 0.0001}/{CENTER[0]}'")
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
    send(s.page)
    assert fake.creates == []
    assert "Se connecter à OSM" in s.page.inner_text("#edit-auth")
    assert queue_ids(s.page) == [101]
    other.close()


def test_s5_a_token_from_another_environment_is_purged_on_load(session, fake):
    s = session(auth_env="prod")
    assert s.page.evaluate("localStorage.getItem('__osmAuth')") is None
    assert "Connecté" not in s.page.inner_text("#edit-auth")


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
    assert "imagery_used" not in tags
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


def whole_way_inside(page, coords):
    return map_eval(page, f"""
      const dock = document.getElementById('edit-dock');
      const r = dock.getBoundingClientRect();
      const c = m.getCanvas();
      const right = dock.classList.contains('open') ? r.left : c.clientWidth;
      return {json.dumps(coords)}.every(p => {{ const q = m.project(p); return q.x >= 0 && q.y >= 0 && q.x <= right && q.y <= c.clientHeight; }});""")


def test_a_long_street_is_shown_whole_before_it_can_be_edited(session, fake):
    long_line = line_at(CENTER, length=0.012)
    fake.add_way(101, long_line, street("Longue Rue", "Lange Straat"))
    s = session()
    wait_candidates(s.page, 1)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "() => !document.querySelector('[data-edit-action=choose][disabled]')")
    assert whole_way_inside(s.page, long_line)
    assert "découp" not in s.page.inner_text("#edit-detail")
    map_eval(s.page, f"m.jumpTo({{ center: [{CENTER[0] + 0.006}, {CENTER[1]}], zoom: 17.5 }}); return true;")
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose][disabled]')")
    assert "pas entièrement visible" in s.page.inner_text("#edit-detail")
    s.page.keyboard.press("s")
    time.sleep(0.3)
    assert queue_ids(s.page) == []
    s.page.click('[data-edit-action="fit"]')
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]')")
    assert whole_way_inside(s.page, long_line)
    s.page.keyboard.press("s")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('101')")
    assert queue_ids(s.page) == [101]


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


def test_after_a_long_street_the_next_one_is_offered_without_zooming_back(session, fake):
    long_line = line_at(CENTER, length=0.012)
    fake.add_way(101, long_line, street("Longue Rue", "Lange Straat"))
    fake.add_way(102, line_at(CENTER, dy=-0.0004), street("Rue Courte", "Korte Straat"))
    s = session()
    wait_candidates(s.page, 2)
    click_way(s.page, CENTER[0], CENTER[1] + 0.00001, 101)
    wait(s.page, "() => !!document.querySelector('[data-edit-action=choose]') && !document.querySelector('[data-edit-action=choose][disabled]')")
    zoom = map_zoom(s.page)
    assert zoom < 17
    s.page.keyboard.press("s")
    wait_selected(s.page, 102)
    time.sleep(0.6)
    assert abs(map_zoom(s.page) - zoom) < 0.01
    assert not locked(s.page)
    s.page.keyboard.press("y")
    wait(s.page, "() => (localStorage.getItem('bpn.queue.dev') || '').includes('102')")
    assert queue_ids(s.page) == [101, 102]
    assert max(requested_areas(fake)) <= 0.001


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
    fake.inject("map", delay=1.5, times=3)
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
    s.page.evaluate("""async (markup) => {
      const { store } = await import('/map/store.js');
      new maplibregl.Popup().setLngLat(store.map.getCenter()).setHTML(markup).addTo(store.map);
    }""", html)
    s.page.click('[data-bpn-edit-way="102"]')
    wait_selected(s.page, 102)
    assert edit_ui(s.page)["active"] is True
