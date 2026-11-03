import json
import re
from xml.sax.saxutils import quoteattr

import pytest
from pyproj import Transformer

import main
from front_contract import (
    APP_STATS_PATHS,
    STATS_HTML_PATHS,
    assert_layer_contract,
    get_path,
    read_text,
)

_TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)
_X0, _Y0 = 150000.0, 170000.0

STREET = "Rue de l'Essai"
ISLAND_STREET = "Sentier de l'Îlot"

NODES = {
    1: (0, 0), 2: (400, 0), 3: (800, 0), 4: (700, 0),
    11: (0, 6), 12: (400, 6), 13: (800, 6), 14: (700, 6),
    21: (0, -6), 22: (400, -6), 23: (800, -6), 24: (700, -6),
    31: (200, 100), 32: (230, 100),
    41: (600, 100), 42: (630, 100),
}

NODE_TAGS = {
    2: {"highway": "crossing", "crossing": "marked", "tactile_paving": "yes"},
}

ROAD = (100, [1, 2, 4, 3], {"highway": "residential", "name": STREET, "sidewalk:both": "separate"})

FOOTWAYS = [
    (101, [11, 12, 14, 13], {"highway": "footway", "footway": "sidewalk"}),
    (102, [21, 22, 24, 23], {"highway": "footway", "footway": "sidewalk"}),
    (103, [12, 2, 22], {"highway": "footway", "footway": "crossing", "crossing": "marked"}),
    (104, [31, 32], {"highway": "footway"}),
    (105, [41, 42], {"highway": "footway"}),
    (106, [14, 4, 24], {"highway": "footway"}),
]

ADDRESSES = [
    ((20, 15), "2"), ((150, 15), "10"), ((650, 15), "60"), ((780, 15), "70"),
    ((20, -15), "1"), ((150, -15), "9"), ((650, -15), "59"), ((780, -15), "69"),
]

PLATFORM_RING = [(595, 95), (635, 95), (635, 105), (595, 105), (595, 95)]


def _ll(x, y):
    return list(_TO_WGS.transform(_X0 + x, _Y0 + y))


