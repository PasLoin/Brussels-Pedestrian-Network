import json

import geopandas as gpd
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point, box

from analysis_boundary import (
    clip_lines,
    inside,
    load_analysis_boundary,
    parse_poly,
    touches_area,
)
from detect_missing_crossings import detect_missing_crossings
from detect_tactile_paving_issues import detect_tactile_paving_issues
from sidewalk_gap import detect_sidewalk_gaps

_TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)
_X0, _Y0 = 150000.0, 170000.0

AREA = box(_X0 - 50, _Y0 - 50, _X0 + 100, _Y0 + 50)


def _ll(x, y):
    return list(_TO_WGS.transform(_X0 + x, _Y0 + y))


def _line(coords, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": [_ll(*c) for c in coords]}}


def _point(x, y, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": _ll(x, y)}}


def _write(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return str(path)


def _ring(name, coords):
    return [name] + [f"   {x:.7E}   {y:.7E}" for x, y in coords] + ["END"]


def _poly_text(*rings):
    lines = ["test"]
    for ring in rings:
        lines += ring
    return "\n".join(lines + ["END", ""])


SQUARE = [(4.0, 50.0), (4.1, 50.0), (4.1, 50.1), (4.0, 50.1), (4.0, 50.0)]
HOLE = [(4.04, 50.04), (4.06, 50.04), (4.06, 50.06), (4.04, 50.06), (4.04, 50.04)]
OTHER = [(4.2, 50.0), (4.3, 50.0), (4.3, 50.1), (4.2, 50.1), (4.2, 50.0)]


def test_parse_poly_reads_named_ring_and_scientific_notation():
    area = parse_poly(_poly_text(_ring("Région de Bruxelles-Capitale - Gewest", SQUARE)))
    assert area.covers(Point(4.05, 50.05))
    assert not area.covers(Point(4.15, 50.05))
    assert area.area == pytest.approx(0.01)


def test_parse_poly_subtracts_holes():
    area = parse_poly(_poly_text(_ring("1", SQUARE), _ring("!2", HOLE)))
    assert not area.covers(Point(4.05, 50.05))
    assert area.covers(Point(4.02, 50.02))


def test_parse_poly_keeps_every_outer_ring():
    area = parse_poly(_poly_text(_ring("1", SQUARE), _ring("2", OTHER)))
    assert area.geom_type == "MultiPolygon"
    assert area.covers(Point(4.25, 50.05))


def test_parse_poly_without_outer_ring_raises():
    with pytest.raises(ValueError):
        parse_poly(_poly_text(_ring("!1", HOLE)))


def test_load_analysis_boundary_missing_file_returns_none(tmp_path):
    assert load_analysis_boundary(str(tmp_path / "absent.poly")) is None
    assert load_analysis_boundary(None) is None


def test_load_analysis_boundary_projects_to_lambert(tmp_path):
    ring = [_TO_WGS.transform(x, y) for x, y in AREA.exterior.coords]
    path = tmp_path / "area.poly"
    path.write_text(_poly_text(_ring("1", ring)), encoding="utf-8")
    area = load_analysis_boundary(str(path))
    assert area.covers(Point(_X0, _Y0))
    assert not area.covers(Point(_X0 + 200, _Y0))
    assert area.area == pytest.approx(AREA.area, rel=1e-3)


def test_inside_and_touches_without_area_keep_everything():
    pts = [Point(0, 0), Point(1, 1)]
    assert inside(pts, None).tolist() == [True, True]
    assert touches_area(pts, None).tolist() == [True, True]


def test_inside_counts_points_on_the_edge():
    area = box(0, 0, 10, 10)
    pts = gpd.GeoSeries([Point(5, 5), Point(10, 5), Point(11, 5)])
    assert inside(pts, area).tolist() == [True, True, False]


def test_clip_lines_cuts_explodes_and_drops_point_contacts():
    area = box(0, 0, 100, 100)
    gdf = gpd.GeoDataFrame(
        {"name": ["through", "in_out_in", "outside", "corner"]},
        geometry=[
            LineString([(-50, 50), (150, 50)]),
            LineString([(10, 10), (150, 10), (150, 90), (10, 90)]),
            LineString([(200, 0), (300, 0)]),
            LineString([(100, 150), (100, 100), (150, 100)]),
        ],
        crs="EPSG:31370",
    )
    out = clip_lines(gdf, area)
    assert sorted(out["name"]) == ["in_out_in", "in_out_in", "through"]
    assert out.geometry.geom_type.eq("LineString").all()
    assert sorted(round(g.length) for g in out.geometry) == [90, 90, 100]
    assert out.crs == gdf.crs


def test_clip_lines_without_area_is_identity():
    gdf = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 0)])], crs="EPSG:31370")
    assert clip_lines(gdf, None) is gdf


def _crossing(x, tp, fid):
    return _point(x, 0, {"highway": "crossing", "tactile_paving": tp, "@id": fid})


def _crossing_way(x, fid):
    return _line([(x, -6), (x, 0), (x, 6)],
                 {"highway": "footway", "footway": "crossing", "@id": fid})


def _kerb(x, y, tp, fid):
    return _point(x, y, {"barrier": "kerb", "tactile_paving": tp, "@id": fid})


def _tactile_inputs(tmp_path):
    highways = [_crossing(0, "yes", 1), _crossing(300, "yes", 2), _crossing(400, "no", 3)]
    footways = [_crossing_way(0, 10), _crossing_way(300, 11), _crossing_way(400, 12)]
    kerbs = [
        _kerb(0, -6, "no", 20), _kerb(0, 6, "no", 21),
        _kerb(300, -6, "no", 22), _kerb(300, 6, "no", 23),
    ]
    return (
        _write(tmp_path / "highways.geojson", highways),
        _write(tmp_path / "footways.geojson", footways),
        _write(tmp_path / "kerbs.geojson", kerbs),
    )


