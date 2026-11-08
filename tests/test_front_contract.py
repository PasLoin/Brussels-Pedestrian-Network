from config import PED_HIGHWAY_TYPES
from front_contract import (
    APP_STATS_PATHS,
    HISTORY_PATHS,
    FILTER_VALUES,
    LAYER_PROPS,
    PAGES,
    STATS_HTML_PATHS,
    app_stats_block,
    push_trigger_paths,
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
    assert stats_reads(read_text("stats.js")) == STATS_HTML_PATHS


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
    assert history_reads(read_text("evolution.js")) == HISTORY_PATHS


def test_evolution_pedestrian_types_match_config():
    assert evolution_ped_types(read_text("evolution.js")) == PED_HIGHWAY_TYPES


def test_every_local_script_is_deployed_and_triggers_a_site_deploy():
    workflow = read_text(".github/workflows/site.yml")
    scripts = set().union(*(local_scripts(page_text(page)) for page in PAGES))
    assert {"i18n.js", "app.js", "popups.js", "stats.js", "evolution.js"} <= scripts
    assert scripts <= deployed_files()
    assert scripts <= push_trigger_paths(workflow)


def test_every_site_source_triggers_a_site_deploy():
    triggers = push_trigger_paths(read_text(".github/workflows/site.yml"))
    sources = {"build_site.py", "check_i18n.py", "templates/**", "i18n/**", *deployed_files()}
    assert sources <= triggers


def test_data_pipeline_is_not_triggered_by_site_sources():
    triggers = push_trigger_paths(read_text(".github/workflows/build.yml"))
    assert triggers == {".github/workflows/build.yml", "scripts/**"}


def test_both_workflows_render_checked_pages():
    for name in ("build.yml", "site.yml"):
        workflow = read_text(f".github/workflows/{name}")
        assert workflow.index("python3 check_i18n.py") < workflow.index("python3 build_site.py --out _site")


def test_deploying_workflows_never_overlap():
    for name in ("build.yml", "site.yml"):
        workflow = read_text(f".github/workflows/{name}")
        assert "group: gh-pages-deploy" in workflow
        assert "cancel-in-progress: false" in workflow
        assert "publish_branch: gh-pages" in workflow


def test_site_deploy_republishes_every_data_file():
    site = read_text(".github/workflows/site.yml")
    build = read_text(".github/workflows/build.yml")
    copied = build[build.index("name: Prepare site"):]
    copied = copied[copied.index("cp "):copied.index("_site/", copied.index("cp "))].split()[1:]
    assert set(copied) == {"state.txt", "stats.json", "graph.json", "pedestrian.pmtiles", "history.json"}
    for name in copied:
        assert name in site
