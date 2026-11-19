import json
import re
from pathlib import Path

import geopandas as gpd
import pytest

from config import EDIT_CANDIDATE_HIGHWAYS
from export_sidewalk_roads import EDIT_CANDIDATES_FILE, _classify_edge_sidewalk, export_sidewalk_roads, write_edit_candidates
from front_contract import assert_layer_contract
from geo_fixtures import TO_WGS as _TO_WGS84, X0 as _X0, Y0 as _Y0


@pytest.mark.parametrize("tags, expected", [
    (("", "", "", ""), "unknown"),
    (("both", "", "", ""), "yes"),
    (("yes", "", "", ""), "yes"),
    (("separate", "", "", ""), "separate"),
    (("no", "", "", ""), "documented"),
    (("left", "", "", ""), "partial"),
    (("right", "", "", ""), "partial"),
    (("", "", "", "yes"), "yes"),
    (("", "", "", "both"), "yes"),
    (("", "", "", "separate"), "separate"),
    (("", "", "", "no"), "documented"),
    (("", "yes", "yes", ""), "documented"),
    (("", "separate", "separate", ""), "separate"),
    (("", "no", "no", ""), "documented"),
    (("", "separate", "no", ""), "documented"),
    (("", "yes", "no", ""), "documented"),
    (("", "separate", "yes", ""), "documented"),
    (("", "yes", "", ""), "partial"),
    (("", "separate", "", ""), "partial"),
    (("", "no", "", ""), "partial"),
    (("left", "", "no", ""), "partial"),
    (("left", "", "separate", ""), "partial"),
    (("no", "separate", "separate", ""), "separate"),
    (("separate", "", "no", ""), "separate"),
    (("both", "", "no", ""), "yes"),
    (("yes", "no", "no", ""), "documented"),
    (("none", "", "", ""), "documented"),
    (("", "", "", "separate;yes"), "documented"),
])
def test_map_classification_is_frozen(tags, expected):
    assert _classify_edge_sidewalk(*tags) == expected


def _line(dy, length):
    coords = [(_X0, _Y0 + dy), (_X0 + length, _Y0 + dy)]
    return [list(_TO_WGS84.transform(x, y)) for x, y in coords]


def _write_roads(path, roads):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"@type": "way", "@id": 1000 + i, **props},
                "geometry": {"type": "LineString", "coordinates": _line(i * 50, length)},
            }
            for i, (length, props) in enumerate(roads)
        ],
    }
    path.write_text(json.dumps(fc))
    return str(path)


_ROADS = [
    (100, {"highway": "residential", "name": "Rue A", "sidewalk:both": "separate"}),
    (100, {"highway": "residential", "name": "Rue A", "sidewalk:left": "separate", "sidewalk:right": "no"}),
    (200, {"highway": "tertiary", "name": "Rue B", "sidewalk": "no"}),
    (50, {"highway": "residential", "name": "Rue B", "sidewalk": "left"}),
    (80, {"highway": "secondary", "name": "Rue C"}),
    (60, {"highway": "residential", "name": "Rue D", "sidewalk": "none"}),
    (100, {"highway": "residential", "sidewalk": "yes"}),
    (100, {"highway": "service", "name": "Rue E", "sidewalk": "no"}),
    (10, {"highway": "residential", "name": "Rue F", "sidewalk": "both"}),
    (100, {"highway": "footway", "name": "Rue G", "footway": "sidewalk"}),
]


@pytest.fixture
def exported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = export_sidewalk_roads(_write_roads(tmp_path / "roads.geojson", _ROADS))
    return stats, gpd.read_file(tmp_path / "sidewalk_roads.geojson")


def test_counts_by_status(exported):
    stats, _ = exported
    assert stats["total_road_ways"] == 7
    assert stats["by_status"] == {
        "separate": 1, "yes": 1, "documented": 3, "partial": 1, "unknown": 1,
    }
    assert stats["pct_by_status"] == {
        "separate": 14.3, "yes": 14.3, "documented": 42.9, "partial": 14.3, "unknown": 14.3,
    }


def test_km_by_status(exported):
    stats, _ = exported
    assert stats["km_by_status"] == {
        "separate": 0.1, "yes": 0.1, "documented": 0.36, "partial": 0.05, "unknown": 0.08,
    }


def test_separate_all_sides(exported):
    stats, _ = exported
    assert stats["separate_all_sides"] == {"count": 2, "pct": 28.6, "km": 0.2}


def test_streets_with_sidewalk_tags(exported):
    stats, _ = exported
    assert stats["streets_total"] == 4
    assert stats["streets_with_sidewalk_tags"] == 2


def test_written_layer(exported):
    _, gdf = exported
    assert gdf.crs.to_epsg() == 4326
    assert list(gdf["sw"]) == [
        "separate", "documented", "documented", "partial", "unknown", "documented", "yes", "yes",
    ]
    assert list(gdf["name"]) == ["rue a", "rue a", "rue b", "rue b", "rue c", "rue d", "", "rue f"]
    assert list(gdf["short"]) == [False] * 7 + [True]