def _line(node_ids, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": [_ll(*NODES[n]) for n in node_ids]}}


def _point(xy, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": _ll(*xy)}}


def _polygon(ring, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [[_ll(*xy) for xy in ring]]}}


def _write(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _osm_xml():
    out = ["<?xml version='1.0' encoding='UTF-8'?>", '<osm version="0.6" generator="test">']
    for nid, xy in NODES.items():
        lon, lat = _ll(*xy)
        tags = "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in NODE_TAGS.get(nid, {}).items())
        out.append(f'  <node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}">{tags}</node>')
    for wid, refs, tags in [ROAD, *FOOTWAYS]:
        nds = "".join(f'<nd ref="{n}"/>' for n in refs)
        tg = "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
        out.append(f'  <way id="{wid}">{nds}{tg}</way>')
    out.append("</osm>")
    return "\n".join(out)


def _with_ids(wid, tags):
    return {**tags, "@type": "way", "@id": wid}


def _write_inputs(folder, complete: bool):
    (folder / "routing_raw.osm").write_text(_osm_xml())

    crossing = _point(NODES[2], {**NODE_TAGS[2], "@type": "node", "@id": 2})
    _write(folder / "highways.geojson",
           [_line(refs, _with_ids(wid, tags)) for wid, refs, tags in FOOTWAYS] + [crossing])
    _write(folder / "sidewalk_roads_raw.geojson", [_line(ROAD[1], ROAD[2])])
    _write(folder / "sidewalk_footways_raw.geojson",
           [_line(refs, _with_ids(wid, tags)) for wid, refs, tags in FOOTWAYS])

    addresses = [_point(xy, {"addr:street": STREET, "addr:housenumber": hn}) for xy, hn in ADDRESSES]
    addresses.append(_point((215, 95), {"addr:street": ISLAND_STREET, "addr:housenumber": "1"}))
    addresses.append(_polygon(
        [(390, 15), (410, 15), (410, 30), (390, 30), (390, 15)],
        {"addr:street": STREET, "addr:housenumber": "20", "building": "house"},
    ))
    _write(folder / "addresses.geojson", addresses)

    kerbs = [
        _point(NODES[n], {"barrier": "kerb", "kerb": "lowered", "tactile_paving": "no",
                          "@type": "node", "@id": n})
        for n in (12, 22)
    ] if complete else []
    platforms = [_polygon(PLATFORM_RING, {"public_transport": "platform", "@type": "way", "@id": 900})] if complete else []
    _write(folder / "kerbs_raw.geojson", kerbs)
    _write(folder / "platforms_raw.geojson", platforms)
    for name in ("service_roads_raw", "cycleways_raw", "tracks_raw"):
        _write(folder / f"{name}.geojson", [])


def _tiled_files() -> set[str]:
    return set(re.findall(r"--named-layer=\w+:(\S+\.geojson)", read_text(".github/workflows/build.yml")))


def _read_geojson(path):
    data = json.loads(path.read_text())
    assert data["type"] == "FeatureCollection", path.name
    return [f for f in data["features"] if f.get("geometry")]


@pytest.fixture(scope="module", params=[True, False], ids=["complete", "optional_layers_empty"])
def run(request, tmp_path_factory):
    folder = tmp_path_factory.mktemp("main_smoke")
    _write_inputs(folder, request.param)
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(folder)
        main.main()
    return folder, request.param


def test_every_layer_tiled_by_the_build_is_written(run):
    folder, _ = run
    missing = sorted(name for name in _tiled_files() if not (folder / name).exists())
    assert not missing
    for name in _tiled_files():
        _read_geojson(folder / name)


def test_simulated_trips_reach_flow_edges(run):
    folder, _ = run
    stats = json.loads((folder / "stats.json").read_text())
    assert stats["routing"]["routed_trips"] > 0
    features = assert_layer_contract(folder / "flow_edges.geojson", "flow_edges")
    assert max(f["properties"]["flow_pct"] for f in features) == 100


def test_stats_json_has_every_section_and_every_path_read_by_the_front(run):
    folder, _ = run
    stats = json.loads((folder / "stats.json").read_text())
    for section in (
        "routing", "od_sampling", "graph", "network", "flow", "sidewalk_gaps",
        "sidewalk_roads", "missing_crossings", "footway_connectivity_candidates",
        "tactile_paving_issues",
    ):
        assert stats.get(section), section
    for path in STATS_HTML_PATHS | APP_STATS_PATHS:
        get_path(stats, path)


def test_od_sampling_stats_from_the_simulation_are_merged(run):
    folder, _ = run
    od = json.loads((folder / "stats.json").read_text())["od_sampling"]
    assert od["points_even"] > 0 and od["points_odd"] > 0
    assert od["points_even"] + od["points_odd"] == od["od_points"]
    assert od["streets_sampled"] == 2
    assert od["points_dropped_too_far"] == 0
    assert od["points_redirected_from_islands"] == 1
    assert od["min_dist_m"] > 0


def test_graph_json_is_consistent_for_the_front(run):
    folder, _ = run
    graph = json.loads((folder / "graph.json").read_text())
    assert set(graph) == {"hw", "n", "e"}
    n_nodes = len(graph["n"])
    assert graph["e"]
    for src, tgt, cost, length, hw_i, _, coords, ground in graph["e"]:
        assert 0 <= src < n_nodes and 0 <= tgt < n_nodes
        assert cost > 0 and length > 0
        assert 0 <= hw_i < len(graph["hw"])
        assert len(coords) >= 2
        assert ground in (0, 1)


def test_islands_respect_the_platform_layer(run):
    folder, complete = run
    islands = _read_geojson(folder / "graph_islands.geojson")
    isolated = [f for f in islands if f["properties"]["type"] == "isolated"]
    way_ids = {f["properties"]["way_ids"] for f in isolated}
    assert "104" in way_ids
    assert ("105" in way_ids) is not complete


def test_untagged_footway_across_the_road_is_a_crossing_candidate(run):
    folder, _ = run
    features = assert_layer_contract(folder / "footway_crossing_candidates.geojson", "footway_crossing_candidates")
    assert [f["properties"]["osm_id"] for f in features] == [106]


def test_kerbs_layer_reaches_the_tactile_paving_check(run):
    folder, complete = run
    features = _read_geojson(folder / "tactile_paving_issues.geojson")
    if complete:
        assert [f["properties"]["reason"] for f in features] == ["value_mismatch"]
        assert features[0]["properties"]["osm_id"] == 2
    else:
        assert features == []
