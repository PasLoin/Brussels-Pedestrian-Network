import hashlib
import re

import pytest

import build_site
from build_site import DEV_API, DEVTEST_LAND, DEVTEST_PAGE, ROOT, SITE_URL, devtest_path, edit_pages

OSM_API_SHA256 = "abcb97866313a82a4975b54e547a6fdf7f12d0d564feee544794450b5981e417"
PROD_HOSTS = ("https://api.openstreetmap.org", "https://www.openstreetmap.org")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    build_site.build(out, lastmod="2026-11-09")
    return out.resolve()


def _html(path):
    return path.read_text(encoding="utf-8")


def _csp(html):
    content = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    return {d.split()[0]: d.split()[1:] for d in (p.strip() for p in content.split(";")) if d}


def _local_refs(html):
    return re.findall(r'(?:src|href)="(\.\./[^"#?]+|\./[^"#?]+)"', html)


def test_devtest_page_is_rendered_hidden_and_in_dev(site):
    html = _html(site / DEVTEST_PAGE)
    assert 'data-edit-env="dev"' in html
    assert '<meta name="robots" content="noindex, nofollow" />' in html
    assert 'id="edit-panel"' in html
    assert f'<link rel="canonical" href="{SITE_URL}{DEVTEST_PAGE}" />' in html


def test_public_pages_carry_no_edit_code(site):
    for page in build_site.PAGES:
        html = _html(site / page)
        assert "data-edit-env" not in html
        assert "edit/main.js" not in html
        assert "osm-api" not in html
        assert 'name="robots"' not in html


def test_devtest_may_reach_the_dev_api_and_never_production(site):
    csp = _csp(_html(site / DEVTEST_PAGE))
    assert DEV_API in csp["connect-src"]
    for host in PROD_HOSTS:
        assert host not in csp["connect-src"]
    index_csp = _csp(_html(site / "index.html"))
    assert DEV_API not in index_csp["connect-src"]
    for directive, sources in index_csp.items():
        assert set(sources) <= set(csp[directive]), directive


def test_devtest_loads_the_guarded_editor_before_the_map(site):
    html = _html(site / DEVTEST_PAGE)
    osm_api = html.index('src="../vendor/osm-api-4.0.1.min.js"')
    editor = html.index('src="../edit/main.js"')
    map_main = html.index('src="../map/main.js"')
    assert osm_api < editor < map_main


def test_every_local_reference_of_the_test_pages_exists(site):
    for page in (DEVTEST_PAGE, DEVTEST_LAND):
        path = site / page
        for ref in _local_refs(_html(path)):
            assert (path.parent / ref).resolve().is_file(), (page, ref)


def test_devtest_navigation_reaches_the_french_pages(site):
    html = _html(site / DEVTEST_PAGE)
    for name in ("stats.html", "evolution.html", "about.html"):
        assert f'href="../fr/{name}"' in html


def test_land_page_runs_no_inline_script_and_fetches_nothing(site):
    html = _html(site / DEVTEST_LAND)
    csp = _csp(html)
    assert csp["default-src"] == ["'none'"]
    assert csp["script-src"] == ["'self'"]
    assert "connect-src" not in csp
    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html) == []
    assert 'src="../edit/land.js"' in html
    assert 'data-edit-env="dev"' in html
    assert '<meta name="robots" content="noindex, nofollow" />' in html


def test_land_page_has_a_message_for_every_verdict(site):
    html = _html(site / DEVTEST_LAND)
    for verdict in ("working", "ok", "missing", "expired", "mismatch", "denied", "nocode"):
        assert f'id="land-{verdict}"' in html


def test_test_pages_stay_out_of_the_sitemap(site):
    sitemap = _html(site / "sitemap.xml")
    assert "test-api" not in sitemap


def test_editor_notes_and_tooling_are_not_published(site):
    assert not (site / "edit" / "TESTING.md").exists()
    assert not (site / "edit" / "package.json").exists()
    assert (site / "edit" / "main.js").is_file()
    assert (site / "vendor" / "osm-api-4.0.1.LICENSE").is_file()


def test_vendored_osm_api_is_the_reviewed_build():
    data = (ROOT / "vendor" / "osm-api-4.0.1.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == OSM_API_SHA256


def test_devtest_panel_has_a_queue(site):
    assert 'id="edit-queue"' in _html(site / DEVTEST_PAGE)


def test_every_basemap_names_its_imagery_for_changesets():
    src = (ROOT / "map" / "basemaps.js").read_text(encoding="utf-8")
    block = src[src.index("export const BASEMAPS = ["):src.index("export const BASEMAP_STORAGE_KEY")]
    ids = re.findall(r'\bid: "([\w-]+)", label:', block)
    names = re.findall(r'osmName: "([^"]+)"', block)
    assert ids and len(names) == len(ids)
    assert len(set(names)) == len(names)
    assert all("i18n" not in n for n in names)



def test_devtest_exists_in_every_published_language_with_a_working_switch(site):
    config = build_site.load_languages()
    pages = edit_pages(config)
    langs = build_site.published_languages(config)
    assert sorted(spec["lang"] for spec in pages.values()) == sorted(langs)
    assert devtest_path(build_site.DEVTEST_LANG) == DEVTEST_PAGE
    for path, spec in pages.items():
        html = _html(site / path)
        assert f'<html lang="{spec["lang"]}"' in html
        assert 'class="lang-switch"' in html
        assert re.search(rf'href="[^"]+" lang="{spec["lang"]}"[^>]*aria-current="true"', html)
        for other in pages:
            href = "./" + other.rsplit("/", 1)[-1]
            assert f'href="{href}"' in html
            assert (site / path).parent.joinpath(href).resolve().is_file()
        assert _csp(html) == _csp(_html(site / DEVTEST_PAGE))
        assert 'data-edit-env="dev"' in html
        assert '<meta name="robots" content="noindex, nofollow" />' in html
