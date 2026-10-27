from pathlib import Path

import pytest
import yaml

from pwg_criteria import (
    PwgConfigError,
    load_criteria,
    merge_criteria,
    up_to_tier,
)
from pwg_schema_fetch import (
    PwgStructureError,
    _expand_key,
    dump_yaml,
    main as fetch_main,
    parse_schema_html,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pwg_schema.html"
PAGE = "Foundation/Local Chapters/United States/Pedestrian Working Group/Schema"


@pytest.fixture(scope="module")
def schema():
    return parse_schema_html(FIXTURE.read_text(encoding="utf-8"), title=PAGE, revision=2971851)


def _criterion(schema, crit_id):
    for feature in schema["features"].values():
        for crit in feature["criteria"]:
            if crit["id"] == crit_id:
                return crit
    raise KeyError(crit_id)


def test_only_guideline_sections_are_features(schema):
    assert list(schema["features"]) == [
        "sidewalks", "crossings", "curbs", "islands", "access_aisles", "roadways",
    ]


def test_criteria_count(schema):
    counts = {slug: len(f["criteria"]) for slug, f in schema["features"].items()}
    assert counts == {
        "sidewalks": 7, "crossings": 15, "curbs": 4,
        "islands": 7, "access_aisles": 8, "roadways": 2,
    }


def test_source_metadata(schema):
    src = schema["source"]
    assert src["revision"] == 2971851
    assert src["pwg_version"] == "1.0.1"
    assert src["url"].endswith("oldid=2971851")
    assert schema["tiers"] == ["bronze", "silver", "gold", "diamond"]


def test_version_from_versioned_page_title():
    html = FIXTURE.read_text(encoding="utf-8")
    doc = parse_schema_html(html, title=PAGE + "/1.0.0")
    assert doc["source"]["pwg_version"] == "1.0.0"


def test_draft_page_is_not_labelled_as_a_release():
    html = FIXTURE.read_text(encoding="utf-8")
    src = parse_schema_html(html, title="Draft:" + PAGE)["source"]
    assert src["pwg_version"] is None
    assert src["draft"] is True
    assert src["latest_release"] == "1.0.1"


def test_selectors(schema):
    crossings = schema["features"]["crossings"]["selectors"]
    assert [s["tags"] for s in crossings] == [
        {"highway": "footway", "footway": "crossing"},
        {"highway": "crossing"},
    ]
    assert crossings[1]["elements"] == ["node"]
    assert schema["features"]["curbs"]["selectors"][0]["tier"] == "silver"


def test_wildcard_only_table_uses_first_row_as_selector(schema):
    roadways = schema["features"]["roadways"]
    assert roadways["selectors"][0]["tags"] == {"highway": "*"}
    assert [c["id"] for c in roadways["criteria"]] == [
        "roadways.sidewalk:(left|right|both)",
        "roadways.maxspeed",
    ]


def test_tier_is_lowest_filled_column(schema):
    assert _criterion(schema, "sidewalks.surface")["tier"] == "silver"
    assert _criterion(schema, "sidewalks.incline")["tier"] == "gold"
    assert _criterion(schema, "sidewalks.lit")["tier"] == "gold"
    assert _criterion(schema, "crossings.width")["tier"] == "gold"
    assert _criterion(schema, "roadways.maxspeed")["tier"] == "gold"
    assert _criterion(schema, "crossings.traffic_signals:minimap")["tier"] == "diamond"


def test_merged_cell_is_recorded_once(schema):
    assert list(_criterion(schema, "sidewalks.surface")["levels"]) == ["silver"]
    assert list(_criterion(schema, "sidewalks.incline")["levels"]) == ["gold", "diamond"]
    signals = _criterion(schema, "crossings.crossing:signals")["levels"]
    assert signals["bronze"]["values"] == ["yes", "no"]
    assert signals["diamond"]["values"] == ["shared", "dedicated"]


def test_levels_keep_values_per_tier(schema):
    markings = _criterion(schema, "crossings.crossing:markings")
    assert markings["levels"]["bronze"]["values"] == ["yes", "no"]
    assert markings["levels"]["silver"]["values"] == ["zebra", "lines"]
    assert markings["elements"] == ["way", "node"]


def test_tag_codes_are_not_values(schema):
    sidewalk = _criterion(schema, "roadways.sidewalk:(left|right|both)")
    assert sidewalk["levels"]["bronze"]["values"] == ["no", "separate"]
    assert sidewalk["keys"] == ["sidewalk:left", "sidewalk:right", "sidewalk:both"]


def test_duplicate_keys_get_element_suffix(schema):
    ids = [c["id"] for c in schema["features"]["crossings"]["criteria"]]
    assert "crossings.tactile_paving@node" in ids
    assert "crossings.tactile_paving@way" in ids
    assert "crossings.tactile_paving" not in ids


def test_short_rows_are_reported(schema):
    assert len(schema["warnings"]) == 2
    assert all(w.startswith("Islands:") and "5 colonnes sur 6" in w for w in schema["warnings"])
    assert _criterion(schema, "islands.surface")["tier"] == "bronze"


def test_edit_links_are_ignored(schema):
    assert all("edit" not in f["title"] for f in schema["features"].values())


def test_descriptions_keep_line_breaks(schema):
    desc = _criterion(schema, "curbs.kerb")["levels"]["silver"]["description"]
    assert desc.splitlines() == [
        "Specify the curb type:",
        "raised - Raised curb",
        "lowered - Curb ramp",
        "flush - Flush curb",
        "rolled - Rolled curb",
        "no - There is no curb",
    ]


def test_tag_codes_inside_descriptions_are_not_values(schema):
    tactile = _criterion(schema, "sidewalks.tactile_paving")["levels"]["diamond"]
    assert tactile["values"] == ["yes", "no"]
    assert "tactile_paving=*" in tactile["description"]


def test_yaml_roundtrip_keeps_yes_no_as_strings(schema):
    reloaded = yaml.safe_load(dump_yaml(schema))
    assert reloaded["features"]["crossings"]["criteria"][0]["levels"]["bronze"]["values"] == ["yes", "no"]
    assert reloaded == schema


def test_colspan_and_rowspan_are_expanded():
    html = (
        '<div class="mw-heading mw-heading2"><h2>Tagging Guidelines</h2></div>'
        '<div class="mw-heading mw-heading3"><h3>Ramps</h3></div>'
        "<table><tr><th>Tag</th><th>Element</th><th>Bronze</th><th>Silver</th></tr>"
        "<tr><td><code>highway=footway</code> + <code>footway=ramp</code></td>"
        '<td rowspan="2"><img alt="way"></td><td colspan="2">Ramp location</td></tr>'
        "<tr><td><code>incline=*</code></td><td></td><td>Direction <code>up</code></td></tr>"
        "</table>"
    )
    doc = parse_schema_html(html)
    feature = doc["features"]["ramps"]
    assert feature["selectors"][0]["tier"] == "bronze"
    assert doc["warnings"] == []
    crit = feature["criteria"][0]
    assert crit["elements"] == ["way"]
    assert crit["tier"] == "silver"
    assert crit["levels"]["silver"]["values"] == ["up"]


def test_expand_key():
    assert _expand_key("surface") == ["surface"]
    assert _expand_key("sidewalk:(left|right)") == ["sidewalk:left", "sidewalk:right"]
    assert _expand_key("a:(x|y):(1|2)") == ["a:x:1", "a:x:2", "a:y:1", "a:y:2"]


def test_structure_change_is_an_error():
    with pytest.raises(PwgStructureError):
        parse_schema_html("<h2>Something else</h2><table><tr><th>Tag</th></tr></table>")


def test_cli_offline_write_and_check(tmp_path, capsys):
    out = tmp_path / "schema.yaml"
    args = ["--html", str(FIXTURE), "--page", PAGE, "--revision", "1", "--output", str(out)]
    assert fetch_main(args) == 0
    assert out.exists()
    assert fetch_main(args + ["--check"]) == 0
    out.write_text(out.read_text() + "\n")
    assert fetch_main(args + ["--check"]) == 1


def _by_id(criteria):
    return {c.id: c for c in criteria}


def test_merge_without_overrides(schema):
    criteria = _by_id(merge_criteria(schema))
    assert criteria["curbs.kerb"].origin == "pwg"
    assert criteria["curbs.kerb"].values == ("raised", "lowered", "flush", "rolled", "no")
    assert criteria["crossings.crossing:markings"].values == ("yes", "no", "zebra", "lines")
    assert all(c.enabled for c in criteria.values())


def test_override_tier_values_and_disable(schema):
    overrides = {
        "criteria": {
            "islands.surface": {"tier": "silver", "reason": "incohérence wiki"},
            "roadways.maxspeed": {"enabled": False, "reason": "hors périmètre"},
            "curbs.kerb": {"values": ["raised", "lowered", "flush", "no"], "reason": "rolled absent à Bruxelles"},
        },
    }
    criteria = _by_id(merge_criteria(schema, overrides))
    assert criteria["islands.surface"].tier == "silver"
    assert criteria["islands.surface"].overridden == ("tier",)
    assert criteria["islands.surface"].reason == "incohérence wiki"
    assert criteria["roadways.maxspeed"].enabled is False
    assert criteria["curbs.kerb"].values == ("raised", "lowered", "flush", "no")


def test_yaml_booleans_are_coerced_to_osm_values(schema):
    overrides = yaml.safe_load(
        "criteria:\n"
        "  sidewalks.lit:\n"
        "    values: [yes, no, limited]\n"
        "    reason: test\n"
    )
    crit = _by_id(merge_criteria(schema, overrides))["sidewalks.lit"]
    assert crit.values == ("yes", "no", "limited")


def test_disable_whole_feature(schema):
    overrides = {"features": {"roadways": {"enabled": False, "reason": "géré ailleurs"}}}
    criteria = merge_criteria(schema, overrides)
    roadways = [c for c in criteria if c.feature == "roadways"]
    assert roadways and all(not c.enabled for c in roadways)
    assert all(c.reason == "géré ailleurs" for c in roadways)


def test_add_local_criterion(schema):
    overrides = {
        "add": [{
            "id": "local.crossings.continuous",
            "feature": "crossings",
            "keys": ["crossing:continuous"],
            "elements": ["way"],
            "tier": "silver",
            "values": [True, False],
            "reason": "traversées continues fréquentes à Bruxelles",
        }],
    }
    crit = _by_id(merge_criteria(schema, overrides))["local.crossings.continuous"]
    assert crit.origin == "local"
    assert crit.values == ("yes", "no")
    assert crit.levels["silver"]["values"] == ["yes", "no"]


@pytest.mark.parametrize("overrides, message", [
    ({"criteria": {"sidewalks.nope": {"tier": "gold", "reason": "x"}}}, "n'existe pas"),
    ({"criteria": {"sidewalks.lit": {"tier": "gold"}}}, "reason"),
    ({"criteria": {"sidewalks.lit": {"tier": "platinum", "reason": "x"}}}, "invalide"),
    ({"criteria": {"sidewalks.lit": {"tierr": "gold", "reason": "x"}}}, "inconnu"),
    ({"criteria": {"sidewalks.lit": {"enabled": "no", "reason": "x"}}}, "booléen"),
    ({"features": {"ramps": {"enabled": False, "reason": "x"}}}, "inconnue"),
    ({"add": [{"id": "sidewalks.lit", "feature": "f", "keys": ["k"], "tier": "gold", "reason": "x"}]}, "existe déjà"),
    ({"add": [{"id": "local.x", "feature": "f", "tier": "gold", "reason": "x"}]}, "manquant"),
    ({"unexpected": {}}, "inconnu"),
])
def test_invalid_overrides(schema, overrides, message):
    with pytest.raises(PwgConfigError, match=message):
        merge_criteria(schema, overrides)


def test_up_to_tier(schema):
    criteria = merge_criteria(schema)
    bronze = {c.id for c in up_to_tier(criteria, "bronze")}
    assert bronze == {
        "crossings.crossing:markings",
        "crossings.crossing:signals",
        "islands.surface",
        "roadways.sidewalk:(left|right|both)",
    }
    assert len(up_to_tier(criteria, "diamond")) == len(criteria)
    with pytest.raises(PwgConfigError):
        up_to_tier(criteria, "platinum")


def test_load_criteria_from_files(tmp_path, schema):
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(dump_yaml(schema), encoding="utf-8")
    overrides_path = tmp_path / "overrides.yaml"
    overrides_path.write_text(
        "criteria:\n  roadways.maxspeed:\n    enabled: false\n    reason: test\n",
        encoding="utf-8",
    )
    active = load_criteria(schema_path, overrides_path)
    everything = load_criteria(schema_path, overrides_path, include_disabled=True)
    assert len(everything) == len(active) + 1
    assert "roadways.maxspeed" not in {c.id for c in active}
    assert len(load_criteria(schema_path, tmp_path / "absent.yaml")) == len(everything)


def test_missing_schema_file_is_explicit(tmp_path):
    with pytest.raises(PwgConfigError, match="pwg_schema_fetch"):
        load_criteria(tmp_path / "absent.yaml")


def test_repository_overrides_are_valid(schema):
    pwg_dir = Path(__file__).resolve().parent.parent / "pwg"
    overrides = yaml.safe_load((pwg_dir / "overrides.yaml").read_text(encoding="utf-8")) or {}
    repo_schema = pwg_dir / "schema.yaml"
    if repo_schema.exists():
        schema = yaml.safe_load(repo_schema.read_text(encoding="utf-8"))
    merge_criteria(schema, overrides)
