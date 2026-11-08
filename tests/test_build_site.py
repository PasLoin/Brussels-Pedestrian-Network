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


@pytest.fixture(scope="module")
def every_language(tmp_path_factory):
    out = tmp_path_factory.mktemp("every_language")
    langs = list(build_site.load_languages()["languages"])
    build_site.build(out, langs=langs, lastmod=LASTMOD)
    return out, langs


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
    markup = re.sub(r'<script type="application/json" id="i18n-dict">.*?</script>', "", html, flags=re.S)
    assert not re.search(r"\{\{|\{%|\{#", markup)


@pytest.mark.parametrize("page", PAGES)
def test_page_language_and_url(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert html.startswith(
        '<!DOCTYPE html>\n<html lang="fr" data-locale="fr-BE" data-time-zone="Europe/Brussels" data-root="./">\n'
    )
    expected = SITE_URL + ("" if page == "index.html" else page)
    assert _attr(html, r'<meta property="og:url" content="([^"]*)"') == expected


@pytest.mark.parametrize("page", PAGES)
def test_share_preview_repeats_title_and_description(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert _attr(html, r"<title>(.*?)</title>") == _attr(html, r'<meta property="og:title" content="([^"]*)"')
    assert _attr(html, r'<meta name="description" content="([^"]*)"') == _attr(html, r'<meta property="og:description" content="([^"]*)"')


@pytest.mark.parametrize("page", PAGES)
def test_every_local_link_of_every_language_is_published(every_language, page):
    out, langs = every_language
    config = build_site.load_languages()
    for lang in langs:
        folder = out / config["languages"][lang]["path"]
        html = (folder / page).read_text(encoding="utf-8")
        targets = re.findall(r'(?:href|src)="(\.\.?/[^"#?]*)', html)
        assert targets
        for target in targets:
            resolved = (folder / target).resolve()
            if target.endswith("/"):
                resolved = resolved / "index.html"
            assert resolved.is_relative_to(out.resolve()), (lang, target)
            assert resolved.is_file(), (lang, target)


@pytest.mark.parametrize("page", PAGES)
def test_page_embeds_its_dictionary_and_runtime(every_language, page):
    out, langs = every_language
    config = build_site.load_languages()
    for lang in langs:
        conf = config["languages"][lang]
        html = (out / conf["path"] / page).read_text(encoding="utf-8")
        embedded = _attr(html, r'<script type="application/json" id="i18n-dict">(.*?)</script>')
        assert json.loads(embedded) == build_site.page_dictionary(config, lang)
        assert f'data-locale="{conf["locale"]}"' in html
        assert f'data-root="{build_site.page_root(conf)}"' in html
        assert html.index("i18n.js") < html.index("</head>")


def _write(directory, lang, tree):
    (directory / f"{lang}.json").write_text(json.dumps(tree), encoding="utf-8")


def test_dictionaries_are_flattened_into_dotted_keys(tmp_path):
    _write(tmp_path, "en", {"map": {"legend": {"title": "Legend"}, "trips_one": "{{count}} trip", "trips_other": "{{count}} trips"}})
    assert build_site.load_dictionary("en", tmp_path) == {
        "map.legend.title": "Legend",
        "map.trips_one": "{{count}} trip",
        "map.trips_other": "{{count}} trips",
    }


@pytest.mark.parametrize("tree, message", [
    ({"map": {"legend.title": "x"}}, "invalid key"),
    ({"map_one": {"title": "x"}}, "invalid group key"),
    ({"map": {"trips_some": "x"}}, "invalid key"),
    ({"map": {"count": 3}}, "must be a string"),
    (["map"], "must be an object"),
])
def test_malformed_dictionaries_are_rejected(tmp_path, tree, message):
    _write(tmp_path, "en", tree)
    with pytest.raises(ValueError, match=message):
        build_site.load_dictionary("en", tmp_path)


def test_missing_dictionary_is_reported(tmp_path):
    with pytest.raises(ValueError, match="missing dictionary nl.json"):
        build_site.load_dictionary("nl", tmp_path)


def test_missing_keys_fall_back_to_the_reference_by_plural_family(tmp_path):
    _write(tmp_path, "en", {"a": "A", "b": "B", "trips_one": "1 trip", "trips_other": "n trips"})
    _write(tmp_path, "pl", {"b": "Bé", "trips_few": "kilka", "trips_other": "wiele"})
    config = {"reference": "en", "languages": {}}
    assert build_site.page_dictionary(config, "pl", tmp_path) == {
        "a": "A", "b": "Bé", "trips_few": "kilka", "trips_other": "wiele",
    }
    assert build_site.page_dictionary(config, "en", tmp_path)["trips_one"] == "1 trip"


def test_embedded_dictionary_cannot_close_its_script_tag():
    text = str(build_site.dictionary_json({"x": "</script><b>&"}))
    assert "<" not in text and ">" not in text and "&" not in text
    assert json.loads(text) == {"x": "</script><b>&"}


def test_template_translator_fills_variables_and_fails_loudly():
    t = build_site.translator({"route.walk": "{{ minutes }} min walk"})
    assert t("route.walk", minutes=12) == "12 min walk"
    with pytest.raises(KeyError, match="minutes"):
        t("route.walk")
    with pytest.raises(KeyError, match="route.unknown"):
        t("route.unknown")


@pytest.mark.parametrize("path, root", [("", "./"), ("fr/", "../")])
def test_page_root_points_to_shared_assets(path, root):
    assert build_site.page_root({"path": path}) == root


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
    assert '<html lang="en" data-locale="en-GB" data-time-zone="Europe/Brussels" data-root="../">' in html
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


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_no_inline_script(site, page):
    html = (site / page).read_text(encoding="utf-8")
    inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
    assert all('type="application/json"' in attrs for attrs in inline), inline


@pytest.mark.parametrize("page", PAGES)
def test_page_has_no_inline_event_handler(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert not re.search(r"<[^>]*\son[a-z]+\s*=", html)


@pytest.mark.parametrize("page", PAGES)
def test_script_policy_forbids_inline_code(site, page):
    html = (site / page).read_text(encoding="utf-8")
    csp = _attr(html, r'http-equiv="Content-Security-Policy" content="([^"]*)"')
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "'self'" in script_src
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
