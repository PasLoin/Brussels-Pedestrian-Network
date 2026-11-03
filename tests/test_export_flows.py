import json

import geopandas as gpd
import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point

import export
from export import (
    _infra_type,
    compute_network_stats,
    export_flow_layers,
    export_routing_graph,
    undirected_edge_groups,
)
from front_contract import assert_layer_contract

_X0, _Y0 = 150000.0, 170000.0
_TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)


def _seg(x1, y1, x2, y2):
    return LineString([(_X0 + x1, _Y0 + y1), (_X0 + x2, _Y0 + y2)])


class Network:
    def __init__(self):
        self.edge_tuples = []
        self.edge_geoms = []
        self.edge_lengths = []
        self.edge_highways = []
        self.edge_cycleway_nf = []
        self.edge_foot_tags = []
        self.flows = []

    def way(self, u, v, geom, highway, flows=(0, 0), cycleway_nf=False, foot=""):
        length = geom.length if geom is not None else 10.0
        reverse = LineString(list(geom.coords)[::-1]) if geom is not None else None
        for (a, b), g, f in (((u, v), geom, flows[0]), ((v, u), reverse, flows[1])):
            self.edge_tuples.append((a, b))
            self.edge_geoms.append(g)
            self.edge_lengths.append(length)
            self.edge_highways.append(highway)
            self.edge_cycleway_nf.append(cycleway_nf)
            self.edge_foot_tags.append(foot)
            self.flows.append(f)
        return self

    def groups(self):
        return undirected_edge_groups(self.edge_tuples, self.edge_geoms, self.edge_lengths)

    def export(self):
        return export_flow_layers(
            np.array(self.flows, dtype=np.int32),
            self.groups(),
            self.edge_highways,
            self.edge_geoms,
            self.edge_lengths,
            self.edge_cycleway_nf,
            self.edge_foot_tags,
        )


def _scenario():
    return (
        Network()
        .way(0, 1, _seg(0, 0, 200, 0), "primary", flows=(60, 40))
        .way(2, 3, _seg(0, 50, 100, 50), "cycleway", flows=(30, 20), cycleway_nf=True)
        .way(4, 5, _seg(0, 100, 80, 100), "residential", flows=(4, 0))
        .way(6, 7, _seg(0, 150, 50, 150), "footway", flows=(0, 0))
    )


def _features(name):
    data = json.loads(open(name).read())
    return [f for f in data["features"] if f.get("geometry")]


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, "TOP_RANK_PCT", 5.0)
    monkeypatch.setattr(export, "MIN_FLOW_THRESHOLD", 5)
    return tmp_path


def test_flow_stats_match_hand_count(workdir):
    stats = _scenario().export()

    assert stats["max_flow_trips"] == 100
    assert stats["flow_threshold_trips"] == 95
    assert stats["flow_edges_exported"] == 2
    assert stats["flow_edges_dropped_low"] == 1
    assert stats["forced_road_segments"] == 1
    assert stats["forced_cycleway_segments"] == 0
    assert stats["forced_road_length_m"] == 200
    assert stats["forced_cycleway_length_m"] == 0


def test_flow_by_infra_sums_both_directions(workdir):
    stats = _scenario().export()

    assert stats["flow_by_infra"] == {"road": 104, "cycleway_no_foot": 50}
    assert stats["edges_with_flow_by_infra"] == {"road": 2, "cycleway_no_foot": 1}
    assert stats["length_with_flow_by_infra_m"] == {"road": 280, "cycleway_no_foot": 100}


def test_flow_edges_layer_content(workdir):
    _scenario().export()
    feats = _features("flow_edges.geojson")

    by_highway = {f["properties"]["highway"]: f["properties"] for f in feats}
    assert set(by_highway) == {"primary", "cycleway"}
    assert by_highway["primary"]["flow_pct"] == 100.0
    assert by_highway["primary"]["infra_type"] == "road"
    assert by_highway["cycleway"]["flow_pct"] == 50.0
    assert by_highway["cycleway"]["infra_type"] == "cycleway_no_foot"


def test_flow_edges_layer_is_in_wgs84(workdir):
    _scenario().export()
    lon, lat = _features("flow_edges.geojson")[0]["geometry"]["coordinates"][0]
    assert 4.0 < lon < 5.0
    assert 50.0 < lat < 51.5


