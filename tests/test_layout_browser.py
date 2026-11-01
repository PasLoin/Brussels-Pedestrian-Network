import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

if sync_playwright is None:
    if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
        raise RuntimeError("REQUIRE_BROWSER_TESTS=1 but playwright is not installed")
    pytest.skip("playwright not installed", allow_module_level=True)

_ROOT = Path(__file__).resolve().parent.parent

_VIEWPORTS = [
    (1920, 1080), (1366, 768), (1280, 720), (1024, 640),
    (768, 1024), (414, 896), (390, 844), (360, 740),
]

_PANELS = ["#legend", "#header", "#basemap-control", "#zoom-badge"]

_TALL_LEGEND = """
() => {
  const content = document.getElementById("legend-content");
  content.innerHTML = Array.from({ length: 40 }, (_, i) =>
    `<div class="legend-item"><div class="legend-line"></div><span class="legend-label">Couche ${i}</span></div>`
  ).join("");
  document.getElementById("legend").className = "open";
  document.getElementById("header").className = "open";
  document.getElementById("route-panel").classList.add("visible");
}
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
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(_ROOT))
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
    page.wait_for_timeout(600)
    panel = page.evaluate(_RECTS, ["#route-panel"])["#route-panel"]
    centre = (panel["left"] + panel["right"]) / 2
    assert abs(centre - 640) <= 1
    assert 720 - panel["bottom"] == pytest.approx(28, abs=1)
