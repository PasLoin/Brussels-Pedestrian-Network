import json
import math

import numpy as np
import pytest
from pyproj import Transformer

import export
import routing
from build_graph import build_graph
from clean_osm import clean_osm
from export import undirected_edge_groups
from simulation import drop_unsnapped, simulate_flows

_LAT0, _LON0 = 50.80, 4.30
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = _M_PER_DEG_LAT * math.cos(math.radians(_LAT0))
_TO_LAMBERT = Transformer.from_crs("EPSG:4326", "EPSG:31370", always_xy=True)

_N_BLOCKS = 7
_BLOCK_M = 100.0
_SIDEWALK_Y = 5.0
_UNDERGROUND_Y = 10.0
_POINT_Y = 12.0
_ISLAND_Y = 14.0

_EXPECTED_SEGMENT_FLOWS = [4, 7, 9, 9, 7, 4]


def test_drop_unsnapped_filters_every_column_together():
    snapped, pts, streets = drop_unsnapped(
        [3, -1, 5, -1, 7], ["a", "b", "c", "d", "e"], ["s1", "s2", "s3", "s4", "s5"],
    )
    assert snapped == [3, 5, 7]
    assert pts == ["a", "c", "e"]
    assert streets == ["s1", "s3", "s5"]


def test_drop_unsnapped_without_unsnapped_points_is_unchanged():
    assert drop_unsnapped([1, 2], ["a", "b"]) == ([1, 2], ["a", "b"])


def test_drop_unsnapped_with_only_unsnapped_points_is_empty():
    assert drop_unsnapped([-1, -1], ["a", "b"], ["x", "y"]) == ([], [], [])


def _ll(x, y):
    return _LAT0 + y / _M_PER_DEG_LAT, _LON0 + x / _M_PER_DEG_LON


def _lambert(x, y):
    lat, lon = _ll(x, y)
    return _TO_LAMBERT.transform(lon, lat)


class _Xml:
    def __init__(self):
        self.nodes, self.ways = [], []
        self.next_node, self.next_way = 1, 1000

    def node(self, x, y):
        nid = self.next_node
        self.next_node += 1
        lat, lon = _ll(x, y)
        self.nodes.append(f'<node id="{nid}" lat="{lat:.8f}" lon="{lon:.8f}" version="1"/>')
        return nid

    def way(self, refs, **tags):
        wid = self.next_way
        self.next_way += 1
        nd = "".join(f'<nd ref="{r}"/>' for r in refs)
        tag_xml = "".join(f'<tag k="{k.replace("__", ":")}" v="{v}"/>' for k, v in tags.items())
        self.ways.append(f'<way id="{wid}" version="1">{nd}{tag_xml}</way>')

    def text(self):
        return (
            "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"test\">\n"
            + "\n".join(self.nodes) + "\n" + "\n".join(self.ways) + "\n</osm>\n"
        )


def _street_xml(kind):
    xml = _Xml()
    xs = [k * _BLOCK_M for k in range(_N_BLOCKS + 1)]
    road = [xml.node(x, 0.0) for x in xs]
    xml.way(road, highway="residential", name="Rue Test")
    for k, x in enumerate(xs):
        stub = xml.node(x, -20.0)
        xml.way([road[k], stub], highway="service", name=f"Entrée {k}")
    island_west = xml.node(200.0, _ISLAND_Y)
    island_east = xml.node(260.0, _ISLAND_Y)
    xml.way([island_west, island_east], highway="footway", name="Îlot")
    if kind == "cycleway":
        lane = [xml.node(x, _SIDEWALK_Y) for x in xs]
        xml.way(lane, highway="cycleway", name="Piste")
        for k in range(len(xs)):
            xml.way([road[k], lane[k]], highway="footway", name=f"Raccord {k}")
    if kind == "sidewalk":
        side = [xml.node(x, _SIDEWALK_Y) for x in xs]
        xml.way(side, highway="footway", footway="sidewalk", name="Trottoir")
        for k in range(len(xs)):
            xml.way([road[k], side[k]], highway="footway", name=f"Raccord {k}")
        under_west = xml.node(xs[0], _UNDERGROUND_Y)
        under_east = xml.node(xs[-1], _UNDERGROUND_Y)
        xml.way([under_west, under_east], highway="footway", level="-1", name="Couloir")
        xml.way([side[0], under_west], highway="steps", level="-1;0", name="Escalier ouest")
        xml.way([side[-1], under_east], highway="steps", level="-1;0", name="Escalier est")
    return xml.text()


def _od_points():
    pts = [_lambert(k * _BLOCK_M + 10.0, _POINT_Y) for k in range(_N_BLOCKS)]
    far = _lambert(350.0, 400.0)
    streets = ["Rue Test"] * len(pts) + ["Rue Lointaine"]
    sides = ["even" if k % 2 == 0 else "odd" for k in range(len(pts))] + ["even"]
    return pts + [far], streets, sides


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(routing, "MIN_OD_DISTANCE_M", 300.0)
    monkeypatch.setattr(routing, "MAX_OD_DISTANCE_M", 5000.0)
    monkeypatch.setattr(routing, "MAX_OD_PAIRS", 50_000)
    monkeypatch.setattr(export, "MIN_FLOW_THRESHOLD", 1)
    monkeypatch.setattr(export, "TOP_RANK_PCT", 100.0)


def _main_component_mask(graph):
    components = graph.connected_components(mode="weak")
    biggest = max(components, key=len)
    mask = np.zeros(graph.vcount(), dtype=bool)
    mask[list(biggest)] = True
    return mask


