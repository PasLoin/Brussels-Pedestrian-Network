import json
import math

import pytest
from pyproj import Transformer

from build_graph import build_graph
from clean_osm import clean_osm
from detect_missing_crossings import detect_missing_crossings
from export import compute_graph_stats, compute_network_stats, save_stats, undirected_edge_groups
from export_sidewalk_roads import export_sidewalk_roads
from front_contract import APP_STATS_PATHS, ROOT, STATS_HTML_PATHS, get_path, page_text
from sidewalk_gap import detect_sidewalk_gaps

_TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)
_X0, _Y0 = 150000.0, 170000.0


def _ll(x, y):
    return list(_TO_WGS.transform(_X0 + x, _Y0 + y))


def _line(coords, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": [_ll(*c) for c in coords]}}


def _point(x, y, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": _ll(x, y)}}


def _write(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return str(path)


_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.8500" lon="4.3500"/>
  <node id="2" lat="50.8500" lon="4.3510"/>
  <node id="3" lat="50.8500" lon="4.3520"/>
  <node id="4" lat="50.8500" lon="4.3530"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
  <way id="11"><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way>
  <way id="12"><nd ref="3"/><nd ref="4"/><tag k="highway" v="cycleway"/></way>
</osm>
"""

_EMPTY_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.8500" lon="4.3500"/>
  <node id="2" lat="50.8500" lon="4.3510"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
</osm>
"""


def _build_stats(tmp_path, monkeypatch, populated: bool) -> dict:
    monkeypatch.chdir(tmp_path)
    road = {"highway": "residential", "name": "Rue Test", "sidewalk:both": "separate"}
    roads = [_line([(0, 0), (100, 0)], road)] if populated else [
        _line([(0, 0), (100, 0)], {"highway": "service"})
    ]
    footways = [
        _line([(0, 6), (100, 6)], {"highway": "footway", "footway": "sidewalk", "@id": 20}),
        _line([(0, -6), (100, -6)], {"highway": "footway", "footway": "sidewalk", "@id": 21}),
    ] if populated else []
    nodes = [_point(50, 0, {"highway": "crossing", "@id": 1})] if populated else []
    _write(tmp_path / "roads.geojson", roads)
    _write(tmp_path / "footways.geojson", footways)
    _write(tmp_path / "highways.geojson", nodes)

    (tmp_path / "raw.osm").write_text(_OSM if populated else _EMPTY_OSM)
    clean_osm("raw.osm", "clean.osm")
    gb = build_graph("clean.osm")
    groups = undirected_edge_groups(gb.edges.tuples, gb.edges.geoms, gb.edges.lengths)

    save_stats(
        12 if populated else 0, 9000.0 if populated else 0.0,
        40 if populated else 0, 80 if populated else 0, 3, 2, 1.5,
        graph_stats=compute_graph_stats(gb, groups),
        network_stats=compute_network_stats(
            groups, gb.edges.highways, gb.edges.lengths, gb.edges.cycleway_nf, gb.edges.foot_tags,
        ),
        sidewalk_gap_stats=detect_sidewalk_gaps("roads.geojson", "footways.geojson"),
        sidewalk_road_stats=export_sidewalk_roads("roads.geojson"),
        missing_crossing_stats=detect_missing_crossings(
            highways_geojson_path="highways.geojson",
            footways_geojson_path="footways.geojson",
            roads_geojson_path="roads.geojson",
            service_roads_geojson_path="absent.geojson",
            cycleways_geojson_path="absent.geojson",
            tracks_geojson_path="absent.geojson",
        ),
    )
    return json.loads((tmp_path / "stats.json").read_text())


@pytest.fixture(params=[True, False], ids=["populated", "empty"])
def stats(request, tmp_path, monkeypatch):
    return _build_stats(tmp_path, monkeypatch, request.param)


def test_stats_json_has_every_path_read_by_the_front(stats):
    for path in sorted(STATS_HTML_PATHS | APP_STATS_PATHS):
        value = get_path(stats, path)
        assert value is not None, path
        if not isinstance(value, dict):
            assert isinstance(value, (int, float)), path
            assert math.isfinite(value), path


def test_stats_json_has_no_root_level_duplicates(stats):
    assert "routed_trips" not in stats
    assert "avg_distance_m" not in stats


_CHART_STUB = """
window.__charts = [];
const sink = () => new Proxy(function () {}, {
  get: (t, k) => (k in t ? t[k] : (t[k] = sink())),
  set: (t, k, v) => { t[k] = v; return true; },
});
window.Chart = class {
  constructor(ctx, config) { window.__charts.push(JSON.parse(JSON.stringify(config.data || {}))); }
  destroy() {}
  update() {}
};
window.Chart.defaults = sink();
window.Chart.register = () => {};
"""

_BAD_TEXT = ("NaN", "undefined", "Infinity", "[object Object]")


def _render(page_html: str, stats_json: dict):
    sync_api = pytest.importorskip("playwright.sync_api")
    errors = []
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(bypass_csp=True).new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/chart.umd.js", lambda r: r.fulfill(body=_CHART_STUB, content_type="text/javascript"))
        page.route("**/stats.json", lambda r: r.fulfill(body=json.dumps(stats_json), content_type="application/json"))
        page.route("**/state.txt", lambda r: r.fulfill(body="build_timestamp=2026-11-02T00:00:00Z\n"))
        page.route("**/page.html", lambda r: r.fulfill(body=page_html, content_type="text/html"))
        page.route("**/i18n.js", lambda r: r.fulfill(path=ROOT / "i18n.js", content_type="text/javascript"))
        page.route("**/stats.js", lambda r: r.fulfill(path=ROOT / "stats.js", content_type="text/javascript"))
        page.route("**/*.svg", lambda r: r.fulfill(body="", content_type="image/svg+xml"))
        page.goto("http://contract.test/page.html")
        page.wait_for_function(
            "window.__charts.length > 0 || document.body.innerText.includes('Erreur')",
            timeout=10000,
        )
        text = page.inner_text("body")
        charts = page.evaluate("window.__charts")
        browser.close()
    return text, charts, errors


def _numbers(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _numbers(v)
    elif isinstance(node, list):
        for v in node:
            yield from _numbers(v)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield node


def test_stats_page_renders_without_broken_values(stats):
    text, charts, errors = _render(page_text("stats.html"), stats)
    assert errors == []
    assert "Erreur" not in text
    for bad in _BAD_TEXT:
        assert bad not in text, bad
    assert charts
    for chart in charts:
        for dataset in chart.get("datasets", []):
            assert None not in dataset.get("data", []), chart
            assert all(math.isfinite(v) for v in _numbers(dataset.get("data", [])))
