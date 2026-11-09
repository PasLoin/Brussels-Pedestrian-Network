import functools
import http.server
import json
import os
import re
import threading

import pytest

import build_site

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

if sync_playwright is None:
    if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
        raise RuntimeError("REQUIRE_BROWSER_TESTS=1 but playwright is not installed")
    pytest.skip("playwright not installed", allow_module_level=True)

from test_pages_i18n_browser import HISTORY, STATS
from test_stats_json_contract import _CHART_STUB

MAP_STUB = """
const noop = () => undefined;
const lenient = target => new Proxy(target, { get: (t, k) => (k in t ? t[k] : noop) });
class FakeMap {
  constructor() {
    this.handlers = {};
    this.visibility = {};
    setTimeout(() => (this.handlers.load || []).forEach(fn => fn()), 0);
    return lenient(this);
  }
  on(event, ...args) { (this.handlers[event] = this.handlers[event] || []).push(args[args.length - 1]); return this; }
  once(event, ...args) { return this.on(event, ...args); }
  getLayoutProperty(id) { return this.visibility[id] || "visible"; }
  setLayoutProperty(id, key, value) { this.visibility[id] = value; }
  getZoom() { return 12; }
  getCenter() { return { lat: 50.85, lng: 4.35 }; }
  getCanvas() { return { style: {} }; }
  queryRenderedFeatures() { return []; }
  getStyle() { return { version: 8, sources: {}, layers: [] }; }
  getSource() { return null; }
  getLayer() { return {}; }
}
class Chainable { constructor() { return lenient(this); } setLngLat() { return this; } setHTML() { return this; } addTo() { return this; } }
window.maplibregl = { Map: FakeMap, AttributionControl: class {}, Popup: Chainable, Marker: Chainable, addProtocol: noop };
"""
PMTILES_STUB = "window.pmtiles = { Protocol: class { constructor() { this.tile = () => {}; } } };"
EMPTY_STYLE = json.dumps({"version": 8, "sources": {}, "layers": []})

COLLECT_TEXT = """
() => {
  const out = [];
  const pageLang = document.documentElement.lang;
  const skipped = el => {
    if (!el || el.closest("script, style, [data-i18n-fragment]")) return true;
    const scope = el.closest("[lang]");
    return Boolean(scope && scope.lang !== pageLang);
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.replace(/\\s+/g, " ").trim();
    if (text && !skipped(node.parentElement)) out.push(text);
  }
  for (const el of document.querySelectorAll("[title], [aria-label], [alt], [placeholder]")) {
    if (skipped(el)) continue;
    for (const name of ["title", "aria-label", "alt", "placeholder"]) {
      const value = (el.getAttribute(name) || "").trim();
      if (value) out.push(value);
    }
  }
  out.push(document.title);
  return out;
}
"""

RENDER_POPUPS = """
samples => samples.flatMap(([kind, id, props]) => {
  const entry = (kind === "hover" ? BPNMap.hoverPopups : BPNMap.clickPopups).find(e => e.ids.includes(id));
  const box = document.createElement("div");
  box.innerHTML = entry.format(props);
  const texts = [];
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.replace(/\\s+/g, " ").trim();
    if (text) texts.push(text);
  }
  return texts;
})
"""

POPUP_SAMPLES = [
    ["hover", "sidewalk-gaps", {"name": "Ωstreet"}],
    ["hover", "footway-crossing-candidates", {"name": "Ωstreet", "length_m": 12.34}],
    *[["hover", "sidewalk-roads", {"sw": sw, "name": "Ωstreet"}] for sw in ("separate", "yes", "documented", "partial", "unknown")],
    *[["hover", "flow-road", {"infra_type": infra, "highway": "footway", "flow_pct": 42.5}]
      for infra in ("pedestrian", "road", "cycleway_foot_yes", "cycleway_no_foot")],
    ["hover", "highway-footway", {"highway": "footway", "surface": "asphalt"}],
    ["hover", "highway-elevator", {}],
    *[["click", "missing-crossings", {"type": t, "osm_id": 1, "way_osm_id": 2, "nearest_tag_m": 2.4, "detect_radius": 3, "name": "Ωstreet"}]
      for t in ("missing_way", "missing_tag", "wrong_tag")],
    ["click", "footway-crossing-candidates", {"osm_id": 3, "length_m": 8, "name": "Ωstreet"}],
    *[["click", "tactile-paving-issues", {"osm_id": 3, "way_osm_id": 4, "partner_way_osm_id": 5, "sides_checked": s,
                                          "crossing_tp": "yes", "reason": r}]
      for s, r in ((1, "value_mismatch"), (2, "incorrect_not_mixed"))],
    *[["click", "graph-islands", {"type": t, "way_ids": "1,2", "gap_m": 1.5, "length_m": 30,
                                  "bbox_w": 4.35, "bbox_s": 50.85, "bbox_e": 4.36, "bbox_n": 50.86}]
      for t in ("unjoined", "isolated")],
    ["click", "graph-islands", {"type": "level", "level_values": "|1", "level_missing": "", "node_id": 9, "way_ids": "4"}],
    ["click", "graph-islands", {"type": "level", "level_values": "1;2", "level_missing": "1", "node_id": 9, "way_ids": "4"}],
    *[["click", "kerb-issues", {"type": t, "crossing_osm_id": 1, "kerb_osm_id": 2, "way_osm_id": 3, "partner_way_osm_id": 4}]
      for t in ("kerb_missing", "kerb_untagged")],
]

