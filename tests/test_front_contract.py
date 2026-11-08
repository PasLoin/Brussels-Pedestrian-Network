from config import PED_HIGHWAY_TYPES
from front_contract import (
    APP_STATS_PATHS,
    HISTORY_PATHS,
    FILTER_VALUES,
    LAYER_PROPS,
    PAGES,
    STATS_HTML_PATHS,
    app_stats_block,
    build_trigger_paths,
    built_layers,
    deployed_files,
    evolution_ped_types,
    filter_values,
    front_js,
    history_reads,
    layer_props,
    layer_sources,
    local_scripts,
    page_text,
    read_text,
    slim_highway_props,
    stats_reads,
)


def test_stats_html_reads_match_contract():
    assert stats_reads(page_text("stats.html")) == STATS_HTML_PATHS


def test_app_js_stats_reads_match_contract():
    assert stats_reads(app_stats_block(read_text("app.js"))) == APP_STATS_PATHS


def test_app_js_layer_properties_match_contract():
    assert layer_props(front_js()) == LAYER_PROPS


def test_app_js_filter_values_match_contract():
    assert filter_values(front_js()) == FILTER_VALUES


def test_every_layer_read_by_app_js_is_built():
    used = set(layer_sources(front_js()).values())
    assert used <= built_layers(read_text(".github/workflows/build.yml"))


def test_highways_slim_keeps_properties_read_by_app_js():
    kept = slim_highway_props(read_text(".github/workflows/build.yml"))
    assert LAYER_PROPS["highways"] <= kept


def test_evolution_history_reads_match_contract():
    assert history_reads(page_text("evolution.html")) == HISTORY_PATHS


def test_evolution_pedestrian_types_match_config():
    assert evolution_ped_types(page_text("evolution.html")) == PED_HIGHWAY_TYPES


def test_every_local_script_is_deployed_and_triggers_a_rebuild():
    workflow = read_text(".github/workflows/build.yml")
    scripts = set().union(*(local_scripts(page_text(page)) for page in PAGES))
    assert {"app.js", "popups.js"} <= scripts
    assert scripts <= deployed_files()
    assert scripts <= build_trigger_paths(workflow)


def test_site_sources_trigger_a_rebuild_and_are_rendered():
    workflow = read_text(".github/workflows/build.yml")
    assert {"build_site.py", "templates/**", "i18n/**", "sitemap.xml"} <= build_trigger_paths(workflow)
    assert "python3 build_site.py --out _site" in workflow
