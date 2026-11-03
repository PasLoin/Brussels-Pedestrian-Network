import math

import pytest

from build_graph import build_graph
from clean_osm import clean_osm
from routing import route_pairs

_M_PER_DEG_LAT = 111_320.0
_LAT0, _LON0 = 50.80, 4.30
_M_PER_DEG_LON = _M_PER_DEG_LAT * math.cos(math.radians(_LAT0))

_SCENARIOS = [
    ("primary vs residential detour 1000 m", 300, {"highway": "primary"}, 1000, {"highway": "residential"}, "detour"),
    ("primary vs residential detour 1400 m", 300, {"highway": "primary"}, 1400, {"highway": "residential"}, "direct"),
    ("cycleway foot=yes vs footway detour", 100, {"highway": "cycleway", "foot": "yes"}, 150, {"highway": "footway"}, "direct"),
    ("tertiary vs cycleway without foot", 100, {"highway": "tertiary"}, 150, {"highway": "cycleway"}, "detour"),
    ("steps vs footway detour 130 m", 100, {"highway": "steps"}, 130, {"highway": "footway"}, "detour"),
    ("steps vs footway detour 170 m", 100, {"highway": "steps"}, 170, {"highway": "footway"}, "direct"),
    ("elevator vs footway detour 24 m", 20, {"highway": "elevator"}, 24, {"highway": "footway"}, "detour"),
    ("elevator vs footway detour 32 m", 20, {"highway": "elevator"}, 32, {"highway": "footway"}, "direct"),
    ("platform vs footway detour 130 m", 100, {"highway": "platform"}, 130, {"highway": "footway"}, "detour"),
    ("platform vs footway detour 190 m", 100, {"highway": "platform"}, 190, {"highway": "footway"}, "direct"),
    ("railway=platform vs footway detour 190 m", 100, {"railway": "platform"}, 190, {"highway": "footway"}, "direct"),
    ("corridor permissive vs footway detour", 100, {"highway": "corridor", "foot": "permissive"}, 108, {"highway": "footway"}, "detour"),
    ("corridor foot=yes vs footway detour", 100, {"highway": "corridor", "foot": "yes"}, 108, {"highway": "footway"}, "direct"),
    ("footway foot=private vs long detour", 100, {"highway": "footway", "foot": "private"}, 400, {"highway": "footway"}, "detour"),
    ("footway foot=no vs long detour", 100, {"highway": "footway", "foot": "no"}, 400, {"highway": "footway"}, "detour"),
    ("residential access=private vs long detour", 100, {"highway": "residential", "access": "private"}, 400, {"highway": "residential"}, "detour"),
    ("residential access=private foot=yes vs detour", 100, {"highway": "residential", "access": "private", "foot": "yes"}, 400, {"highway": "residential"}, "direct"),
]

_GATE_SCENARIO = "footway through private gate vs long detour"


def _ll(origin_lat, x_m, y_m):
    return origin_lat + y_m / _M_PER_DEG_LAT, _LON0 + x_m / _M_PER_DEG_LON


class _Xml:
    def __init__(self):
        self.nodes, self.ways = [], []
        self.next_node, self.next_way = 1, 1000

    def node(self, lat, lon, tags=None):
        nid = self.next_node
        self.next_node += 1
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in (tags or {}).items())
        self.nodes.append(f'<node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}" version="1">{tag_xml}</node>')
        return nid

    def way(self, refs, tags):
        wid = self.next_way
        self.next_way += 1
        nd = "".join(f'<nd ref="{r}"/>' for r in refs)
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        self.ways.append(f'<way id="{wid}" version="1">{nd}{tag_xml}</way>')

    def text(self):
        return (
            "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"test\">\n"
            + "\n".join(self.nodes) + "\n" + "\n".join(self.ways) + "\n</osm>\n"
        )


def _detour_height(direct_m, detour_m):
    return math.sqrt((detour_m / 2) ** 2 - (direct_m / 2) ** 2)


