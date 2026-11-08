import functools
import http.server
import os
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


_VIEWPORTS = [
    (1920, 1080), (1366, 768), (1280, 720), (1024, 640),
    (768, 1024), (600, 900), (540, 960), (414, 896), (390, 844), (360, 740),
]

_PANELS = ["#legend", "#header", "#basemap-control", "#zoom-badge"]

_TALL_LEGEND = """
() => {
  hideRoutePanel();
  const content = document.getElementById("legend-content");
  content.innerHTML = Array.from({ length: 40 }, (_, i) =>
    `<div class="legend-item"><div class="legend-line"></div><span class="legend-label">Couche ${i}</span></div>`
  ).join("");
  setLegendOpen(true);
  const header = document.getElementById("header");
  header.classList.add("open");
  header.classList.remove("closed");
}
"""

_SHOW = "() => showRoutePanel()"
_HIDE = "() => hideRoutePanel()"
_LEGEND_STATE = """
() => ({
  open: document.getElementById("legend").classList.contains("open"),
  closed: document.getElementById("legend").classList.contains("closed"),
  expanded: document.getElementById("legend-toggle").getAttribute("aria-expanded"),
})
"""

_RECTS = """
(selectors) => Object.fromEntries(selectors.map(sel => {
  const el = document.querySelector(sel);
  if (!el) return [sel, null];
  const r = el.getBoundingClientRect();
  return [sel, { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }];
}))
"""


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    site = tmp_path_factory.mktemp("site")
    build_site.build(site)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    httpd.shutdown()


@pytest.fixture(scope="module")
def page(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.goto(server, wait_until="domcontentloaded")
        yield pg
        browser.close()


def _overlap(a, b):
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


@pytest.mark.parametrize("width, height", _VIEWPORTS, ids=[f"{w}x{h}" for w, h in _VIEWPORTS])
def test_route_panel_is_not_covered(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_SHOW)
    page.wait_for_timeout(600)
    rects = page.evaluate(_RECTS, ["#route-panel", *_PANELS])

    panel = rects["#route-panel"]
    assert panel is not None and panel["width"] > 0 and panel["height"] > 0
    assert panel["left"] >= 0 and panel["right"] <= width
    assert panel["top"] >= 0 and panel["bottom"] <= height
    for sel in _PANELS:
        other = rects[sel]
        if other is None or other["width"] == 0 or other["height"] == 0:
            continue
        assert not _overlap(panel, other), f"{sel} overlaps the route panel at {width}x{height}: {other} vs {panel}"


def test_route_panel_sits_at_the_bottom_centre(page):
    page.set_viewport_size({"width": 1280, "height": 720})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_SHOW)
    page.wait_for_timeout(600)
    panel = page.evaluate(_RECTS, ["#route-panel"])["#route-panel"]
    centre = (panel["left"] + panel["right"]) / 2
    assert abs(centre - 640) <= 1
    assert 720 - panel["bottom"] == pytest.approx(28, abs=1)


def _legend(page):
    return page.evaluate(_LEGEND_STATE)


@pytest.mark.parametrize("width, height", [(600, 900), (540, 960), (414, 896), (390, 844), (360, 740)])
def test_phone_collapses_the_legend_and_restores_it(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_SHOW)
    assert _legend(page) == {"open": False, "closed": True, "expanded": "false"}
    page.evaluate(_HIDE)
    assert _legend(page) == {"open": True, "closed": False, "expanded": "true"}


@pytest.mark.parametrize("width, height", [(1920, 1080), (1280, 720), (768, 1024), (601, 900)])
def test_larger_screens_keep_the_legend_open(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_SHOW)
    assert _legend(page)["open"] is True
    page.evaluate(_HIDE)
    assert _legend(page)["open"] is True


def test_closed_legend_is_not_reopened_after_the_route(page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate(_TALL_LEGEND)
    page.evaluate("() => setLegendOpen(false)")
    page.evaluate(_SHOW)
    page.evaluate(_HIDE)
    assert _legend(page)["open"] is False


def test_user_choice_during_the_route_wins(page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_SHOW)
    page.evaluate("() => toggleLegend()")
    page.evaluate("() => toggleLegend()")
    page.evaluate(_HIDE)
    assert _legend(page)["open"] is False


def test_popups_js_is_loaded_before_app_js(page):
    assert page.evaluate("() => [typeof makePopupLayers, typeof escapeHTML]") == ["function", "function"]


@pytest.mark.parametrize("width, height", [(600, 900), (414, 896), (390, 844), (375, 667), (360, 740)])
def test_phone_header_and_legend_never_overlap(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_HIDE)
    page.evaluate("() => { setLegendOpen(false); setHeaderOpen(false); }")
    page.wait_for_timeout(400)
    for action in ["() => toggleLegend()", "() => toggleHeader()", "() => toggleLegend()", "() => setLegendOpen(false)"]:
        page.evaluate(action)
        page.wait_for_timeout(400)
        rects = page.evaluate(_RECTS, ["#header", "#legend"])
        assert not _overlap(rects["#header"], rects["#legend"]), f"{action} at {width}x{height}: {rects}"


def test_desktop_legend_shows_its_last_item(page):
    page.set_viewport_size({"width": 1600, "height": 1000})
    page.evaluate(_TALL_LEGEND)
    page.evaluate(_HIDE)
    page.wait_for_timeout(400)
    sizes = page.evaluate("""
() => {
  const c = document.getElementById("legend-content");
  const legend = document.getElementById("legend");
  legend.scrollTop = legend.scrollHeight;
  const last = c.lastElementChild.getBoundingClientRect();
  return { scroll: c.scrollHeight, client: c.clientHeight, last: last.bottom, legend: legend.getBoundingClientRect().bottom };
}
""")
    assert sizes["client"] >= sizes["scroll"]
    assert sizes["last"] <= sizes["legend"]


_COLLECT_CSP_VIOLATIONS = """
window.__cspViolations = [];
document.addEventListener("securitypolicyviolation", e => window.__cspViolations.push(`${e.violatedDirective} ${e.blockedURI}`));
"""


def test_controls_work_without_inline_scripts(page, server):
    pg = page.context.browser.new_page(viewport={"width": 1280, "height": 720})
    pg.add_init_script(_COLLECT_CSP_VIOLATIONS)
    pg.goto(server, wait_until="domcontentloaded")
    pg.wait_for_function("() => typeof toggleLegend === 'function'")

    legend_before = pg.evaluate(_LEGEND_STATE)
    pg.dispatch_event("#legend-toggle", "click")
    assert pg.evaluate(_LEGEND_STATE)["open"] != legend_before["open"]

    header_open = "() => document.getElementById('header').classList.contains('open')"
    header_before = pg.evaluate(header_open)
    pg.dispatch_event("#header-toggle", "click")
    assert pg.evaluate(header_open) != header_before

    pg.eval_on_selector("#flow-threshold-slider", "el => { el.value = '50'; el.dispatchEvent(new Event('input')); }")
    assert pg.inner_text("#flow-threshold-val") == "50 %"

    pg.evaluate(_SHOW)
    pg.dispatch_event("#route-clear", "click")
    assert not pg.evaluate("() => document.getElementById('route-panel').classList.contains('visible')")

    violations = [v for v in pg.evaluate("window.__cspViolations") if v.startswith("script-src")]
    assert violations == []
    pg.close()
