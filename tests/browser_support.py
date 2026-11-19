import contextlib
import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _required():
    return os.environ.get("REQUIRE_BROWSER_TESTS") == "1"


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if _required():
            raise RuntimeError("REQUIRE_BROWSER_TESTS=1 but playwright is not installed")
        pytest.skip("playwright not installed", allow_module_level=True)
    return sync_playwright


def require_node_modules():
    if not (ROOT / "node_modules" / "maplibre-gl" / "package.json").is_file():
        if _required():
            raise RuntimeError("the site libraries come from node_modules: run npm ci")
        pytest.skip("npm dev dependencies not installed", allow_module_level=True)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextlib.contextmanager
def serve(directory):
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    finally:
        httpd.shutdown()


@contextlib.contextmanager
def chromium():
    sync_playwright = require_playwright()
    with sync_playwright() as p:
        instance = p.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()