def _build_scenarios():
    xml = _Xml()
    endpoints = {}
    for i, (name, direct_m, direct_tags, detour_m, detour_tags, _) in enumerate(_SCENARIOS):
        lat0 = _LAT0 + i * 0.01
        a = xml.node(*_ll(lat0, 0, 0))
        b = xml.node(*_ll(lat0, direct_m, 0))
        c = xml.node(*_ll(lat0, direct_m / 2, _detour_height(direct_m, detour_m)))
        xml.way([a, b], {**direct_tags, "name": f"{name} | direct"})
        xml.way([a, c, b], {**detour_tags, "name": f"{name} | detour"})
        endpoints[name] = (a, b)

    lat0 = _LAT0 + len(_SCENARIOS) * 0.01
    a = xml.node(*_ll(lat0, 0, 0))
    gate = xml.node(*_ll(lat0, 50, 0), {"barrier": "gate", "access": "private"})
    b = xml.node(*_ll(lat0, 100, 0))
    c = xml.node(*_ll(lat0, 50, _detour_height(100, 400)))
    xml.way([a, gate, b], {"highway": "footway", "name": f"{_GATE_SCENARIO} | direct"})
    xml.way([a, c, b], {"highway": "footway", "name": f"{_GATE_SCENARIO} | detour"})
    endpoints[_GATE_SCENARIO] = (a, b)
    return xml.text(), endpoints


@pytest.fixture(scope="module")
def network(tmp_path_factory):
    folder = tmp_path_factory.mktemp("route_choice")
    text, endpoints = _build_scenarios()
    raw, clean = folder / "raw.osm", folder / "clean.osm"
    raw.write_text(text)
    clean_osm(str(raw), str(clean))
    return build_graph(str(clean)), endpoints


def _chosen(network, name, reverse=False):
    gb, endpoints = network
    index = {osmid: i for i, osmid in enumerate(gb.node_list)}
    a, b = (index[n] for n in endpoints[name])
    src, tgt = (b, a) if reverse else (a, b)
    result = route_pairs(gb.graph, [(src, tgt)], gb.edges.lengths)
    used = {
        gb.edges.names[eid].rsplit(" | ", 1)[1]
        for eid, flow in enumerate(result.flow_arr) if flow > 0
    }
    assert result.routed == 1
    return used


@pytest.mark.parametrize("reverse", [False, True], ids=["A to B", "B to A"])
@pytest.mark.parametrize(
    "name, expected",
    [(s[0], s[5]) for s in _SCENARIOS] + [(_GATE_SCENARIO, "detour")],
    ids=[s[0] for s in _SCENARIOS] + [_GATE_SCENARIO],
)
def test_route_takes_the_expected_path(network, name, expected, reverse):
    assert _chosen(network, name, reverse) == {expected}


@pytest.mark.parametrize("name, direct_m, direct_tags, detour_m, detour_tags, expected", _SCENARIOS,
                         ids=[s[0] for s in _SCENARIOS])
def test_scenario_geometry_is_as_designed(network, name, direct_m, direct_tags, detour_m, detour_tags, expected):
    gb, _ = network
    lengths = {}
    for eid, edge_name in enumerate(gb.edges.names):
        if edge_name.startswith(f"{name} | "):
            lengths[edge_name.rsplit(" | ", 1)[1]] = gb.edges.lengths[eid]
    assert lengths["detour"] == pytest.approx(detour_m, rel=0.01)
    if "direct" in lengths:
        assert lengths["direct"] == pytest.approx(direct_m, rel=0.01)


def test_competing_paths_are_not_merged_by_simplification(network):
    gb, _ = network
    name = _SCENARIOS[0][0]
    kinds = [n.rsplit(" | ", 1)[1] for n in gb.edges.names if n.startswith(f"{name} | ")]
    assert sorted(kinds) == ["detour", "detour", "direct", "direct"]