def test_forced_layers_with_top_5_pct(workdir):
    _scenario().export()

    roads = _features("forced_segments.geojson")
    assert len(roads) == 1
    assert roads[0]["properties"]["highway"] == "primary"
    assert roads[0]["properties"]["flow"] == 100
    assert roads[0]["properties"]["length_m"] == 200.0
    assert _features("forced_cycleway.geojson") == []


def test_forced_layers_with_top_50_pct(workdir, monkeypatch):
    monkeypatch.setattr(export, "TOP_RANK_PCT", 50.0)
    stats = _scenario().export()

    assert stats["flow_threshold_trips"] == 50
    assert stats["forced_road_segments"] == 1
    assert stats["forced_cycleway_segments"] == 1
    cycleways = _features("forced_cycleway.geojson")
    assert len(cycleways) == 1
    assert cycleways[0]["properties"]["flow"] == 50


def test_min_flow_threshold_is_inclusive(workdir, monkeypatch):
    monkeypatch.setattr(export, "MIN_FLOW_THRESHOLD", 4)
    stats = _scenario().export()

    assert stats["flow_edges_exported"] == 3
    assert stats["flow_edges_dropped_low"] == 0


def test_group_without_geometry_is_skipped(workdir):
    net = _scenario().way(8, 9, None, "primary", flows=(500, 500))
    stats = net.export()

    assert stats["max_flow_trips"] == 1000
    assert stats["flow_edges_exported"] == 2
    assert stats["flow_by_infra"]["road"] == 104


def test_all_zero_flows(workdir):
    net = Network().way(0, 1, _seg(0, 0, 100, 0), "footway")
    stats = net.export()

    assert stats["max_flow_trips"] == 1
    assert stats["flow_edges_exported"] == 0
    assert stats["forced_road_segments"] == 0
    assert _features("flow_edges.geojson") == []


@pytest.mark.parametrize("highway, cycleway_nf, foot, expected", [
    ("cycleway", False, "", "cycleway_foot_yes"),
    ("cycleway", True, "", "cycleway_no_foot"),
    ("cycleway", True, "no", "cycleway_no_foot"),
    ("cycleway", True, "yes", "cycleway_foot_yes"),
    ("cycleway", True, "designated", "cycleway_foot_yes"),
    ("cycleway", True, "permissive", "cycleway_foot_yes"),
    ("footway", False, "", "pedestrian"),
    ("pedestrian", False, "", "pedestrian"),
    ("path", False, "", "pedestrian"),
    ("steps", False, "", "pedestrian"),
    ("living_street", False, "", "pedestrian"),
    ("elevator", False, "", "pedestrian"),
    ("track", False, "", "pedestrian"),
    ("bridleway", False, "yes", "pedestrian"),
    ("platform", False, "", "pedestrian"),
    ("corridor", False, "", "pedestrian"),
    ("corridor", False, "permissive", "pedestrian"),
    ("residential", False, "", "road"),
    ("service", False, "", "road"),
    ("primary", False, "yes", "road"),
])
def test_infra_type(highway, cycleway_nf, foot, expected):
    assert _infra_type(highway, cycleway_nf, foot) == expected


def _partition(groups):
    return sorted(eid for g in groups for eid in g)


def test_reversed_directions_form_one_group():
    net = Network().way(0, 1, _seg(0, 0, 100, 0), "footway")
    groups = net.groups()
    assert len(groups) == 1
    assert sorted(groups[0]) == [0, 1]


def test_parallel_ways_with_different_lengths_stay_separate():
    net = (
        Network()
        .way(0, 1, _seg(0, 0, 100, 0), "footway")
        .way(0, 1, LineString([(_X0, _Y0), (_X0 + 50, _Y0 + 30), (_X0 + 100, _Y0)]), "footway")
    )
    groups = net.groups()
    assert len(groups) == 2
    assert _partition(groups) == [0, 1, 2, 3]


def test_parallel_ways_with_same_length_but_mirrored_shape_stay_separate():
    up = LineString([(_X0, _Y0), (_X0 + 50, _Y0 + 30), (_X0 + 100, _Y0)])
    down = LineString([(_X0, _Y0), (_X0 + 50, _Y0 - 30), (_X0 + 100, _Y0)])
    net = Network().way(0, 1, up, "footway").way(0, 1, down, "footway")
    groups = net.groups()
    assert len(groups) == 2
    assert all(len(g) == 2 for g in groups)


def test_groups_partition_all_edges():
    net = _scenario().way(8, 9, None, "primary")
    assert _partition(net.groups()) == list(range(len(net.edge_tuples)))


