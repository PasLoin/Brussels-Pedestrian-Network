import functools
import http.server
import json
import math
import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

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
    def __init__(self, browser, server, fake, logged_in=True, queue=None, auth_env="dev", center=CENTER, zoom=17.5):
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
        self.page = self.open()

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

    def open(self):
        page = self.context.new_page()
        page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.problems.append(m.text) if m.type == "error" and m.text.startswith("CSP") else None)
        page.goto(self.url)
        wait(page, "() => !!document.getElementById('edit-status') && document.getElementById('edit-status').textContent.length > 0")
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
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('Impossible de charger')")
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
    assert "Envoi impossible" in queue_text(s.page)
    assert queue_ids(s.page) == [101]


def test_n3_cut_between_changeset_creation_and_upload_closes_the_empty_changeset(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", abort=True)
    send(s.page)
    assert "Envoi impossible" in queue_text(s.page)
    assert queue_ids(s.page) == [101]
    assert fake.uploads == []
    assert fake.open_changesets() == []


def test_n4_a_lost_response_after_a_successful_upload_never_writes_twice(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", abort=True, after=True)
    send(s.page)
    assert "Envoi impossible" in queue_text(s.page)
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
    assert "Envoi impossible" in queue_text(s.page)
    assert fake.creates == []
    assert queue_ids(s.page) == [101]


def test_n6_a_server_error_is_not_retried(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("upload", status=500, body="Internal Server Error")
    send(s.page)
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
    assert "Envoi impossible" in queue_text(s.page)
    assert [u["ways"] for u in fake.uploads] == [[101]]
    assert queue_ids(s.page) == [102]


def test_l2_download_limit_empties_the_candidate_layer(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session()
    wait_candidates(s.page, 1)
    fake.inject("map", status=509, body="You have downloaded too much data")
    s.page.evaluate(f"window.location.hash = '#17.6/{CENTER[1]}/{CENTER[0]}'")
    wait(s.page, "() => document.getElementById('edit-status').textContent.includes('Impossible de charger')")


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
    assert "Envoi impossible" in queue_text(s.page)
    assert queue_ids(s.page) == [101]


def test_s2_a_blocked_account_is_not_retried(session, fake):
    fake.add_way(101, line_at(CENTER), street("Rue Test", "Teststraat"))
    s = session(queue=[intent_for(fake, 101)])
    prepare(s.page)
    fake.inject("create", status=403, body="Your access to the API has been blocked")
    send(s.page)
    assert fake.count("create") == 1
    assert queue_ids(s.page) == [101]


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
    assert tags["host"].endswith("/test-api/devtest.html")
    assert "imagery_used" not in tags
    assert "bpn:osm-api-js" not in tags
