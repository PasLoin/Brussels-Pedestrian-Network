import json
import math

import geopandas as gpd
import pytest
from shapely.geometry import Point

from detect_tactile_paving_issues import (
    _IN_SCOPE_VALUES,
    _crossing_nodes_from,
    detect_tactile_paving_issues,
)

LAT0 = 50.85
LON0 = 4.35
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def _xy(x_m, y_m):
    return [LON0 + x_m / _M_PER_DEG_LON, LAT0 + y_m / _M_PER_DEG_LAT]


def _write(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _crossing(x, y, tp, fid):
    props = {"highway": "crossing", "@id": fid}
    if tp is not None:
        props["tactile_paving"] = tp
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": _xy(x, y)},
            "properties": props}


def _line(coords, fid, **tags):
    return {"type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [_xy(x, y) for x, y in coords]},
            "properties": {**tags, "@id": fid}}


def _cw(coords, fid):
    return _line(coords, fid, highway="footway", footway="crossing")


def _kerb(x, y, tp, fid):
    props = {"barrier": "kerb", "@id": fid}
    if tp is not None:
        props["tactile_paving"] = tp
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": _xy(x, y)},
            "properties": props}


def _kerb_issues(tmp_path, kind=None):
    feats = json.loads((tmp_path / "kerb_issues.geojson").read_text())["features"]
    props = [f["properties"] for f in feats if f["properties"].get("type")]
    if kind is not None:
        props = [p for p in props if p["type"] == kind]
    return props


def _tactile_issues(tmp_path):
    feats = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())["features"]
    return [f["properties"] for f in feats if f["properties"].get("osm_id")]


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def build(highways, footways, kerbs):
        _write(tmp_path / "highways.geojson", highways)
        _write(tmp_path / "sidewalk_footways_raw.geojson", footways)
        _write(tmp_path / "kerbs_raw.geojson", kerbs)
        return tmp_path

    return build


def test_crossing_nodes_from_keeps_every_value_by_default():
    gdf = gpd.GeoDataFrame(
        [
            {"geometry": Point(_xy(0, 0)), "highway": "crossing", "tactile_paving": "yes", "@id": 1},
            {"geometry": Point(_xy(1, 0)), "highway": "crossing", "tactile_paving": None, "@id": 2},
            {"geometry": Point(_xy(2, 0)), "highway": "crossing", "tactile_paving": "Contrasted", "@id": 3},
            {"geometry": Point(_xy(3, 0)), "highway": "elevator", "tactile_paving": "yes", "@id": 4},
        ],
        crs="EPSG:4326",
    )
    all_nodes = _crossing_nodes_from(gdf)
    assert sorted(all_nodes["osm_id"]) == [1, 2, 3]
    assert dict(zip(all_nodes["osm_id"], all_nodes["tactile_paving"])) == {
        1: "yes", 2: "", 3: "contrasted",
    }
    in_scope = _crossing_nodes_from(gdf, _IN_SCOPE_VALUES)
    assert list(in_scope["osm_id"]) == [1]


def test_crossing_nodes_from_tolerates_missing_tactile_paving_column():
    gdf = gpd.GeoDataFrame(
        [{"geometry": Point(_xy(0, 0)), "highway": "crossing", "@id": 7}],
        crs="EPSG:4326",
    )
    nodes = _crossing_nodes_from(gdf)
    assert list(nodes["osm_id"]) == [7]
    assert list(nodes["tactile_paving"]) == [""]


def test_issue_60_untagged_crossing_reports_both_missing_kerbs(scene):
    path = scene(
        [_crossing(0, 0, None, 8071884275)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [],
    )
    stats = detect_tactile_paving_issues()
    issues = _kerb_issues(path)
    assert len(issues) == 2
    assert {p["type"] for p in issues} == {"kerb_missing"}
    assert {p["crossing_osm_id"] for p in issues} == {8071884275}
    assert {p["way_osm_id"] for p in issues} == {101}
    assert stats["crossings_in_scope"] == 0
    assert stats["kerb_missing"] == 0
    assert stats["kerb_missing_points"] == 2
    assert stats["kerb_missing_crossings"] == 1
    assert stats["kerb_check_crossings"] == 1
    assert stats["kerb_check_resolved"] == 1
    assert stats["flagged"] == 0


def test_untagged_crossing_reports_only_the_missing_side(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, "yes", 201)],
    )
    stats = detect_tactile_paving_issues()
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["type"] == "kerb_missing"
    assert stats["kerb_missing_points"] == 1


