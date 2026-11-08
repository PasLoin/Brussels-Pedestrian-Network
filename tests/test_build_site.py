import json
import re

import pytest

import build_site
from build_site import PAGES, ROOT, SITE_URL, STATIC

LASTMOD = "2026-11-07"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    build_site.build(out, lastmod=LASTMOD)
    return out


def _attr(html, pattern):
    match = re.search(pattern, html)
    assert match, pattern
    return match.group(1)


def test_languages_config_is_valid():
    config = build_site.load_languages()
    assert config["reference"] == "en"
    assert build_site.root_language(config) == "fr"


@pytest.mark.parametrize("config, message", [
    ({"reference": "en", "timeZone": "Europe/Brussels", "languages": {
        "fr": {"path": "", "locale": "fr-BE", "og": "fr_BE", "name": "Français", "published": True}}},
     "reference language"),
    ({"reference": "fr", "timeZone": "Europe/Brussels", "languages": {
        "fr": {"path": "", "locale": "fr-BE", "og": "fr_BE", "name": "Français", "published": True},
        "en": {"path": "", "locale": "en-GB", "og": "en_GB", "name": "English", "published": True}}},
     "same path"),
    ({"reference": "fr", "timeZone": "Europe/Brussels", "languages": {
        "fr": {"path": "fr/", "locale": "fr-BE", "og": "fr_BE", "name": "Français", "published": True}}},
     "root"),
    ({"reference": "fr", "timeZone": "Europe/Brussels", "languages": {
        "fr": {"path": "", "locale": "fr-BE", "og": "fr_BE", "name": "Français", "published": True},
        "nl": {"path": "nederlands/", "locale": "nl-BE", "og": "nl_BE", "name": "Nederlands", "published": False}}},
     "invalid path"),
    ({"reference": "fr", "timeZone": "Europe/Brussels", "languages": {
        "fr": {"path": "", "locale": "fr-BE", "name": "Français", "published": True}}},
     "missing og"),
])
def test_invalid_languages_config_is_rejected(config, message):
    with pytest.raises(ValueError, match=message):
        build_site.validate_languages(config)


def test_only_published_languages_are_built_by_default(site):
    assert not (site / "en").exists()
    for page in PAGES:
        assert (site / page).is_file()


@pytest.mark.parametrize("page", PAGES)
def test_page_has_no_template_syntax_left(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert not re.search(r"\{\{|\{%|\{#", html)


@pytest.mark.parametrize("page", PAGES)
def test_page_language_and_url(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert html.startswith('<!DOCTYPE html>\n<html lang="fr">\n')
    expected = SITE_URL + ("" if page == "index.html" else page)
    assert _attr(html, r'<meta property="og:url" content="([^"]*)"') == expected


@pytest.mark.parametrize("page", PAGES)
def test_share_preview_repeats_title_and_description(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert _attr(html, r"<title>(.*?)</title>") == _attr(html, r'<meta property="og:title" content="([^"]*)"')
    assert _attr(html, r'<meta name="description" content="([^"]*)"') == _attr(html, r'<meta property="og:description" content="([^"]*)"')


@pytest.mark.parametrize("page", PAGES)
def test_every_local_link_of_the_page_is_published(site, page):
    html = (site / page).read_text(encoding="utf-8")
    targets = re.findall(r'(?:href|src)="\./([^"#?]*)', html)
    assert targets
    for target in targets:
        assert (site / (target or "index.html")).is_file(), target


def test_map_page_keeps_its_wider_content_security_policy(site):
    csp = r'http-equiv="Content-Security-Policy" content="([^"]*)"'
    index = _attr((site / "index.html").read_text(encoding="utf-8"), csp)
    stats = _attr((site / "stats.html").read_text(encoding="utf-8"), csp)
    assert "https://protomaps.github.io" in index
    assert "https://protomaps.github.io" not in stats


def test_static_files_are_copied_unchanged(site):
    for name in STATIC:
        assert (site / name).read_bytes() == (ROOT / name).read_bytes(), name


def test_sitemap_gets_its_lastmod(site):
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert build_site.LASTMOD_PLACEHOLDER not in sitemap
    assert sitemap.count(f"<lastmod>{LASTMOD}</lastmod>") == len(PAGES)


def test_unpublished_language_is_built_on_request(tmp_path):
    assert build_site.build(tmp_path, langs=["en"]) == ["en"]
    html = (tmp_path / "en" / "stats.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    assert f'content="{SITE_URL}en/stats.html"' in html
    assert not (tmp_path / "index.html").exists()


def test_unknown_language_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="xx"):
        build_site.build(tmp_path, langs=["xx"])


@pytest.mark.parametrize("target", [ROOT, ROOT.parent])
def test_build_refuses_to_wipe_the_repository(target):
    with pytest.raises(ValueError, match="refusing"):
        build_site.build(target)


def test_cli_reports_errors_without_traceback(tmp_path, capsys):
    assert build_site.main(["--out", str(tmp_path / "site"), "--lang", "xx"]) == 1
    assert "[ERROR]" in capsys.readouterr().err


def test_cli_builds_the_site(tmp_path, capsys):
    assert build_site.main(["--out", str(tmp_path / "site"), "--lastmod", LASTMOD]) == 0
    assert "[OK]" in capsys.readouterr().out
    assert json.loads((tmp_path / "site" / "style.json").read_text(encoding="utf-8"))
