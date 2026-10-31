import json

from detect_missing_crossings import _load_crossing_nodes


def _write_geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def test_load_crossing_nodes_reads_osm_id_and_continuous(tmp_path):
    p = tmp_path / "highways.geojson"
    _write_geojson(p, [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.35, 50.85]},
            "properties": {"highway": "crossing", "@type": "node", "@id": 123456789},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.36, 50.86]},
            "properties": {"highway": "crossing", "crossing:continuous": "yes"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.37, 50.87]},
            "properties": {"highway": "elevator", "@id": 42},
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[4.35, 50.85], [4.36, 50.86]]},
            "properties": {"highway": "footway", "@id": 7},
        },
    ])

    gdf = _load_crossing_nodes(str(p))
    assert len(gdf) == 2
    by_id = {row.osm_id: row for row in gdf.itertuples()}
    assert 123456789 in by_id
    assert by_id[123456789].continuous is False
    assert 0 in by_id
    assert by_id[0].continuous is True


def test_load_crossing_nodes_tolerates_bad_id(tmp_path):
    p = tmp_path / "highways.geojson"
    _write_geojson(p, [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [4.35, 50.85]},
        "properties": {"highway": "crossing", "@id": "not-a-number"},
    }])
    gdf = _load_crossing_nodes(str(p))
    assert len(gdf) == 1
    assert gdf.iloc[0]["osm_id"] == 0


from pyproj import Transformer

from detect_missing_crossings import detect_missing_crossings

_TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)
_X0, _Y0 = 150000.0, 170000.0


def _ll(x, y):
    lon, lat = _TO_WGS.transform(_X0 + x, _Y0 + y)
    return [lon, lat]


def _line(coords, props):
    return {"type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [_ll(*c) for c in coords]},
            "properties": props}


def _run_scenario(tmp_path, monkeypatch, connector_props, node_props=None, connector=None, extra=None):
    node = {"highway": "crossing", "@id": 1}
    node.update(node_props or {})
    _write_geojson(tmp_path / "highways.geojson", [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _ll(50, 0)},
        "properties": node,
    }])
    _write_geojson(tmp_path / "roads.geojson", [
        _line([(0, 0), (50, 0), (100, 0)], {"highway": "residential", "name": "Rue Test", "@id": 10}),
    ])
    footways = [
        _line([(0, 6), (100, 6)], {"highway": "footway", "footway": "sidewalk", "@id": 20}),
        _line([(0, -6), (100, -6)], {"highway": "footway", "footway": "sidewalk", "@id": 21}),
    ]
    if connector_props is not None:
        footways.append(_line(connector or [(50, -6), (50, 0), (50, 6)], connector_props))
    footways.extend(extra or [])
    _write_geojson(tmp_path / "footways.geojson", footways)
    monkeypatch.chdir(tmp_path)
    stats = detect_missing_crossings(
        highways_geojson_path="highways.geojson",
        footways_geojson_path="footways.geojson",
        roads_geojson_path="roads.geojson",
        service_roads_geojson_path="absent.geojson",
        cycleways_geojson_path="absent.geojson",
        tracks_geojson_path="absent.geojson",
    )
    out = json.loads((tmp_path / "missing_crossings.geojson").read_text())
    feats = [f for f in out["features"] if f.get("geometry")]
    return stats, feats


def test_sidewalk_through_crossing_node_is_wrong_tag(tmp_path, monkeypatch):
    stats, feats = _run_scenario(tmp_path, monkeypatch,
                                 {"highway": "footway", "footway": "sidewalk", "@id": 99})
    assert stats["wrong_crossing_tag"] == 1
    assert len(feats) == 1
    p = feats[0]["properties"]
    assert p["type"] == "wrong_tag"
    assert p["way_osm_id"] == 99
    assert p["footway_value"] == "sidewalk"
    assert p["osm_id"] == 1


def test_wrong_tag_skipped_when_continuous(tmp_path, monkeypatch):
    stats, feats = _run_scenario(tmp_path, monkeypatch,
                                 {"highway": "footway", "footway": "sidewalk", "@id": 99},
                                 node_props={"crossing:continuous": "yes"})
    assert stats["wrong_crossing_tag"] == 0
    assert feats == []


def test_wrong_tag_detected_even_with_crossing_way_nearby(tmp_path, monkeypatch):
    stats, feats = _run_scenario(
        tmp_path, monkeypatch,
        {"highway": "footway", "footway": "sidewalk", "@id": 99},
        extra=[_line([(60, -6), (60, 0), (60, 6)],
                     {"highway": "footway", "footway": "crossing", "@id": 98})],
    )
    assert stats["wrong_crossing_tag"] == 1
    assert stats["crossing_fully_mapped"] == 0
    assert feats[0]["properties"]["nearest_tag_m"] == 10.0


def test_crossing_tag_is_not_flagged(tmp_path, monkeypatch):
    stats, feats = _run_scenario(tmp_path, monkeypatch,
                                 {"highway": "footway", "footway": "crossing", "@id": 99})
    assert stats["wrong_crossing_tag"] == 0
    assert stats["crossing_fully_mapped"] == 1
    assert feats == []


def test_untagged_footway_stays_missing_tag(tmp_path, monkeypatch):
    stats, feats = _run_scenario(tmp_path, monkeypatch, {"highway": "footway", "@id": 99})
    assert stats["wrong_crossing_tag"] == 0
    assert stats["missing_crossing_tag"] == 1
    assert feats[0]["properties"]["type"] == "missing_tag"


def test_sidewalk_near_but_not_through_node_is_not_wrong_tag(tmp_path, monkeypatch):
    stats, feats = _run_scenario(tmp_path, monkeypatch,
                                 {"highway": "footway", "footway": "sidewalk", "@id": 99},
                                 connector=[(0, 2), (100, 2)])
    assert stats["wrong_crossing_tag"] == 0
    assert all(f["properties"]["type"] != "wrong_tag" for f in feats)