def test_untagged_crossing_with_untagged_kerbs_reports_nothing(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, None, 201), _kerb(3, 0, None, 202)],
    )
    stats = detect_tactile_paving_issues()
    assert _kerb_issues(path) == []
    assert stats["kerb_untagged"] == 0
    assert stats["kerb_untagged_points"] == 0
    assert stats["kerb_missing_points"] == 0


def test_untagged_crossing_missing_and_untagged_kerb_reports_only_missing(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, None, 201)],
    )
    detect_tactile_paving_issues()
    assert len(_kerb_issues(path, "kerb_missing")) == 1
    assert _kerb_issues(path, "kerb_untagged") == []


@pytest.mark.parametrize("tp", ["contrasted", "primitive", "partial"])
def test_out_of_scope_value_still_reports_missing_kerb(scene, tp):
    path = scene(
        [_crossing(0, 0, tp, 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, "yes", 201)],
    )
    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 0
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["type"] == "kerb_missing"


@pytest.mark.parametrize("tp", ["yes", "no"])
def test_in_scope_crossing_missing_kerb_unchanged(scene, tp):
    path = scene(
        [_crossing(0, 0, tp, 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, tp, 201)],
    )
    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["kerb_missing"] == 1
    assert stats["kerb_missing_points"] == 1
    assert stats["coherent"] == 0
    assert stats["flagged"] == 0
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["crossing_osm_id"] == 1


def test_in_scope_crossing_untagged_kerb_unchanged(scene):
    path = scene(
        [_crossing(0, 0, "yes", 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, "yes", 201), _kerb(3, 0, None, 202)],
    )
    stats = detect_tactile_paving_issues()
    assert stats["kerb_untagged"] == 1
    assert stats["kerb_untagged_points"] == 1
    assert stats["kerb_missing_points"] == 0
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["type"] == "kerb_untagged"
    assert issues[0]["kerb_osm_id"] == 202


