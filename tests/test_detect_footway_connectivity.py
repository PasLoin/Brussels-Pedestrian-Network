"""Tests for scripts/detect_footway_connectivity.py — way-centric
heuristic for footways that look like unmapped crossings."""

import json
import math

from detect_footway_connectivity import detect_footway_connectivity_candidates

LAT0 = 50.85
LON0 = 4.35

_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def _xy(x_m: float, y_m: float) -> list[float]:
    """Convert local ENU metre offsets (from LON0, LAT0) to [lon, lat]."""
    return [LON0 + x_m / _M_PER_DEG_LON, LAT0 + y_m / _M_PER_DEG_LAT]


def _write_geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _road_feature(coords_m, name="Test Road", highway="residential", fid=1):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [_xy(*c) for c in coords_m]},
        "properties": {"highway": highway, "name": name, "@id": fid},
    }


def _footway_feature(coords_m, footway=None, fid=1):
    props = {"highway": "footway", "@id": fid}
    if footway is not None:
        props["footway"] = footway
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [_xy(*c) for c in coords_m]},
        "properties": props,
    }


def test_diagonal_crossing_flagged_without_parallel_sidewalk(tmp_path):
    """The exact reported case: a diagonal footway crossing a road with
    no footway=crossing tag, whose connected sidewalks are NOT parallel
    to the footway (they're parallel to the road instead). The old
    bearing-based analysis misses this; the connectivity check should not.
    """
    roads_p = tmp_path / "roads.geojson"
    _write_geojson(roads_p, [_road_feature([(-50, 0), (50, 0)])])

    fw_p = tmp_path / "footways.geojson"
    _write_geojson(fw_p, [
        # Diagonal candidate crossing the road roughly at its own midpoint.
        _footway_feature([(-8, 8), (10, -9)], fid=111),
        # Sidewalks parallel to the ROAD (horizontal), not to the footway —
        # each shares an exact vertex with one footway endpoint.
        _footway_feature([(-20, 8), (-8, 8), (5, 8)], footway="sidewalk", fid=201),
        _footway_feature([(-5, -9), (10, -9), (25, -9)], footway="sidewalk", fid=202),
    ])

    stats = detect_footway_connectivity_candidates(str(fw_p), str(roads_p))
    assert stats["flagged"] == 1
    assert stats["sidewalks_same_side"] == 0
    assert stats["no_midway_road_crossing"] == 0


def test_path_not_crossing_any_road_is_not_flagged(tmp_path):
    """Park-path-style false positive: touches a sidewalk at each end but
    never crosses an eligible road — must not be flagged."""
    roads_p = tmp_path / "roads.geojson"
    _write_geojson(roads_p, [_road_feature([(200, 200), (300, 200)])])  # far away

    fw_p = tmp_path / "footways.geojson"
    _write_geojson(fw_p, [
        _footway_feature([(-8, 8), (10, -9)], fid=112),
        _footway_feature([(-20, 8), (-8, 8), (5, 8)], footway="sidewalk", fid=203),
        _footway_feature([(-5, -9), (10, -9), (25, -9)], footway="sidewalk", fid=204),
    ])

    stats = detect_footway_connectivity_candidates(str(fw_p), str(roads_p))
    assert stats["candidates_scanned"] == 1
    assert stats["flagged"] == 0
    assert stats["no_midway_road_crossing"] == 1


def test_footway_touching_same_side_twice_is_not_flagged(tmp_path):
    """A footway that dips across the road and back (both endpoints on
    the same side) must not be treated as a crossing."""
    roads_p = tmp_path / "roads.geojson"
    _write_geojson(roads_p, [_road_feature([(-50, 0), (50, 0)])])

    fw_p = tmp_path / "footways.geojson"
    _write_geojson(fw_p, [
        _footway_feature([(-10, 5), (0, -3), (10, 5)], fid=113),
        # Dummy distant sidewalk so sw_tree isn't None.
        _footway_feature([(200, 200), (210, 200)], footway="sidewalk", fid=205),
    ])

    stats = detect_footway_connectivity_candidates(str(fw_p), str(roads_p))
    assert stats["flagged"] == 0
    assert stats["sidewalks_same_side"] == 1