def _simulate(tmp_path, monkeypatch, kind):
    raw, clean = tmp_path / "raw.osm", tmp_path / "clean.osm"
    raw.write_text(_street_xml(kind))
    clean_osm(str(raw), str(clean))
    gb = build_graph(str(clean))
    groups = undirected_edge_groups(gb.edge_tuples, gb.edge_geoms, gb.edge_lengths)
    mask = _main_component_mask(gb.graph)
    assert not mask.all()
    pts, streets, sides = _od_points()
    monkeypatch.chdir(tmp_path)
    sim = simulate_flows(gb, groups, mask, pts, streets, sides, max_snap_m=150.0)
    flows = json.loads((tmp_path / "flow_edges.geojson").read_text())
    feats = [f for f in flows["features"] if f.get("geometry")]
    return gb, sim, feats


@pytest.fixture
def with_sidewalk(tmp_path, monkeypatch):
    return _simulate(tmp_path, monkeypatch, "sidewalk")


@pytest.fixture
def without_sidewalk(tmp_path, monkeypatch):
    return _simulate(tmp_path, monkeypatch, "road")


@pytest.fixture
def with_cycleway(tmp_path, monkeypatch):
    return _simulate(tmp_path, monkeypatch, "cycleway")


def test_far_point_is_dropped_before_pairing(with_sidewalk):
    _, sim, _ = with_sidewalk
    assert len(sim.od_points) == _N_BLOCKS
    assert sim.od_sampling_stats["points_dropped_too_far"] == 1
    assert sim.od_sampling_stats["streets_sampled"] == 1
    assert sim.od_sampling_stats["points_even"] == 4
    assert sim.od_sampling_stats["points_odd"] == 3


def test_pairs_match_hand_count(with_sidewalk):
    _, sim, _ = with_sidewalk
    assert len(sim.od_pairs) == 10
    assert sim.rejected_near == 11
    assert sim.rejected_far == 0
    assert all(a >= 0 and b >= 0 for a, b in sim.od_pairs)


def test_routing_totals_match_hand_count(with_sidewalk):
    _, sim, _ = with_sidewalk
    assert sim.routing.routed == 10
    assert sim.routing.total_routed_distance == pytest.approx(4000.0, rel=0.01)


def test_underground_corridor_is_not_used_for_snapping(with_sidewalk):
    _, sim, _ = with_sidewalk
    assert sim.od_sampling_stats["edges_not_at_ground_level"] == 6


def test_walkers_use_the_sidewalk_not_the_road(with_sidewalk):
    _, sim, feats = with_sidewalk
    assert {f["properties"]["infra_type"] for f in feats} == {"pedestrian"}
    assert {f["properties"]["highway"] for f in feats} == {"footway"}
    assert sim.flow_stats["flow_by_infra"] == {"pedestrian": sum(_EXPECTED_SEGMENT_FLOWS)}
    assert sim.flow_stats["forced_road_segments"] == 0


def test_sidewalk_segment_flows_match_hand_count(with_sidewalk):
    _, sim, feats = with_sidewalk
    max_flow = max(_EXPECTED_SEGMENT_FLOWS)
    expected = sorted(round(f / max_flow * 100, 2) for f in _EXPECTED_SEGMENT_FLOWS)
    assert sorted(f["properties"]["flow_pct"] for f in feats) == expected
    assert sim.flow_stats["max_flow_trips"] == max_flow


def test_without_sidewalk_walkers_are_on_the_road(without_sidewalk):
    _, sim, feats = without_sidewalk
    assert {f["properties"]["infra_type"] for f in feats} == {"road"}
    assert {f["properties"]["highway"] for f in feats} == {"residential"}
    assert sim.flow_stats["flow_by_infra"] == {"road": sum(_EXPECTED_SEGMENT_FLOWS)}
    assert sim.flow_stats["forced_road_segments"] == len(_EXPECTED_SEGMENT_FLOWS)


def test_without_sidewalk_totals_are_unchanged(without_sidewalk):
    _, sim, _ = without_sidewalk
    assert sim.routing.routed == 10
    assert sim.routing.total_routed_distance == pytest.approx(4000.0, rel=0.01)
    assert sim.od_sampling_stats["edges_not_at_ground_level"] == 0


@pytest.mark.parametrize("variant", ["with_sidewalk", "without_sidewalk", "with_cycleway"])
def test_point_next_to_an_island_is_redirected_to_main_network(variant, request):
    gb, sim, _ = request.getfixturevalue(variant)
    assert sim.od_sampling_stats["points_redirected_from_islands"] == 1
    assert sim.routing.routed == 10
    island = {gb.edge_tuples[e] for e, n in enumerate(gb.edge_names) if n == "Îlot"}
    island_nodes = {n for t in island for n in t}
    assert not island_nodes & {n for pair in sim.od_pairs for n in pair}


def test_cycleway_without_foot_carries_the_flow(with_cycleway):
    _, sim, feats = with_cycleway
    assert {f["properties"]["infra_type"] for f in feats} == {"cycleway_no_foot"}
    assert {f["properties"]["highway"] for f in feats} == {"cycleway"}
    assert sim.flow_stats["flow_by_infra"] == {"cycleway_no_foot": sum(_EXPECTED_SEGMENT_FLOWS)}
    assert sim.flow_stats["forced_cycleway_segments"] == len(_EXPECTED_SEGMENT_FLOWS)
    assert sim.routing.total_routed_distance == pytest.approx(4000.0, rel=0.01)