def test_in_scope_crossing_missing_plus_untagged_still_hides_untagged(scene):
    path = scene(
        [_crossing(0, 0, "no", 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [_kerb(-3, 0, None, 201)],
    )
    stats = detect_tactile_paving_issues()
    assert stats["kerb_missing"] == 1
    assert stats["kerb_untagged"] == 0
    assert len(_kerb_issues(path, "kerb_missing")) == 1
    assert _kerb_issues(path, "kerb_untagged") == []


def test_two_crossing_nodes_on_one_way_do_not_duplicate_points(scene):
    path = scene(
        [_crossing(-1, 0, "yes", 1), _crossing(1, 0, None, 2)],
        [_cw([(-4, 0), (-1, 0), (1, 0), (4, 0)], 101)],
        [],
    )
    stats = detect_tactile_paving_issues()
    issues = _kerb_issues(path)
    assert len(issues) == 2
    assert stats["kerb_missing_points"] == 2
    assert stats["kerb_missing_crossings"] == 2
    assert stats["kerb_missing"] == 1


def test_adjacent_separate_crossings_keep_one_point_per_way(scene):
    path = scene(
        [_crossing(-3, 0, None, 1), _crossing(3, 0, None, 2)],
        [
            _cw([(-6, 0), (-3, 0), (0, 0)], 101),
            _cw([(0, 0), (3, 0), (6, 0)], 102),
            _line([(0, 0), (0, 10)], 501, highway="footway", footway="sidewalk"),
        ],
        [_kerb(-6, 0, "yes", 201), _kerb(6, 0, "yes", 202)],
    )
    stats = detect_tactile_paving_issues()
    issues = _kerb_issues(path)
    assert len(issues) == 2
    assert {p["way_osm_id"] for p in issues} == {101, 102}
    assert stats["kerb_missing_points"] == 2


def test_contiguous_pair_with_untagged_partner_reports_far_kerb_once(scene):
    path = scene(
        [_crossing(-3, 0, "yes", 1), _crossing(3, 0, None, 2)],
        [
            _cw([(-6, 0), (-3, 0), (0, 0)], 101),
            _cw([(0, 0), (3, 0), (6, 0)], 102),
        ],
        [_kerb(-6, 0, "yes", 201)],
    )
    stats = detect_tactile_paving_issues()
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert {issues[0]["way_osm_id"], issues[0]["partner_way_osm_id"]} == {101, 102}
    assert stats["kerb_missing_points"] == 1
    assert stats["kerb_missing_crossings"] == 2


def test_contiguous_pair_with_tp_conflict_still_reports_missing_kerb(scene):
    path = scene(
        [_crossing(-3, 0, "yes", 1), _crossing(3, 0, "no", 2)],
        [
            _cw([(-6, 0), (-3, 0), (0, 0)], 101),
            _cw([(0, 0), (3, 0), (6, 0)], 102),
        ],
        [_kerb(-6, 0, "yes", 201)],
    )
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_tp_conflict"] == 2
    assert stats["kerb_missing"] == 0
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["type"] == "kerb_missing"
    assert stats["flagged"] == 0


def test_half_mapped_incorrect_crossing_still_reports_missing_kerb(scene):
    path = scene(
        [_crossing(0, 0, "incorrect", 1)],
        [_cw([(-3, 0), (0, 0)], 101)],
        [],
    )
    stats = detect_tactile_paving_issues()
    assert stats["half_mapped_incorrect_skipped"] == 1
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["type"] == "kerb_missing"


def test_half_mapped_untagged_crossing_checks_the_single_side(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_cw([(-3, 0), (0, 0)], 101)],
        [],
    )
    stats = detect_tactile_paving_issues()
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert stats["kerb_missing_points"] == 1


def test_untagged_crossing_without_crossing_way_is_skipped(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_line([(-3, 0), (0, 0), (3, 0)], 101, highway="footway", footway="sidewalk")],
        [],
    )
    stats = detect_tactile_paving_issues()
    assert _kerb_issues(path) == []
    assert stats["kerb_check_crossings"] == 1
    assert stats["kerb_check_skipped"] == 1
    assert stats["kerb_check_resolved"] == 0


def test_untagged_crossing_with_ambiguous_way_is_skipped(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_cw([(-3, 0), (0, 0)], 101), _cw([(0, 0), (3, 0)], 102)],
        [],
    )
    stats = detect_tactile_paving_issues()
    assert _kerb_issues(path) == []
    assert stats["kerb_check_skipped"] == 1


def test_untagged_crossing_does_not_change_coherence_results(scene):
    path = scene(
        [_crossing(0, 0, "yes", 1), _crossing(20, 0, None, 2)],
        [
            _cw([(-3, 0), (0, 0), (3, 0)], 101),
            _cw([(17, 0), (20, 0), (23, 0)], 102),
        ],
        [
            _kerb(-3, 0, "yes", 201), _kerb(3, 0, "no", 202),
            _kerb(17, 0, None, 203), _kerb(23, 0, "no", 204),
        ],
    )
    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["value_mismatch"] == 1
    assert stats["flagged"] == 1
    assert [p["osm_id"] for p in _tactile_issues(path)] == [1]
    assert _kerb_issues(path) == []


def test_no_crossing_at_all_writes_empty_outputs(scene):
    path = scene([], [_cw([(-3, 0), (3, 0)], 101)], [])
    stats = detect_tactile_paving_issues()
    assert stats == {"crossings_in_scope": 0, "flagged": 0}
    assert _kerb_issues(path) == []
    assert _tactile_issues(path) == []


def test_only_untagged_crossings_still_writes_coherence_layer(scene):
    path = scene(
        [_crossing(0, 0, None, 1)],
        [_cw([(-3, 0), (0, 0), (3, 0)], 101)],
        [],
    )
    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 0
    assert stats["flagged"] == 0
    assert _tactile_issues(path) == []
    assert (path / "tactile_paving_issues.geojson").exists()
