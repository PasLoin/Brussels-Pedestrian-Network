from config import PED_HIGHWAY_TYPES
from front_contract import (
    APP_STATS_PATHS,
    HISTORY_PATHS,
    FILTER_VALUES,
    LAYER_PROPS,
    STATS_HTML_PATHS,
    app_stats_block,
    built_layers,
    evolution_ped_types,
    filter_values,
    history_reads,
    layer_props,
    layer_sources,
    read_text,
    slim_highway_props,
    stats_reads,
)


def test_stats_html_reads_match_contract():
    assert stats_reads(read_text("stats.html")) == STATS_HTML_PATHS


def test_app_js_stats_reads_match_contract():
    assert stats_reads(app_stats_block(read_text("app.js"))) == APP_STATS_PATHS


def test_app_js_layer_properties_match_contract():
    assert layer_props(read_text("app.js")) == LAYER_PROPS


def test_app_js_filter_values_match_contract():
    assert filter_values(read_text("app.js")) == FILTER_VALUES


def test_every_layer_read_by_app_js_is_built():
    used = set(layer_sources(read_text("app.js")).values())
    assert used <= built_layers(read_text(".github/workflows/build.yml"))


def test_highways_slim_keeps_properties_read_by_app_js():
    kept = slim_highway_props(read_text(".github/workflows/build.yml"))
    assert LAYER_PROPS["highways"] <= kept


def test_evolution_history_reads_match_contract():
    assert history_reads(read_text("evolution.html")) == HISTORY_PATHS


def test_evolution_pedestrian_types_match_config():
    assert evolution_ped_types(read_text("evolution.html")) == PED_HIGHWAY_TYPES
