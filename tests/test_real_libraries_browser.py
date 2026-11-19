import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

import build_site
from browser_coverage import track
from browser_support import require_playwright, serve

require_playwright()

from map_fixtures import CATCH_MAP_ERRORS, empty_pmtiles
from test_pages_i18n_browser import HISTORY, STATS

ROOT = Path(__file__).resolve().parent.parent
LIBERTY_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"
OFFLINE_STYLE = {
    "version": 8,
    "sources": {},
    "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#f2efe9"}}],
}
ROUTE = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"color": "#0057b8"},
        "geometry": {"type": "LineString", "coordinates": [[4.3480, 50.8490], [4.3517, 50.8503], [4.3555, 50.8515]]},
    }],
}
GRAPH = {
    "hw": ["footway"],
    "n": [[4.3480, 50.8490], [4.3517, 50.8503]],
    "e": [
        [0, 1, 290.0, 290.0, 0, 0, [[4.3480, 50.8490], [4.3517, 50.8503]], 1],
        [1, 0, 290.0, 290.0, 0, 0, [[4.3517, 50.8503], [4.3480, 50.8490]], 1],
    ],
}


def pinned(package):
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["devDependencies"][package]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not (ROOT / "node_modules" / "maplibre-gl" / "package.json").exists():
        pytest.skip("node_modules missing: run npm ci")
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    (out / "stats.json").write_text(json.dumps(STATS), encoding="utf-8")
    (out / "history.json").write_text(json.dumps(HISTORY), encoding="utf-8")
    (out / "state.txt").write_text("build_timestamp=2026-11-08T01:15:00Z\n", encoding="utf-8")
    (out / "pedestrian.pmtiles").write_bytes(empty_pmtiles())
    (out / "graph.json").write_text(json.dumps(GRAPH), encoding="utf-8")
    with serve(out) as url:
        yield url


def open_page(browser, site, path):
    page = browser.new_page()
    track(page.context, page, site)
    problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"console: {m.text}") if m.type == "error" and "Content Security Policy" in m.text else None)
    page.on("requestfailed", lambda r: problems.append(f"failed: {r.url}") if urlparse(r.url).hostname == "127.0.0.1" else None)
    page.on("response", lambda r: problems.append(f"{r.status}: {r.url}") if urlparse(r.url).hostname == "127.0.0.1" and r.status >= 400 else None)

    def offline(route):
        if route.request.url.split("?")[0] == LIBERTY_STYLE_URL:
            route.fulfill(body=json.dumps(OFFLINE_STYLE), content_type="application/json")
        else:
            route.abort()

    page.route(lambda url: urlparse(url).hostname not in ("127.0.0.1", None), offline)
    page.add_init_script(CATCH_MAP_ERRORS)
    page.goto(site + path)
    return page, problems


def test_the_public_map_runs_on_the_pinned_maplibre_and_draws_through_its_worker(browser, site):
    page, problems = open_page(browser, site, "index.html")
    page.wait_for_function("async () => (await import('./map/store.js')).store.mapReady === true", timeout=30000)
    assert page.evaluate("maplibregl.getVersion()") == pinned("maplibre-gl")
    page.wait_for_function("""async () => {
      const m = (await import('./map/store.js')).store.map;
      return !!m.getSource('nav-route') && !!m.getSource('pedestrian') && m.getCanvas().width > 0;
    }""", timeout=15000)
    drawn = page.evaluate("""async (route) => {
      const m = (await import('./map/store.js')).store.map;
      const idle = new Promise((resolve) => m.once('idle', resolve));
      m.jumpTo({ center: [4.3517, 50.8503], zoom: 15 });
      m.getSource('nav-route').setData(route);
      await Promise.race([idle, new Promise((resolve) => setTimeout(resolve, 15000))]);
      return {
        source: m.querySourceFeatures('nav-route').length,
        rendered: m.queryRenderedFeatures({ layers: ['nav-route-line'] }).length,
      };
    }""", ROUTE)
    assert drawn["source"] > 0
    assert drawn["rendered"] > 0
    assert page.evaluate("window.__mapErrors") == []
    assert problems == []
    page.close()


@pytest.mark.parametrize("path", ["stats.html", "evolution.html"])
def test_the_chart_pages_draw_with_the_pinned_chart_js(browser, site, path):
    page, problems = open_page(browser, site, path)
    page.wait_for_function("() => window.Chart && Object.keys(Chart.instances).length > 0", timeout=20000)
    page.wait_for_timeout(500)
    assert page.evaluate("Chart.version") == pinned("chart.js")
    charts = page.evaluate("""() => Object.values(Chart.instances).map((chart) => {
      const canvas = chart.canvas;
      const ctx = canvas.getContext('2d');
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let painted = 0;
      for (let i = 3; i < pixels.length; i += 4) if (pixels[i] !== 0) painted++;
      return {
        id: canvas.id,
        width: canvas.width,
        height: canvas.height,
        datasets: chart.data.datasets.length,
        points: chart.data.datasets.reduce((n, d) => n + (d.data || []).length, 0),
        painted,
      };
    })""")
    canvases = page.evaluate("document.querySelectorAll('canvas').length")
    assert len(charts) == canvases
    for chart in charts:
        assert chart["width"] > 0 and chart["height"] > 0, chart
        assert chart["datasets"] > 0 and chart["points"] > 0, chart
        assert chart["painted"] > 0, chart
    assert problems == []
    page.close()