def test_written_layer_carries_way_identity(exported):
    _, gdf = exported
    assert list(gdf["osm_id"]) == [1000, 1001, 1002, 1003, 1004, 1005, 1006, 1008]
    assert list(gdf["highway"]) == [
        "residential", "residential", "tertiary", "residential", "secondary", "residential", "residential", "residential",
    ]
    assert list(gdf["length_m"]) == pytest.approx([100, 100, 200, 50, 80, 60, 100, 10], abs=0.1)


_INDEX_ROADS = [
    (100, {"highway": "residential", "name": "Rue Sans"}),
    (8, {"highway": "residential", "name": "Bout court"}),
    (100, {"highway": "residential", "sidewalk": "no"}),
    (100, {"highway": "tertiary", "name": "Grand axe"}),
    (100, {"highway": "residential", "sidewalk:both:surface": "asphalt"}),
]


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stats = export_sidewalk_roads(_write_roads(tmp_path / "roads.geojson", _INDEX_ROADS))
    return stats, json.loads((tmp_path / EDIT_CANDIDATES_FILE).read_text())


def test_short_streets_are_exported_flagged_but_never_counted(indexed, tmp_path):
    stats, _ = indexed
    gdf = gpd.read_file(tmp_path / "sidewalk_roads.geojson")
    assert list(gdf["osm_id"]) == [1000, 1001, 1002, 1003, 1004]
    assert list(gdf["short"]) == [False, True, False, False, False]
    assert stats["total_road_ways"] == 4
    assert stats["by_status"]["unknown"] == 3


def test_the_edit_index_lists_every_residential_street_without_a_sidewalk_tag(indexed):
    _, index = indexed
    assert [way[0] for way in index["ways"]] == [1000, 1001, 1004]
    lon, lat = _TO_WGS84.transform(_X0 + 50, _Y0)
    assert index["ways"][0][1:] == pytest.approx([lon, lat], abs=1e-6)
    lon, lat = _TO_WGS84.transform(_X0 + 4, _Y0 + 50)
    assert index["ways"][1][1:] == pytest.approx([lon, lat], abs=1e-6)


def test_the_edit_index_skips_ways_without_an_id(tmp_path):
    from shapely.geometry import LineString
    path = tmp_path / "edit.json"
    assert write_edit_candidates([
        {"geometry": LineString([(_X0, _Y0), (_X0 + 10, _Y0)]), "sw": "unknown", "highway": "residential", "osm_id": 0},
        {"geometry": LineString([(_X0, _Y0), (_X0 + 10, _Y0)]), "sw": "unknown", "highway": "residential", "osm_id": 7},
    ], str(path)) == 1
    assert [way[0] for way in json.loads(path.read_text())["ways"]] == [7]


def test_the_edit_index_follows_the_editor_whitelist():
    js = (Path(__file__).resolve().parent.parent / "edit" / "whitelist.js").read_text(encoding="utf-8")
    values = re.search(r'key: "highway", values: Object\.freeze\(\[([^\]]*)\]', js).group(1)
    assert set(re.findall(r'"([^"]+)"', values)) == set(EDIT_CANDIDATE_HIGHWAYS)


def test_missing_osm_id_falls_back_to_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "roads.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"highway": "residential", "name": "Rue Z"},
            "geometry": {"type": "LineString", "coordinates": _line(0, 40)},
        }],
    }))
    export_sidewalk_roads(str(path))
    gdf = gpd.read_file(tmp_path / "sidewalk_roads.geojson")
    assert list(gdf["osm_id"]) == [0]
    assert list(gdf["sw"]) == ["unknown"]


def test_empty_input_writes_placeholder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = _write_roads(tmp_path / "roads.geojson", [
        (100, {"highway": "service", "sidewalk": "no"}),
    ])
    stats = export_sidewalk_roads(path)
    assert stats["total_road_ways"] == 0
    assert set(stats["pct_by_status"].values()) == {0}
    assert stats["separate_all_sides"] == {"count": 0, "pct": 0, "km": 0.0}
    assert stats["streets_total"] == 0
    assert stats["streets_with_sidewalk_tags"] == 0
    gdf = gpd.read_file(tmp_path / "sidewalk_roads.geojson")
    assert len(gdf) == 1
    assert gdf.geometry.isna().all()


def test_layer_matches_front_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    export_sidewalk_roads(_write_roads(tmp_path / "roads.geojson", _ROADS))
    features = assert_layer_contract(tmp_path / "sidewalk_roads.geojson", "sidewalk_roads")
    assert {f["properties"]["sw"] for f in features} == {
        "separate", "yes", "documented", "partial", "unknown",
    }