PSEUDO = re.compile(re.escape(build_site.PSEUDO_OPEN) + r"[^" + build_site.PSEUDO_OPEN + build_site.PSEUDO_CLOSE + r"]*" + re.escape(build_site.PSEUDO_CLOSE))
BRANDS = (
    "Brussels Pedestrian Network", "Brussels Pedestrian", "Simulated Flows", "OpenStreetMap",
    "OpenFreeMap Liberty", "ZinnekeTiles", "PasLoin", "Liberty", "Zinneke", "JOSM", "iD", "OSM",
)
TAG_WORDS = frozenset({
    "footway", "pedestrian", "path", "living_street", "steps", "elevator", "track", "bridleway", "platform",
    "corridor", "cycleway", "residential", "tertiary", "secondary", "primary", "unclassified", "service",
    "sidewalk", "crossing", "link", "traffic_island", "separate", "yes", "both", "no", "highway", "surface",
    "asphalt", "foot",
})
UNITS = frozenset({"km", "m", "s", "ms", "pts", "ways", "zoom"})
MONTHS = frozenset({"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec"})


def untranslated_words(text):
    rest = PSEUDO.sub(" ", text)
    for brand in BRANDS:
        rest = re.sub(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", " ", rest)
    words = []
    for token in rest.split():
        token = token.strip(".,;:!?()[]{}«»“”\"'·•✕*+−-–—/≈≤≥≠%")
        if not token or "Ω" in token or re.search(r"[=_:*]", token):
            continue
        if re.fullmatch(r"[\d.,\u202f\u00a0+\-−]+", token) or re.fullmatch(r"[wn]\d+", token):
            continue
        if token in TAG_WORDS or token in UNITS or token in MONTHS:
            continue
        if re.search(r"[A-Za-z]", token):
            words.append(token)
    return words


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    site = tmp_path_factory.mktemp("pseudo")
    build_site.build(site, pseudo=True)
    (site / "stats.json").write_text(json.dumps(STATS), encoding="utf-8")
    (site / "history.json").write_text(json.dumps(HISTORY), encoding="utf-8")
    (site / "graph.json").write_text(json.dumps({"n": [], "e": []}), encoding="utf-8")
    (site / "state.txt").write_text('{"timestamp":"2026-11-07T22:30:00Z"}\nbuild_timestamp=2026-11-08T01:15:00Z\n', encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *args: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/{build_site.PSEUDO_CONF['path']}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch()
        yield instance
        instance.close()


def _open(browser, url, ready):
    page = browser.new_page()
    errors, warnings = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    page.route("**/maplibre-gl.js", lambda r: r.fulfill(body=MAP_STUB, content_type="text/javascript"))
    page.route("**/maplibre-gl.css", lambda r: r.fulfill(body="", content_type="text/css"))
    page.route("**/pmtiles.js", lambda r: r.fulfill(body=PMTILES_STUB, content_type="text/javascript"))
    page.route("**/chart.umd.js", lambda r: r.fulfill(body=_CHART_STUB, content_type="text/javascript"))
    page.route("https://tiles.openfreemap.org/**", lambda r: r.fulfill(body=EMPTY_STYLE, content_type="application/json"))
    page.route("https://pasloin.github.io/**", lambda r: r.fulfill(body="", content_type="image/png"))
    page.goto(url)
    page.wait_for_function(ready, timeout=10000)
    page.wait_for_timeout(200)
    return page, errors, warnings


def _chart_texts(page):
    texts = []
    for data in page.evaluate("() => window.__charts || []"):
        texts += [str(label) for label in data.get("labels", [])]
        texts += [str(ds.get("label", "")) for ds in data.get("datasets", [])]
    return texts


def _assert_translated(texts, errors, warnings):
    assert errors == []
    assert [w for w in warnings if "[i18n]" in w] == []
    leftovers = {text: untranslated_words(text) for text in texts}
    assert {text: words for text, words in leftovers.items() if words} == {}


def test_untranslated_words_are_detected():
    assert untranslated_words("⟦Ļéĝéñð⟧") == []
    assert untranslated_words("⟦Šţåţš⟧ 12 km · footway=crossing w12 Ωstreet") == []
    assert untranslated_words("Brussels Pedestrian Network · 1 Aug 2026") == []
    assert untranslated_words("Legend") == ["Legend"]
    assert untranslated_words("⟦Çåļçûļ⟧ Select all") == ["Select", "all"]
    assert untranslated_words("Données") == ["Données"]


def test_map_page_has_no_hardcoded_text(server, browser):
    page, errors, warnings = _open(browser, server + "index.html", "() => document.querySelectorAll('.legend-item').length > 5")
    texts = page.evaluate(COLLECT_TEXT)
    page.dispatch_event("#nav-btn", "click")
    texts += page.evaluate(COLLECT_TEXT)
    texts += page.evaluate(RENDER_POPUPS, POPUP_SAMPLES)
    page.close()
    assert any("⟦" in t for t in texts)
    _assert_translated(texts, errors, warnings)


@pytest.mark.parametrize("name", ["stats.html", "evolution.html"])
def test_data_pages_have_no_hardcoded_text(server, browser, name):
    page, errors, warnings = _open(browser, server + name, "() => (window.__charts || []).length > 0")
    texts = page.evaluate(COLLECT_TEXT) + _chart_texts(page)
    page.close()
    _assert_translated(texts, errors, warnings)


def test_methodology_frame_has_no_hardcoded_text(server, browser):
    page, errors, warnings = _open(browser, server + "about.html", "() => document.readyState === 'complete'")
    texts = page.evaluate(COLLECT_TEXT)
    page.close()
    _assert_translated(texts, errors, warnings)