def _features(path):
    return [f for f in json.loads(path.read_text())["features"] if f["geometry"]]


def test_tactile_paving_without_boundary_checks_every_crossing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_tactile_paving_issues(*_tactile_inputs(tmp_path))
    flagged = {f["properties"]["osm_id"] for f in _features(tmp_path / "tactile_paving_issues.geojson")}
    kerb_crossings = {f["properties"]["crossing_osm_id"] for f in _features(tmp_path / "kerb_issues.geojson")}
    assert flagged == {1, 2}
    assert kerb_crossings == {3}
    assert stats["crossings_outside_boundary"] == 0
    assert stats["crossings_in_scope"] == 3


def test_tactile_paving_ignores_crossings_outside_boundary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_tactile_paving_issues(*_tactile_inputs(tmp_path), boundary=AREA)
    flagged = {f["properties"]["osm_id"] for f in _features(tmp_path / "tactile_paving_issues.geojson")}
    assert flagged == {1}
    assert _features(tmp_path / "kerb_issues.geojson") == []
    assert stats["crossings_outside_boundary"] == 2
    assert stats["crossings_in_scope"] == 1
    assert stats["kerb_check_crossings"] == 1


def test_tactile_paving_with_every_crossing_outside_writes_empty_layers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_tactile_paving_issues(
        *_tactile_inputs(tmp_path), boundary=box(_X0 + 1000, _Y0, _X0 + 1100, _Y0 + 100),
    )
    assert stats["crossings_outside_boundary"] == 3
    assert stats["flagged"] == 0
    assert _features(tmp_path / "tactile_paving_issues.geojson") == []
    assert _features(tmp_path / "kerb_issues.geojson") == []


def _border_road_inputs(tmp_path):
    road = _line([(-40, 0), (450, 0)], {"highway": "residential", "name": "Rue Frontière"})
    sidewalks = [
        _line([(-40, 6), (450, 6)], {"highway": "footway", "footway": "sidewalk", "@id": 30}),
        _line([(-40, -6), (450, -6)], {"highway": "footway", "footway": "sidewalk", "@id": 31}),
    ]
    nodes = [
        _point(20, 0, {"highway": "crossing", "@id": 40}),
        _point(300, 0, {"highway": "crossing", "@id": 41}),
    ]
    return (
        _write(tmp_path / "highways.geojson", nodes),
        _write(tmp_path / "footways.geojson", sidewalks),
        _write(tmp_path / "roads.geojson", [road]),
    )


def test_missing_crossings_flags_orphan_nodes_without_boundary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_missing_crossings(*_border_road_inputs(tmp_path))
    flagged = {f["properties"]["osm_id"] for f in _features(tmp_path / "missing_crossings.geojson")}
    assert flagged == {40, 41}
    assert stats["crossings_outside_boundary"] == 0


def test_missing_crossings_skips_nodes_kept_only_by_a_border_road(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_missing_crossings(*_border_road_inputs(tmp_path), boundary=AREA)
    flagged = {f["properties"]["osm_id"] for f in _features(tmp_path / "missing_crossings.geojson")}
    assert flagged == {40}
    assert stats["crossings_outside_boundary"] == 1
    assert stats["crossing_nodes_found"] == 1
    assert stats["missing_crossing_way"] == 1


def test_missing_crossings_with_every_node_outside(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_missing_crossings(
        *_border_road_inputs(tmp_path), boundary=box(_X0 + 1000, _Y0, _X0 + 1100, _Y0 + 100),
    )
    assert stats["crossings_outside_boundary"] == 2
    assert stats["crossing_nodes_found"] == 0
    assert _features(tmp_path / "missing_crossings.geojson") == []


def _truncated_sidewalk_inputs(tmp_path):
    roads = [
        _line([(0, 0), (300, 0)], {"highway": "residential", "name": "Rue Coupée"}),
        _line([(600, 0), (700, 0)], {"highway": "residential", "name": "Rue Dehors",
                                     "sidewalk:both": "separate"}),
    ]
    footways = [
        _line([(0, 6), (300, 6)], {"highway": "footway", "footway": "sidewalk", "@id": 50}),
        _line([(0, -6), (100, -6)], {"highway": "footway", "footway": "sidewalk", "@id": 51}),
        _line([(600, 6), (700, 6)], {"highway": "footway", "footway": "sidewalk", "@id": 52}),
    ]
    return (
        _write(tmp_path / "roads.geojson", roads),
        _write(tmp_path / "footways.geojson", footways),
    )


def _lambert_lengths(path):
    gdf = gpd.read_file(path)
    gdf = gdf[gdf.geometry.notna()].to_crs("EPSG:31370")
    return sorted(round(g.length) for g in gdf.geometry)


def test_sidewalk_gap_without_boundary_flags_truncated_road(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_sidewalk_gaps(*_truncated_sidewalk_inputs(tmp_path))
    assert stats["one_side_gap"] == 2
    assert stats["roads_outside_boundary"] == 0
    assert _lambert_lengths(tmp_path / "sidewalk_gaps.geojson") == [100, 300]


def test_sidewalk_gap_evaluates_only_the_part_inside_boundary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = detect_sidewalk_gaps(*_truncated_sidewalk_inputs(tmp_path), boundary=AREA)
    assert stats["roads_outside_boundary"] == 1
    assert stats["roads_analysed"] == 1
    assert stats["one_side_gap"] == 0
    assert stats["both_sides"] == 1
    assert _lambert_lengths(tmp_path / "sidewalk_gaps.geojson") == []
    assert _lambert_lengths(tmp_path / "sidewalk_separate_candidates.geojson") == [100]
