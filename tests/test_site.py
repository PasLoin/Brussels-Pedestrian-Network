import re

import pytest

import build_site
from build_site import PAGES, SITE_URL

LASTMOD = "2026-11-08"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    config = build_site.load_languages()
    langs = list(config["languages"])
    build_site.build(out, langs=langs, lastmod=LASTMOD)
    pages = {
        (lang, page): out / config["languages"][lang]["path"] / page
        for lang in langs for page in PAGES
    }
    return out.resolve(), config, pages


def _attr(html, pattern):
    match = re.search(pattern, html)
    assert match, pattern
    return match.group(1)


def _html(path):
    return path.read_text(encoding="utf-8")


def test_every_language_renders_every_page(site):
    _, config, pages = site
    assert len(pages) == len(config["languages"]) * len(PAGES)
    assert all(path.is_file() for path in pages.values())


def test_page_language_matches_its_folder(site):
    _, _, pages = site
    for (lang, _), path in pages.items():
        assert _attr(_html(path), r'<html lang="([^"]+)"') == lang


def test_share_url_is_the_published_location_of_the_page(site):
    out, _, pages = site
    for path in pages.values():
        relative = path.resolve().relative_to(out).as_posix()
        expected = SITE_URL + (relative[: -len("index.html")] if relative.endswith("index.html") else relative)
        assert _attr(_html(path), r'<meta property="og:url" content="([^"]*)"') == expected


def test_share_urls_are_unique(site):
    _, _, pages = site
    urls = [_attr(_html(path), r'<meta property="og:url" content="([^"]*)"') for path in pages.values()]
    assert len(urls) == len(set(urls))


def test_data_root_reaches_the_shared_files(site):
    out, _, pages = site
    for path in pages.values():
        root = _attr(_html(path), r'data-root="([^"]*)"')
        assert (path.parent / root).resolve() == out
        assert (path.parent / root / "i18n.js").is_file()


def test_runtime_is_loaded_before_any_page_script(site):
    _, _, pages = site
    for path in pages.values():
        scripts = re.findall(r'<script src="\.\.?/([\w.-]+\.js)"', _html(path))
        assert scripts[0] == "i18n.js", (path, scripts)


def test_sitemap_lists_only_rendered_pages(site):
    out, _, _ = site
    locations = re.findall(r"<loc>([^<]+)</loc>", (out / "sitemap.xml").read_text(encoding="utf-8"))
    assert locations
    for loc in locations:
        assert loc.startswith(SITE_URL)
        relative = loc[len(SITE_URL):] or "index.html"
        assert (out / relative).is_file(), loc


def test_unpublished_languages_stay_out_of_the_sitemap(site):
    out, config, _ = site
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    for conf in config["languages"].values():
        if not conf["published"] and conf["path"]:
            assert SITE_URL + conf["path"] not in sitemap


FRENCH_LETTERS = re.compile(r"[àâçéèêëîïôûùüœ]", re.IGNORECASE)


def _visible_text(html):
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    texts = re.findall(r">([^<]+)<", html)
    texts += re.findall(r'\s(?:title|aria-label|alt)="([^"]*)"', html)
    texts += re.findall(r'<meta (?:name="description"|property="og:\w+") content="([^"]*)"', html)
    return [" ".join(t.split()) for t in texts if t.strip()]


def test_english_pages_have_no_french_left(site):
    _, _, pages = site
    for (lang, page), path in pages.items():
        if lang != "en":
            continue
        leftovers = [t for t in _visible_text(_html(path)) if FRENCH_LETTERS.search(t)]
        assert leftovers == [], (page, leftovers)


def test_links_to_methodology_anchors_resolve_in_every_language(site):
    out, config, pages = site
    sources = [build_site.ROOT / name for name in build_site.STATIC if name.endswith(".js")]
    sources += [path for path in pages.values()]
    anchors = set()
    for source in sources:
        anchors |= set(re.findall(r"about\.html#([\w-]+)", source.read_text(encoding="utf-8")))
    assert "indicators" in anchors
    for lang in config["languages"]:
        ids = set(re.findall(r'\sid="([^"]+)"', _html(pages[(lang, "about.html")])))
        assert anchors <= ids, (lang, anchors - ids)


def test_methodology_is_written_in_each_language(site):
    _, _, pages = site
    assert "<h1>Methodology</h1>" in _html(pages[("en", "about.html")])
    assert "<h1>Méthodologie</h1>" in _html(pages[("fr", "about.html")])
