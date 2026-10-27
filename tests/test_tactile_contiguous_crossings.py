import json
import math

import pytest

from detect_tactile_paving_issues import detect_tactile_paving_issues

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


def _kerb_issues(tmp_path):
    feats = json.loads((tmp_path / "kerb_issues.geojson").read_text())["features"]
    return [f["properties"] for f in feats if f["properties"].get("type")]


def _tactile_issues(tmp_path):
    feats = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())["features"]
    return [f["properties"] for f in feats if f["properties"].get("osm_id")]


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def build(tp1="yes", tp2="yes", kerb_left="yes", kerb_right="yes",
              extra_footways=(), extra_highways=(), extra_kerbs=(), partner_has_node=True):
        highways = [_crossing(-3, 0, tp1, 1)]
        if partner_has_node:
            highways.append(_crossing(3, 0, tp2, 2))
        _write(tmp_path / "highways.geojson", highways + list(extra_highways))
        _write(tmp_path / "sidewalk_footways_raw.geojson", [
            _cw([(-6, 0), (-3, 0), (0, 0)], 101),
            _cw([(0, 0), (3, 0), (6, 0)], 102),
            *extra_footways,
        ])
        kerbs = list(extra_kerbs)
        if kerb_left is not False:
            kerbs.append(_kerb(-6, 0, kerb_left, 201))
        if kerb_right is not False:
            kerbs.append(_kerb(6, 0, kerb_right, 202))
        _write(tmp_path / "kerbs_raw.geojson", kerbs)
        return tmp_path

    return build


def test_issue_55_pair_is_coherent(pair):
    path = pair()
    stats = detect_tactile_paving_issues()
    assert stats["coherent"] == 2
    assert stats["kerb_missing"] == 0
    assert stats["contiguous_pair_merged"] == 2
    assert _kerb_issues(path) == []
    assert _tactile_issues(path) == []


def test_pair_reveals_mismatch_on_the_far_kerb(pair):
    path = pair(kerb_right="no")
    stats = detect_tactile_paving_issues()
    assert stats["value_mismatch"] == 2
    flagged = {p["osm_id"]: p for p in _tactile_issues(path)}
    assert flagged[1]["partner_way_osm_id"] == 102
    assert flagged[2]["partner_way_osm_id"] == 101
    assert flagged[1]["sides_checked"] == 2


def test_pair_missing_far_kerb_reported_once(pair):
    path = pair(kerb_right=False)
    stats = detect_tactile_paving_issues()
    assert stats["kerb_missing"] == 2
    assert stats["kerb_missing_points"] == 1
    issues = _kerb_issues(path)
    assert len(issues) == 1
    assert issues[0]["type"] == "kerb_missing"
    assert {issues[0]["way_osm_id"], issues[0]["partner_way_osm_id"]} == {101, 102}


def test_partner_without_crossing_node_is_merged(pair):
    path = pair(partner_has_node=False)
    stats = detect_tactile_paving_issues()
    assert stats["coherent"] == 1
    assert stats["contiguous_pair_merged"] == 1
    assert _kerb_issues(path) == []


def test_conflicting_tactile_paving_is_skipped(pair):
    path = pair(tp1="yes", tp2="no")
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_tp_conflict"] == 2
    assert stats["contiguous_pair_merged"] == 0
    assert stats["flagged"] == 0
    assert _kerb_issues(path) == []


def test_partner_with_out_of_scope_value_is_a_conflict(pair):
    pair(tp2="contrasted")
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_tp_conflict"] == 1
    assert stats["coherent"] == 0


def test_partner_without_tactile_paving_is_not_a_conflict(pair):
    pair(tp2=None)
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_tp_conflict"] == 0
    assert stats["coherent"] == 1


def test_junction_with_kerb_keeps_two_separate_crossings(pair):
    path = pair(extra_kerbs=[_kerb(0, 0, "yes", 299)])
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_merged"] == 0
    assert stats["coherent"] == 2
    assert _kerb_issues(path) == []


def test_junction_touching_a_sidewalk_is_not_merged(pair):
    pair(extra_footways=[_line([(0, 0), (0, 10)], 501, highway="footway", footway="sidewalk")])
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_merged"] == 0
    assert stats["kerb_missing"] == 2
    assert stats["kerb_missing_points"] == 2


def test_junction_touching_a_cycleway_from_highways_is_not_merged(pair):
    pair(extra_highways=[_line([(0, 0), (0, 10)], 601, highway="cycleway")])
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_merged"] == 0
    assert stats["kerb_missing"] == 2


def test_junction_on_a_road_from_other_ways_is_not_merged(pair, tmp_path):
    pair()
    _write(tmp_path / "roads.geojson", [_line([(0, -10), (0, 0), (0, 10)], 701, highway="residential")])
    stats = detect_tactile_paving_issues(other_ways_geojson_paths=("roads.geojson",))
    assert stats["contiguous_pair_merged"] == 0
    assert stats["kerb_missing"] == 2


def test_missing_other_ways_file_is_ignored(pair):
    pair()
    stats = detect_tactile_paving_issues(other_ways_geojson_paths=("absent.geojson",))
    assert stats["contiguous_pair_merged"] == 2


def test_junction_on_a_crossing_node_is_not_merged(pair):
    pair(extra_highways=[_crossing(0, 0, None, 3)])
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_merged"] == 0


def test_chain_of_three_crossings_is_not_merged(pair, tmp_path):
    pair(kerb_right=False)
    _write(tmp_path / "sidewalk_footways_raw.geojson", [
        _cw([(-6, 0), (-3, 0), (0, 0)], 101),
        _cw([(0, 0), (3, 0), (6, 0)], 102),
        _cw([(6, 0), (9, 0)], 103),
    ])
    _write(tmp_path / "kerbs_raw.geojson", [
        _kerb(-6, 0, "yes", 201),
        _kerb(9, 0, "yes", 203),
    ])
    stats = detect_tactile_paving_issues()
    assert stats["contiguous_pair_merged"] == 0
    assert stats["kerb_missing"] == 2
