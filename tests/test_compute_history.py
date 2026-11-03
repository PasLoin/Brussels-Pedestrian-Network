import pytest
from pyproj import Transformer

from compute_history import _BrusselsStatsHandler, _build_record
from config import PED_HIGHWAY_TYPES
from front_contract import HISTORY_PATHS

_TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)
_X0, _Y0 = 150000.0, 170000.0


def _way(tags, length_m=1000.0, dy=0.0):
    coords = [list(_TO_WGS.transform(_X0, _Y0 + dy)), list(_TO_WGS.transform(_X0 + length_m, _Y0 + dy))]
    return {"geometry": {"type": "LineString", "coordinates": coords}, "properties": tags}


def _node(tags):
    return {"geometry": {"type": "Point", "coordinates": list(_TO_WGS.transform(_X0, _Y0))},
            "properties": tags}


def _record(*features):
    h = _BrusselsStatsHandler()
    for f in features:
        h.process_feature(f)
    return _build_record("2026-11-01", h)


def test_empty_snapshot_has_every_key_at_zero():
    record = _record()
    assert record["date"] == "2026-11-01"
    assert HISTORY_PATHS <= set(record)
    for key in HISTORY_PATHS - {"km_by_highway"}:
        assert record[key] == 0, key
    assert record["km_by_highway"] == {}


def test_pedestrian_km_follows_config_types():
    ped = sorted(PED_HIGHWAY_TYPES)
    record = _record(*[_way({"highway": hw}, dy=i * 10) for i, hw in enumerate(ped)])
    assert record["km_by_highway"] == {hw: 1.0 for hw in ped}
    assert record["ped_km"] == float(len(ped))
    assert record["road_km"] == 0
    assert record["cycleway_km"] == 0


def test_platform_without_highway_counts_as_platform():
    record = _record(
        _way({"railway": "platform"}),
        _way({"public_transport": "platform"}, length_m=500.0, dy=10),
        _way({"railway": "rail"}, dy=20),
    )
    assert record["km_by_highway"] == {"platform": 1.5}
    assert record["ped_km"] == 1.5


def test_road_cycleway_and_untracked_types():
    record = _record(
        _way({"highway": "residential"}),
        _way({"highway": "primary_link"}, length_m=500.0, dy=10),
        _way({"highway": "service"}, dy=20),
        _way({"highway": "cycleway"}, length_m=250.0, dy=30),
        _way({"highway": "construction"}, dy=40),
    )
    assert record["km_by_highway"] == {
        "residential": 1.0, "primary_link": 0.5, "service": 1.0, "cycleway": 0.2,
    }
    assert record["road_km"] == 1.5
    assert record["cycleway_km"] == 0.2
    assert record["ped_km"] == 0
    assert record["road_ways"] == 2


def test_crossing_nodes():
    record = _record(
        _node({"highway": "crossing", "crossing": "marked", "tactile_paving": "yes"}),
        _node({"highway": "crossing", "crossing": "unmarked", "crossing:continuous": "yes"}),
        _node({"highway": "crossing", "crossing": "traffic_signals", "tactile_paving": "contrasted"}),
        _node({"highway": "crossing", "tactile_paving": "no"}),
        _node({"highway": "elevator"}),
        _node({"amenity": "elevator"}),
        _way({"highway": "footway", "footway": "crossing"}, length_m=10.0),
    )
    assert record["crossing_nodes"] == 4
    assert record["crossing_marked"] == 1
    assert record["crossing_unmarked"] == 1
    assert record["crossing_signals"] == 1
    assert record["crossing_continuous"] == 1
    assert record["crossing_with_tactile"] == 2
    assert record["tactile_paving_pct"] == 50.0
    assert record["crossing_tagged_pct"] == 25.0
    assert record["elevator_nodes"] == 2


def test_footway_subtypes_and_quality_tags():
    record = _record(
        _way({"highway": "footway", "footway": "sidewalk", "surface": "asphalt"}),
        _way({"highway": "footway", "footway": "crossing", "smoothness": "good"}, dy=10),
        _way({"highway": "footway", "footway": "link"}, dy=20),
        _way({"highway": "footway", "footway": "traffic_island", "surface": "paving_stones"}, dy=30),
        _way({"highway": "footway", "footway": "access_aisle"}, dy=40),
        _way({"highway": "footway"}, dy=50),
        _way({"highway": "path", "footway": "sidewalk"}, dy=60),
    )
    assert record["footway_ways"] == 6
    assert record["footway_sidewalk"] == 1
    assert record["footway_crossing"] == 1
    assert record["footway_link"] == 1
    assert record["footway_traffic_island"] == 1
    assert record["footway_other"] == 1
    assert record["footway_no_subtag"] == 1
    assert record["footway_with_surface"] == 2
    assert record["footway_with_smoothness"] == 1
    assert record["footway_surface_pct"] == 33.33
    assert record["footway_smoothness_pct"] == 16.67


@pytest.mark.parametrize("geometry", [None, {"type": "Polygon", "coordinates": []}])
def test_ignored_geometries(geometry):
    h = _BrusselsStatsHandler()
    h.process_feature({"geometry": geometry, "properties": {"highway": "footway"}})
    assert _build_record("2026-11-01", h)["footway_ways"] == 0