def test_network_stats_count_each_physical_segment_once():
    net = (
        Network()
        .way(0, 1, _seg(0, 0, 1000, 0), "footway")
        .way(1, 2, _seg(1000, 0, 1500, 0), "primary")
        .way(2, 3, _seg(1500, 0, 1750, 0), "cycleway", cycleway_nf=True)
    )
    stats = compute_network_stats(
        net.groups(), net.edge_highways, net.edge_lengths,
        net.edge_cycleway_nf, net.edge_foot_tags,
    )

    assert stats["total_km"] == 1.75
    assert stats["km_by_highway"] == {"footway": 1.0, "primary": 0.5, "cycleway": 0.25}
    assert stats["edges_by_highway"] == {"footway": 1, "primary": 1, "cycleway": 1}
    assert stats["km_by_category"] == {
        "pedestrian": 1.0, "road": 0.5, "cycleway_no_foot": 0.25, "cycleway_foot_yes": 0.0,
    }


def _routing_graph(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    coords = [(0, 0), (100, 0), (100, 100), (0, 100), (200, 0)]
    node_list = [9000 + i for i in range(len(coords))]
    nodes_gdf = gpd.GeoDataFrame(
        {
            "x": [_X0 + x for x, _ in coords],
            "y": [_Y0 + y for _, y in coords],
            "geometry": [Point(_X0 + x, _Y0 + y) for x, y in coords],
        },
        index=node_list,
        crs="EPSG:31370",
    )
    edges = [
        ((0, 1), _seg(0, 0, 100, 0), 100.0, 100.0, "footway", False, ""),
        ((1, 2), _seg(100, 0, 100, 100), 800.0, 100.0, "primary", False, ""),
        ((2, 3), _seg(100, 100, 0, 100), 180.04, 100.02, "cycleway", True, ""),
        ((3, 0), _seg(0, 100, 0, 0), 100.0, 100.0, "cycleway", False, "yes"),
        ((1, 4), None, 250.0, 100.0, float("nan"), False, ""),
        ((4, 1), _seg(200, 0, 100, 0), 170.0, 100.0, "cycleway", True, "designated"),
    ]
    export_routing_graph(
        node_list, nodes_gdf,
        [e[0] for e in edges], [e[2] for e in edges], [e[3] for e in edges],
        [e[4] for e in edges], [e[1] for e in edges],
        [e[5] for e in edges], [e[6] for e in edges],
    )
    return json.loads((tmp_path / "graph.json").read_text()), coords


def test_routing_graph_structure(tmp_path, monkeypatch):
    data, coords = _routing_graph(tmp_path, monkeypatch)

    assert len(data["n"]) == len(coords)
    assert len(data["e"]) == 6
    assert [e[:2] for e in data["e"]] == [[0, 1], [1, 2], [2, 3], [3, 0], [1, 4], [4, 1]]
    assert data["hw"] == sorted(data["hw"])
    assert [data["hw"][e[4]] for e in data["e"]] == [
        "footway", "primary", "cycleway", "cycleway", "unclassified", "cycleway",
    ]


def test_routing_graph_infra_codes_match_app_js(tmp_path, monkeypatch):
    data, _ = _routing_graph(tmp_path, monkeypatch)
    assert [e[5] for e in data["e"]] == [0, 1, 2, 3, 1, 3]


def test_routing_graph_weights_and_lengths_rounded(tmp_path, monkeypatch):
    data, _ = _routing_graph(tmp_path, monkeypatch)
    assert [e[2] for e in data["e"]] == [100.0, 800.0, 180.0, 100.0, 250.0, 170.0]
    assert data["e"][2][3] == 100.0


def test_routing_graph_coordinates_are_lat_lng(tmp_path, monkeypatch):
    data, coords = _routing_graph(tmp_path, monkeypatch)

    for (x, y), (lat, lng) in zip(coords, data["n"]):
        exp_lng, exp_lat = _TO_WGS.transform(_X0 + x, _Y0 + y)
        assert lat == pytest.approx(exp_lat, abs=1e-6)
        assert lng == pytest.approx(exp_lng, abs=1e-6)
        assert 50.0 < lat < 51.5
        assert 4.0 < lng < 5.0


def test_routing_graph_edge_geometry(tmp_path, monkeypatch):
    data, _ = _routing_graph(tmp_path, monkeypatch)

    first = data["e"][0][6]
    assert first[0] == data["n"][0]
    assert first[-1] == data["n"][1]
    assert data["e"][4][6] == [data["n"][1], data["n"][4]]


def test_low_flow_road_is_never_forced(workdir, monkeypatch):
    monkeypatch.setattr(export, "TOP_RANK_PCT", 100.0)
    stats = _scenario().export()

    roads = _features("forced_segments.geojson")
    assert [f["properties"]["highway"] for f in roads] == ["primary"]
    assert stats["forced_road_segments"] == 1
    assert stats["forced_road_length_m"] == 200
    assert stats["flow_edges_dropped_low"] == 1


def test_low_flow_segments_still_count_in_infra_stats(workdir, monkeypatch):
    monkeypatch.setattr(export, "TOP_RANK_PCT", 100.0)
    stats = _scenario().export()

    assert stats["flow_by_infra"]["road"] == 104
    assert stats["edges_with_flow_by_infra"]["road"] == 2
    assert stats["length_with_flow_by_infra_m"]["road"] == 280


def test_min_flow_above_every_segment_forces_nothing(workdir, monkeypatch):
    monkeypatch.setattr(export, "TOP_RANK_PCT", 100.0)
    monkeypatch.setattr(export, "MIN_FLOW_THRESHOLD", 1000)
    stats = _scenario().export()

    assert stats["forced_road_segments"] == 0
    assert stats["forced_cycleway_segments"] == 0
    assert stats["flow_edges_exported"] == 0


@pytest.mark.parametrize("top_pct", [5.0, 15.0, 50.0, 100.0])
@pytest.mark.parametrize("min_flow", [1, 5, 50, 60])
def test_forced_segments_are_always_displayed(workdir, monkeypatch, top_pct, min_flow):
    monkeypatch.setattr(export, "TOP_RANK_PCT", top_pct)
    monkeypatch.setattr(export, "MIN_FLOW_THRESHOLD", min_flow)
    _scenario().export()

    shown = {json.dumps(f["geometry"]["coordinates"]) for f in _features("flow_edges.geojson")}
    forced = _features("forced_segments.geojson") + _features("forced_cycleway.geojson")
    assert {json.dumps(f["geometry"]["coordinates"]) for f in forced} <= shown


def test_routing_graph_platform_and_corridor_are_pedestrian(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nodes_gdf = gpd.GeoDataFrame(
        {"x": [_X0, _X0 + 50, _X0 + 100], "y": [_Y0, _Y0, _Y0],
         "geometry": [Point(_X0, _Y0), Point(_X0 + 50, _Y0), Point(_X0 + 100, _Y0)]},
        index=[1, 2, 3], crs="EPSG:31370",
    )
    export_routing_graph(
        [1, 2, 3], nodes_gdf,
        [(0, 1), (1, 2)], [80.0, 50.0], [50.0, 50.0],
        ["platform", "corridor"],
        [_seg(0, 0, 50, 0), _seg(50, 0, 100, 0)],
        [False, False], ["", "permissive"],
    )
    data = json.loads((tmp_path / "graph.json").read_text())
    assert [e[5] for e in data["e"]] == [0, 0]


def _ground_graph(tmp_path, monkeypatch, levels):
    monkeypatch.chdir(tmp_path)
    nodes_gdf = gpd.GeoDataFrame(
        {"x": [_X0, _X0 + 50], "y": [_Y0, _Y0], "geometry": [Point(_X0, _Y0), Point(_X0 + 50, _Y0)]},
        index=[1, 2], crs="EPSG:31370",
    )
    n = 6
    export_routing_graph(
        [1, 2], nodes_gdf,
        [(0, 1)] * n, [50.0] * n, [50.0] * n, ["footway"] * n,
        [_seg(0, 0, 50, 0)] * n, [False] * n, [""] * n,
        **({} if levels is None else {"edge_levels": levels}),
    )
    return json.loads((tmp_path / "graph.json").read_text())


def test_routing_graph_ground_flag_follows_levels(tmp_path, monkeypatch):
    data = _ground_graph(tmp_path, monkeypatch, ["", "0", "-1", "1", "?", "0;-1"])
    assert [e[7] for e in data["e"]] == [1, 1, 0, 0, 0, 0]


def test_routing_graph_without_levels_marks_everything_as_ground(tmp_path, monkeypatch):
    data = _ground_graph(tmp_path, monkeypatch, None)
    assert [e[7] for e in data["e"]] == [1] * 6


def test_flow_layer_matches_front_contract(workdir):
    _scenario().export()
    features = assert_layer_contract(workdir / "flow_edges.geojson", "flow_edges")
    assert {f["properties"]["infra_type"] for f in features} == {"road", "cycleway_no_foot"}
