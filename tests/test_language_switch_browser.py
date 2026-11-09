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

STORAGE_KEY = "bpn-lang"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
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


def _context(browser, locale):
    context = browser.new_context(locale=locale)
    context.route("**/chart.umd.js", lambda r: r.fulfill(body="window.Chart = class {}; Chart.defaults = {};", content_type="text/javascript"))
    return context


def _banner(page):
    return page.evaluate("""() => {
      const banner = document.getElementById('lang-banner');
      return { hidden: banner.hidden, lang: banner.lang, text: document.getElementById('lang-banner-text').textContent,
               link: document.getElementById('lang-banner-switch').textContent,
               close: document.getElementById('lang-banner-close').getAttribute('aria-label') };
    }""")


def test_english_visitor_sees_no_banner(site, browser):
    context = _context(browser, "en-GB")
    page = context.new_page()
    page.goto(site + "about.html")
    assert _banner(page)["hidden"] is True
    context.close()


def test_french_browser_is_offered_french_in_french(site, browser):
    context = _context(browser, "fr-BE")
    page = context.new_page()
    page.goto(site + "about.html")
    banner = _banner(page)
    assert banner == {"hidden": False, "lang": "fr", "text": "Cette page existe aussi en français.",
                      "link": "Passer en français", "close": "Fermer"}
    context.close()


def test_switching_from_the_banner_keeps_the_anchor_and_is_remembered(site, browser):
    context = _context(browser, "fr-BE")
    page = context.new_page()
    page.goto(site + "about.html#indicators")
    page.click("#lang-banner-switch")
    page.wait_for_url("**/fr/about.html#indicators")
    assert page.evaluate(f"localStorage.getItem('{STORAGE_KEY}')") == "fr"
    assert page.evaluate("document.documentElement.lang") == "fr"
    page.goto(site + "stats.html")
    page.wait_for_url("**/fr/stats.html")
    context.close()


def test_dismissing_the_banner_keeps_the_page_language(site, browser):
    context = _context(browser, "fr-BE")
    page = context.new_page()
    page.goto(site + "about.html")
    page.click("#lang-banner-close")
    assert _banner(page)["hidden"] is True
    assert page.evaluate(f"localStorage.getItem('{STORAGE_KEY}')") == "en"
    page.reload()
    assert _banner(page)["hidden"] is True
    assert page.url == site + "about.html"
    context.close()


def test_menu_switches_language_and_root_follows_the_choice(site, browser):
    context = _context(browser, "en-GB")
    page = context.new_page()
    page.goto(site + "fr/about.html")
    assert page.evaluate("document.querySelector('.lang-switch [aria-current]').dataset.lang") == "fr"
    page.click(".lang-switch [data-lang='en']")
    page.wait_for_url(site + "about.html")
    assert page.evaluate(f"localStorage.getItem('{STORAGE_KEY}')") == "en"
    page.goto(site + "about.html")
    assert page.url == site + "about.html"
    context.close()


def test_shared_french_link_is_never_redirected(site, browser):
    context = _context(browser, "en-GB")
    page = context.new_page()
    page.goto(site + "about.html")
    page.evaluate(f"localStorage.setItem('{STORAGE_KEY}', 'en')")
    page.goto(site + "fr/about.html")
    assert page.url == site + "fr/about.html"
    assert _banner(page)["hidden"] is True
    context.close()


def test_saved_choice_redirects_the_map_with_its_position(site, browser):
    context = _context(browser, "en-GB")
    context.add_init_script(f"localStorage.setItem('{STORAGE_KEY}', 'fr')")
    page = context.new_page()
    page.goto(site + "#14/50.8466/4.3528", wait_until="commit")
    page.wait_for_url("**/fr/#14/50.8466/4.3528")
    context.close()


def test_missing_page_offers_every_language(site, browser):
    context = _context(browser, "en-GB")
    page = context.new_page()
    html = page.request.get(site + "404.html").text()
    for lang in build_site.published_languages(build_site.load_languages()):
        assert f'<section lang="{lang}">' in html
    assert 'name="robots" content="noindex"' in html
    context.close()
