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

from test_stats_json_contract import _BAD_TEXT, _CHART_STUB

STATUSES = ("separate", "yes", "documented", "partial", "unknown")

STATS = {
    "graph": {"nodes": 120000, "edges": 150000},
    "network": {
        "total_km": 4321.5,
        "km_by_category": {"pedestrian": 2100.2, "road": 1800.4, "cycleway_foot_yes": 50.1, "cycleway_no_foot": 20.3},
        "km_by_highway": {"footway": 1500.5, "residential": 900.2, "cycleway": 70.4},
    },
    "missing_crossings": {
        "crossing_nodes_found": 9000, "missing_crossing_way": 300, "missing_crossing_tag": 200,
        "wrong_crossing_tag": 50, "crossing_continuous": 120, "on_excluded_way": 80,
    },
    "od_sampling": {"od_points": 5000},
    "routing": {"avg_distance_m": 1234.5, "routed_trips": 25000, "routing_time_s": 42.3},
    "sidewalk_gaps": {
        "roads_analysed": 8000, "skipped_no_sidewalk": 1, "both_sides": 5000, "one_side_gap": 2000,
        "neither_side": 1000, "both_length_km": 800.5, "gap_length_km": 300.2, "neither_length_km": 100.1,
        "footway_filter": {
            "kept": 10000, "kept_sidewalk": 6000, "kept_link": 1000, "kept_crossing": 2000,
            "kept_traffic_island": 300, "kept_pedestrian": 500, "kept_cycleway_foot": 200,
        },
    },
    "sidewalk_roads": {
        "total_road_ways": 15000,
        "by_status": dict(zip(STATUSES, (4000, 3000, 2000, 1500, 4500))),
        "km_by_status": dict(zip(STATUSES, (400.5, 300.2, 200.1, 150.3, 450.7))),
        "pct_by_status": dict(zip(STATUSES, (26.7, 20.0, 13.3, 10.0, 30.0))),
        "separate_all_sides": {"pct": 35.5},
    },
}


def _entry(date, kind, step):
    by_type = {
        hw: {"total": 1000 + step, "separate": 300 + step, "yes_or_both": 200, "partial": 100, "no_explicit": 50}
        for hw in ("residential", "tertiary", "secondary", "primary")
    }
    return {
        "date": date, "type": kind,
        "ped_km": 2000.5 + step, "road_km": 1800.2, "cycleway_km": 70.4 + step,
        "km_by_highway": {"footway": 1500.5 + step, "pedestrian": 80.1, "steps": 12.3, "cycleway": 70.4,
                          "residential": 900.2, "tertiary": 300.1, "secondary": 200.4, "primary": 150.2},
        "footway_ways": 20000 + step, "footway_sidewalk": 9000 + step, "footway_crossing": 6000,
        "footway_link": 1500, "footway_traffic_island": 300, "footway_other": 100, "footway_no_subtag": 3100,
        "crossing_nodes": 9000 + step, "crossing_continuous": 120, "crossing_tagged_pct": 70.5 + step / 10,
        "sidewalk_documented_pct": 60.2 + step / 10, "sidewalk_separate_pct": 30.1, "tactile_paving_pct": 40.3,
        "footway_surface_pct": 55.5, "footway_smoothness_pct": 20.2,
        "road_ways": 15000, "road_sidewalk_separate": 4000, "road_sidewalk_yes_or_both": 3000,
        "road_sidewalk_partial": 1500, "road_sidewalk_no_explicit": 500,
        "road_sidewalk_by_type": by_type,
    }


HISTORY = [
    _entry("2026-08-01", "monthly", 0),
    _entry("2026-09-01", "monthly", 5),
    _entry("2026-10-01", "monthly", 10),
    _entry("2026-11-07", "daily", 12),
]

RAW_KEY = re.compile(r"\b(?:stats|evolution|common|header|meta|layer)\.[a-z]\w*(?:\.\w+)*")
FRENCH_LETTERS = re.compile(r"[àâçéèêëîïôûùüœ]", re.IGNORECASE)
WAIT_FOR_PAGE = "() => window.__charts.length > 0 || document.body.innerText.includes('rror')"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    site = tmp_path_factory.mktemp("site")
    langs = list(build_site.load_languages()["languages"])
    build_site.build(site, langs=langs)
    (site / "stats.json").write_text(json.dumps(STATS), encoding="utf-8")
    (site / "history.json").write_text(json.dumps(HISTORY), encoding="utf-8")
    (site / "state.txt").write_text("build_timestamp=2026-11-08T01:15:00Z\n", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *args: None
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


def _render(browser, url):
    page = browser.new_page()
    errors, warnings = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    page.route("**/chart.umd.js", lambda r: r.fulfill(body=_CHART_STUB, content_type="text/javascript"))
    page.goto(url)
    page.wait_for_function(WAIT_FOR_PAGE, timeout=10000)
    page.wait_for_timeout(200)
    text = page.inner_text("body")
    charts = page.evaluate("window.__charts")
    page.close()
    return text, charts, errors, warnings


def _chart_texts(charts):
    texts = []
    for data in charts:
        texts += [str(label) for label in data.get("labels", [])]
        texts += [str(ds.get("label", "")) for ds in data.get("datasets", [])]
    return texts


PAGES_UNDER_TEST = {"stats.html": "Complétude", "evolution.html": "Période d'analyse"}


@pytest.mark.parametrize("page", PAGES_UNDER_TEST)
@pytest.mark.parametrize("lang", list(build_site.load_languages()["languages"]))
def test_page_renders_fully_translated(server, browser, lang, page):
    folder = build_site.load_languages()["languages"][lang]["path"]
    text, charts, errors, warnings = _render(browser, server + folder + page)
    assert errors == []
    assert [w for w in warnings if "[i18n]" in w] == []
    assert charts
    for shown in [text, *_chart_texts(charts)]:
        assert "{{" not in shown
        assert not RAW_KEY.search(shown), RAW_KEY.search(shown).group(0)
        for bad in _BAD_TEXT:
            assert bad not in shown
    if lang == "fr":
        assert PAGES_UNDER_TEST[page] in text
    if lang == "en":
        leftovers = [s for s in [text, *_chart_texts(charts)] if FRENCH_LETTERS.search(s)]
        assert leftovers == []


def test_stats_numbers_follow_the_page_locale(server, browser):
    fr_text = _render(browser, server + "stats.html")[0]
    en_text = _render(browser, server + "en/stats.html")[0]
    assert re.search(r"4\s321,5", fr_text)
    assert "4,321.5" in en_text
    assert re.search(r"10,0\s%", fr_text)
    assert "10.0%" in en_text
    assert "1 exclue (sidewalk=no documenté)" in fr_text


def test_evolution_dates_and_plurals_follow_the_page_locale(server, browser):
    fr_text = _render(browser, server + "evolution.html")[0]
    en_text = _render(browser, server + "en/evolution.html")[0]
    assert "4 relevés couvrant" in fr_text
    assert "4 snapshots covering" in en_text
    assert "1 Aug 2026" in en_text
    assert re.search(r"1\s(?:er\s)?août\s2026", fr_text)
    assert "4 points shown (zoom active)" in en_text or "Full period · 4 points" in en_text
