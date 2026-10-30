import json
import math

from shapely.geometry import Point
from shapely.strtree import STRtree

from detect_tactile_paving_issues import (
    _classify,
    _is_footway_crossing,
    _match_crossing_way,
    detect_tactile_paving_issues,
)

LAT0 = 50.85
LON0 = 4.35

_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def _xy(x_m: float, y_m: float) -> list[float]:
    return [LON0 + x_m / _M_PER_DEG_LON, LAT0 + y_m / _M_PER_DEG_LAT]


def _write_geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _crossing_feature(x_m, y_m, tactile_paving, fid):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": {"highway": "crossing", "tactile_paving": tactile_paving, "@id": fid},
    }


def _crossing_way_feature(x0, y0, xc, yc, x1, y1, fid):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [_xy(x0, y0), _xy(xc, yc), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "crossing", "@id": fid},
    }


def _crossing_way_2pt_feature(x0, y0, x1, y1, fid):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [_xy(x0, y0), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "crossing", "@id": fid},
    }


def _sidewalk_way_feature(x0, y0, x1, y1, fid):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [_xy(x0, y0), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "sidewalk", "@id": fid},
    }


def _kerb_feature(x_m, y_m, tactile_paving, fid):
    props = {"barrier": "kerb", "@id": fid}
    if tactile_paving is not None:
        props["tactile_paving"] = tactile_paving
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": props,
    }


def test_classify_yes_coherent_when_both_kerbs_yes():
    assert _classify("yes", "yes", "yes") is None


def test_classify_yes_flagged_when_one_kerb_no():
    assert _classify("yes", "yes", "no") == "value_mismatch"


def test_classify_no_coherent_when_both_kerbs_no():
    assert _classify("no", "no", "no") is None


def test_classify_incorrect_coherent_when_kerbs_are_a_mixed_pair():
    assert _classify("incorrect", "yes", "no") is None
    assert _classify("incorrect", "no", "yes") is None


def test_classify_incorrect_flagged_when_kerbs_not_mixed():
    assert _classify("incorrect", "yes", "yes") == "incorrect_not_mixed"
    assert _classify("incorrect", "no", "no") == "incorrect_not_mixed"


def test_classify_missing_kerb_is_a_reason_code_but_not_flagged_by_caller():
    assert _classify("yes", "yes", None) == "kerb_missing"
    assert _classify("incorrect", None, None) == "kerb_missing"


def test_classify_untagged_kerb_is_a_reason_code_but_not_flagged_by_caller():
    assert _classify("no", "no", "") == "kerb_untagged"


def test_coherent_yes_crossing_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
        _kerb_feature(3, 0, "yes", fid=202),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["coherent"] == 1
    assert stats["flagged"] == 0


def test_no_crossing_with_mismatched_kerb_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=2),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=102),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no",  fid=203),
        _kerb_feature(3, 0, "yes", fid=204),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 1
    assert stats["value_mismatch"] == 1

    out = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())
    props = out["features"][0]["properties"]
    assert props["osm_id"] == 2
    assert props["reason"] == "value_mismatch"
    assert props["kerb1_tp"] == "no"
    assert props["kerb2_tp"] == "yes"


def test_incorrect_crossing_with_mixed_kerbs_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=3),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=103),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=205),
        _kerb_feature(3, 0, "no",  fid=206),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["coherent"] == 1
    assert stats["flagged"] == 0


def test_incorrect_crossing_with_both_kerbs_yes_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=4),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=104),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=207),
        _kerb_feature(3, 0, "yes", fid=208),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 1
    assert stats["incorrect_not_mixed"] == 1


def test_missing_kerb_at_one_extremity_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=5),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=105),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=209),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["kerb_missing"] == 1

    out = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())
    assert all(f["properties"].get("osm_id", 0) != 5 for f in out["features"])


def test_kerb_without_tactile_paving_tag_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=6),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=106),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no", fid=210),
        _kerb_feature(3, 0, None,  fid=211),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["kerb_untagged"] == 1


def test_out_of_scope_tactile_paving_value_is_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "contrasted", fid=7),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=107),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no",  fid=212),
        _kerb_feature(3, 0, "yes", fid=213),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 0
    assert stats["flagged"] == 0


def test_crossing_without_nearby_crossing_way_is_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=8),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(197, 200, 200, 200, 203, 200, fid=108),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=214),
        _kerb_feature(3, 0, "yes", fid=215),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["no_crossing_way_found"] == 1
    assert stats["flagged"] == 0


def test_match_crossing_way_ignores_a_nearby_but_unrelated_way():
    real_way    = [(-3, 0), (0, 0), (3, 0)]
    distractor  = [(-10, 0.3), (10, 0.3)]

    vertex_points, vertex_way_idx = [], []
    for w_idx, coords in enumerate([real_way, distractor]):
        for c in coords:
            vertex_points.append(Point(c))
            vertex_way_idx.append(w_idx)
    tree = STRtree(vertex_points)

    way_idx, ambiguous = _match_crossing_way(
        Point(0, 0), tree, vertex_points, vertex_way_idx, tol_m=1.5,
    )
    assert way_idx == 0
    assert ambiguous is False


def test_match_crossing_way_finds_nothing_when_only_the_distractor_is_close():
    distractor = [(-10, 0.3), (10, 0.3)]

    vertex_points = [Point(c) for c in distractor]
    vertex_way_idx = [0, 0]
    tree = STRtree(vertex_points)

    way_idx, ambiguous = _match_crossing_way(
        Point(0, 0), tree, vertex_points, vertex_way_idx, tol_m=1.5,
    )
    assert way_idx is None
    assert ambiguous is False


