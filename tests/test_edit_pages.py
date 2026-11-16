import hashlib
import re

import pytest

import build_site
from build_site import BETA_LAND, BETA_PAGE, DEV_API, DEVTEST_LAND, DEVTEST_PAGE, ROOT, SITE_URL, devtest_path, edit_pages

OSM_API_JS = "vendor/osm-api-4.0.1/index.min.js"
PROD_HOSTS = build_site.PROD_HOSTS


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


def test_beta_page_is_rendered_hidden_and_in_prod(site):
    html = _html(site / BETA_PAGE)
    assert 'data-edit-env="prod"' in html
    assert '<meta name="robots" content="noindex, nofollow" />' in html
    assert 'id="edit-panel"' in html
    assert f'<link rel="canonical" href="{SITE_URL}{BETA_PAGE}" />' in html
    assert "devtest" not in html


def test_beta_may_reach_production_and_never_the_dev_api(site):
    csp = _csp(_html(site / BETA_PAGE))
    for host in PROD_HOSTS:
        assert host in csp["connect-src"]
    assert DEV_API not in csp["connect-src"]
    dev_csp = _csp(_html(site / DEVTEST_PAGE))
    for directive, sources in dev_csp.items():
        assert directive == "connect-src" or sources == csp[directive], directive
    assert set(dev_csp["connect-src"]) - {DEV_API} == set(csp["connect-src"]) - set(PROD_HOSTS)


def test_beta_land_page_is_the_prod_one_and_the_pages_point_at_each_other(site):
    html = _html(site / BETA_LAND)
    assert 'data-edit-env="prod"' in html
    assert _csp(html) == _csp(_html(site / DEVTEST_LAND))
    assert '<meta name="robots" content="noindex, nofollow" />' in html
    env_js = (ROOT / "edit" / "env.js").read_text(encoding="utf-8")
    assert f'landingPage: "{BETA_LAND.rsplit("/", 1)[-1]}"' in env_js
    assert f'landingPage: "{DEVTEST_LAND.rsplit("/", 1)[-1]}"' in env_js


def test_robots_keep_crawlers_out_of_the_test_pages(site):
    assert "Disallow: /test-api/\n" in _html(site / "robots.txt")


def test_devtest_loads_the_guarded_editor_before_the_map(site):
    html = _html(site / DEVTEST_PAGE)
    osm_api = html.index(f'src="../{OSM_API_JS}"')
    editor = html.index('src="../edit/main.js"')
    map_main = html.index('src="../map/main.js"')
    assert osm_api < editor < map_main


def test_every_local_reference_of_the_test_pages_exists(site):
    for page in (DEVTEST_PAGE, DEVTEST_LAND, BETA_PAGE, BETA_LAND):
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
    assert (site / "vendor" / "osm-api-4.0.1" / "LICENSE").is_file()


def test_served_osm_api_is_the_installed_package(site):
    served = (site / OSM_API_JS).read_bytes()
    installed = (ROOT / "node_modules" / "osm-api" / "dist" / "index.min.js").read_bytes()
    assert hashlib.sha256(served).digest() == hashlib.sha256(installed).digest()


def test_devtest_panel_has_a_queue(site):
    assert 'id="edit-queue"' in _html(site / DEVTEST_PAGE)


def test_only_raster_basemaps_name_their_imagery_for_changesets():
    src = (ROOT / "map" / "basemaps.js").read_text(encoding="utf-8")
    block = src[src.index("export const BASEMAPS = ["):src.index("export const BASEMAP_STORAGE_KEY")]
    entries = re.split(r"\n  \{", block)[1:]
    assert len(entries) >= 4
    for entry in entries:
        assert ("osmName:" in entry) == ("wms:" in entry), entry[:60]
    assert re.findall(r'osmName: "([^"]+)"', block) == ["UrbIS Ortho"]
    assert src.count("if (bm.osmName) store.imageryUsed.add(bm.osmName);") == 2



@pytest.mark.parametrize("edit_env", ["dev", "prod"])
def test_edit_pages_exist_in_every_published_language_with_a_working_switch(site, edit_env):
    config = build_site.load_languages()
    pages = edit_pages(config, edit_env)
    langs = build_site.published_languages(config)
    assert sorted(spec["lang"] for spec in pages.values()) == sorted(langs)
    assert devtest_path(build_site.DEVTEST_LANG) == DEVTEST_PAGE
    assert build_site.edit_path(build_site.DEVTEST_LANG, "prod") == BETA_PAGE
    main_page = build_site.EDIT_ENVS[edit_env]["page"]
    other_pages = [p for env, spec in build_site.EDIT_ENVS.items() if env != edit_env for p in edit_pages(config, env)]
    for path, spec in pages.items():
        html = _html(site / path)
        assert f'<html lang="{spec["lang"]}"' in html
        assert 'class="lang-switch"' in html
        assert re.search(rf'href="[^"]+" lang="{spec["lang"]}"[^>]*aria-current="true"', html)
        for other in pages:
            href = "./" + other.rsplit("/", 1)[-1]
            assert f'href="{href}"' in html
            assert (site / path).parent.joinpath(href).resolve().is_file()
        for other in other_pages:
            assert f'href="./{other.rsplit("/", 1)[-1]}"' not in html
        assert _csp(html) == _csp(_html(site / main_page))
        assert f'data-edit-env="{edit_env}"' in html
        assert '<meta name="robots" content="noindex, nofollow" />' in html



def test_editing_lives_in_its_own_panel_outside_the_header(site):
    html = _html(site / DEVTEST_PAGE)
    header = html[html.index('<div id="header"'):html.index('<div id="route-panel"')]
    assert 'id="edit-panel"' not in header
    dock = html[html.index('<aside id="edit-dock"'):html.index("</aside>")]
    for part in ("edit-dock-toggle", "edit-auth", "edit-status", "edit-detail", "edit-queue"):
        assert f'id="{part}"' in dock
