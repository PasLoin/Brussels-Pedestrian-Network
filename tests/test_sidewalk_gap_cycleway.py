import json

import geopandas as gpd
import pytest
from pyproj import Transformer
from shapely.geometry import LineString

from sidewalk_gap import _foot_cycleway_mask, _load_foot_cycleways, detect_sidewalk_gaps

_TO_WGS84 = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)

_X0, _Y0 = 150000.0, 170000.0


def _wgs84_coords(coords):
    return [list(_TO_WGS84.transform(x, y)) for x, y in coords]


def _write_geojson(path, features):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "LineString", "coordinates": _wgs84_coords(coords)},
            }
            for coords, props in features
        ],
    }
    path.write_text(json.dumps(fc))
    return str(path)


def _hline(dy, length=100.0):
    return [(_X0, _Y0 + dy), (_X0 + length, _Y0 + dy)]


@pytest.mark.parametrize("highway, foot, kept", [
    ("cycleway", "yes", True),
    ("cycleway", "designated", True),
    ("cycleway", "permissive", True),
    ("cycleway", "YES", True),
    ("cycleway", "no", False),
    ("cycleway", "", False),
    ("cycleway", None, False),
    ("footway", "yes", False),
    ("path", "designated", False),
])
def test_foot_cycleway_mask(highway, foot, kept):
    gdf = gpd.GeoDataFrame(
        [{"highway": highway, "foot": foot, "geometry": LineString(_hline(0))}],
        crs="EPSG:31370",
    )
    assert bool(_foot_cycleway_mask(gdf).iloc[0]) is kept


def test_foot_cycleway_mask_missing_foot_column():
    gdf = gpd.GeoDataFrame(
        [{"highway": "cycleway", "geometry": LineString(_hline(0))}],
        crs="EPSG:31370",
    )
    assert not _foot_cycleway_mask(gdf).any()


def test_load_foot_cycleways_missing_file(tmp_path):
    geoms, stats = _load_foot_cycleways(str(tmp_path / "absent.geojson"))
    assert geoms == []
    assert stats == {"raw": 0, "kept": 0}


def test_load_foot_cycleways_none():
    assert _load_foot_cycleways(None) == ([], {"raw": 0, "kept": 0})


def test_load_foot_cycleways_filters(tmp_path):
    path = _write_geojson(tmp_path / "cw.geojson", [
        (_hline(7), {"highway": "cycleway", "foot": "yes"}),
        (_hline(-7), {"highway": "cycleway", "foot": "no"}),
        (_hline(14), {"highway": "cycleway"}),
    ])
    geoms, stats = _load_foot_cycleways(path)
    assert len(geoms) == 1
    assert stats == {"raw": 3, "kept": 1}


@pytest.fixture
def street(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    roads = _write_geojson(tmp_path / "roads.geojson", [
        (_hline(0), {"highway": "residential", "name": "Rue Test"}),
    ])
    footways = _write_geojson(tmp_path / "footways.geojson", [
        (_hline(7), {"highway": "footway", "footway": "sidewalk"}),
    ])
    return tmp_path, roads, footways


@pytest.mark.parametrize("foot, expected_gap", [
    ("yes", 0),
    ("designated", 0),
    ("no", 1),
    (None, 1),
])
def test_cycleway_on_other_side(street, foot, expected_gap):
    tmp_path, roads, footways = street
    props = {"highway": "cycleway"}
    if foot is not None:
        props["foot"] = foot
    cycleways = _write_geojson(tmp_path / "cycleways.geojson", [(_hline(-7), props)])

    stats = detect_sidewalk_gaps(roads, footways, cycleways)

    assert stats["one_side_gap"] == expected_gap
    assert stats["both_sides"] == 1 - expected_gap
    assert stats["footway_filter"]["kept_cycleway_foot"] == 1 - expected_gap


def test_without_cycleway_file_keeps_previous_behaviour(street):
    _, roads, footways = street
    stats = detect_sidewalk_gaps(roads, footways)
    assert stats["one_side_gap"] == 1
    assert stats["footway_filter"]["kept_cycleway_foot"] == 0


def test_foot_cycleway_both_sides_counts_as_covered(street):
    tmp_path, roads, _ = street
    footways = _write_geojson(tmp_path / "empty_fw.geojson", [
        (_hline(30), {"highway": "footway", "footway": "sidewalk"}),
    ])
    cycleways = _write_geojson(tmp_path / "cycleways.geojson", [
        (_hline(7), {"highway": "cycleway", "foot": "yes"}),
        (_hline(-7), {"highway": "cycleway", "foot": "designated"}),
    ])
    stats = detect_sidewalk_gaps(roads, footways, cycleways)
    assert stats["both_sides"] == 1
    assert stats["one_side_gap"] == 0


def test_gap_layer_empty_when_cycleway_fills_side(street):
    tmp_path, roads, footways = street
    cycleways = _write_geojson(tmp_path / "cycleways.geojson", [
        (_hline(-7), {"highway": "cycleway", "foot": "yes"}),
    ])
    detect_sidewalk_gaps(roads, footways, cycleways)
    gaps = gpd.read_file(tmp_path / "sidewalk_gaps.geojson")
    assert gaps.geometry.dropna().empty
