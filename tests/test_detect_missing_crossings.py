"""Tests for the crossing-node loader and traceability fields in
scripts/detect_missing_crossings.py."""

import json

from detect_missing_crossings import _load_crossing_nodes


def _write_geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def test_load_crossing_nodes_reads_osm_id_and_continuous(tmp_path):
    p = tmp_path / "highways.geojson"
    _write_geojson(p, [
        {   # nœud crossing normal, avec @id osmium
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.35, 50.85]},
            "properties": {"highway": "crossing", "@type": "node", "@id": 123456789},
        },
        {   # crossing surélevé
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.36, 50.86]},
            "properties": {"highway": "crossing", "crossing:continuous": "yes"},
        },
        {   # pas un crossing → ignoré
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [4.37, 50.87]},
            "properties": {"highway": "elevator", "@id": 42},
        },
        {   # LineString → ignoré
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
    # nœud sans @id → 0 (les anciens extraits restent lisibles)
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