def test_match_crossing_way_flags_ambiguous_when_two_ways_share_the_vertex():
    way_a = [(-3, 0), (0, 0)]
    way_b = [(0, 0), (3, 0)]

    vertex_points, vertex_way_idx = [], []
    for w_idx, coords in enumerate([way_a, way_b]):
        for c in coords:
            vertex_points.append(Point(c))
            vertex_way_idx.append(w_idx)
    tree = STRtree(vertex_points)

    way_idx, ambiguous = _match_crossing_way(
        Point(0, 0), tree, vertex_points, vertex_way_idx, tol_m=1.5,
    )
    assert way_idx in (0, 1)
    assert ambiguous is True


def test_nearby_unrelated_way_does_not_produce_a_false_positive_end_to_end(
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=9),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_2pt_feature(-10, 0.3, 10, 0.3, fid=109),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-10, 0.3, "yes", fid=216),
        _kerb_feature(10, 0.3, "yes", fid=217),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["no_crossing_way_found"] == 1


def test_ambiguous_way_match_is_skipped_not_flagged_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=10),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_2pt_feature(-3, 0, 0, 0, fid=110),
        _crossing_way_2pt_feature(0, 0, 3, 0, fid=111),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=218),
        _kerb_feature(3, 0, "yes", fid=219),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["ambiguous_way_match"] == 1


def test_is_footway_crossing():
    assert _is_footway_crossing({"highway": "footway", "footway": "crossing"}) is True
    assert _is_footway_crossing({"highway": "footway", "footway": "sidewalk"}) is False
    assert _is_footway_crossing({"highway": "footway", "footway": ""}) is False
    assert _is_footway_crossing({"highway": "path", "footway": "crossing"}) is False
    assert _is_footway_crossing({}) is False


def test_sidewalk_way_sharing_the_crossing_nodes_vertex_is_never_used(
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=11),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _sidewalk_way_feature(0, 0, 10, 5, fid=112),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no", fid=220),
        _kerb_feature(3, 0, "no", fid=221),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["no_crossing_way_found"] == 1


def test_a_different_nearby_crossing_does_not_hijack_the_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=12),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _sidewalk_way_feature(0, 0, -8, 4, fid=113),
        _crossing_way_2pt_feature(1.2, -3, 1.2, 3, fid=114),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(1.2, -3, "no", fid=222),
        _kerb_feature(1.2, 3, "no", fid=223),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["no_crossing_way_found"] == 1


def test_kerb_shared_with_attached_sidewalk_is_still_checked_both_sides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
        _sidewalk_way_feature(-3, 0, -3, -5, fid=102),
        _sidewalk_way_feature(3, 0, 3, 5, fid=103),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
        _kerb_feature(3, 0, "yes", fid=202),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["coherent"] == 1
    assert stats["kerb_missing"] == 0
    assert stats["flagged"] == 0


def test_kerb_shared_with_sidewalk_still_flags_a_real_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
        _sidewalk_way_feature(-3, 0, -3, -5, fid=102),
        _sidewalk_way_feature(3, 0, 3, 5, fid=103),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
        _kerb_feature(3, 0, "no", fid=202),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["value_mismatch"] == 1
    assert stats["flagged"] == 1


def test_kerb_shared_with_sidewalk_still_detects_missing_kerb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
        _sidewalk_way_feature(-3, 0, -3, -5, fid=102),
        _sidewalk_way_feature(3, 0, 3, 5, fid=103),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["kerb_missing"] == 1
    assert stats["coherent"] == 0
    assert stats["flagged"] == 0


def test_half_mapped_crossing_real_production_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [4.351743, 50.8440884]},
        "properties": {"highway": "crossing", "tactile_paving": "no", "@id": 4470463383},
    }])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [
            [4.3517455, 50.8441001], [4.351743, 50.8440884],
        ]},
        "properties": {"highway": "footway", "footway": "crossing", "@id": 875635271},
    }])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [4.3517455, 50.8441001]},
        "properties": {"barrier": "kerb", "kerb": "lowered", "tactile_paving": "no", "@id": 8150193317},
    }])

    stats = detect_tactile_paving_issues()
    assert stats["half_mapped_sides"] == 1
    assert stats["coherent"] == 1
    assert stats["kerb_missing"] == 0
    assert stats["flagged"] == 0


def test_half_mapped_crossing_still_flags_a_real_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_2pt_feature(-3, 0, 0, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no", fid=201),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["half_mapped_sides"] == 1
    assert stats["value_mismatch"] == 1
    assert stats["flagged"] == 1


def test_half_mapped_crossing_still_detects_a_real_missing_kerb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_2pt_feature(-3, 0, 0, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [])

    stats = detect_tactile_paving_issues()
    assert stats["half_mapped_sides"] == 1
    assert stats["kerb_missing"] == 1
    assert stats["coherent"] == 0
    assert stats["flagged"] == 0


def test_half_mapped_crossing_with_incorrect_tag_is_skipped_not_guessed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_2pt_feature(-3, 0, 0, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["half_mapped_incorrect_skipped"] == 1
    assert stats["half_mapped_sides"] == 0
    assert stats["coherent"] == 0
    assert stats["flagged"] == 0


def test_fully_mapped_crossing_is_unaffected_by_the_half_mapped_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
        _kerb_feature(3, 0, "yes", fid=202),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["half_mapped_sides"] == 0
    assert stats["coherent"] == 1
