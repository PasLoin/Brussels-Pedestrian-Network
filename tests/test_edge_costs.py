from pathlib import Path

import pytest
import yaml

from build_graph import build_graph
from clean_osm import clean_osm
from config import EDGE_COST, PED_HIGHWAY_TYPES

_CASES = [
    ("footway", {"highway": "footway"}, 1.0, False),
    ("pedestrian", {"highway": "pedestrian"}, 1.0, False),
    ("corridor", {"highway": "corridor"}, 1.0, False),
    ("corridor foot=yes", {"highway": "corridor", "foot": "yes"}, 1.0, False),
    ("corridor foot=permissive", {"highway": "corridor", "foot": "permissive"}, 1.2, False),
    ("corridor foot=PERMISSIVE", {"highway": "corridor", "foot": "PERMISSIVE"}, 1.2, False),
    ("path", {"highway": "path"}, 1.2, False),
    ("track", {"highway": "track"}, 1.2, False),
    ("living_street", {"highway": "living_street"}, 1.2, False),
    ("bridleway foot=yes", {"highway": "bridleway", "foot": "yes"}, 1.2, False),
    ("bridleway foot=designated", {"highway": "bridleway", "foot": "designated"}, 1.2, False),
    ("elevator", {"highway": "elevator"}, 1.4, False),
    ("steps", {"highway": "steps"}, 1.5, False),
    ("platform", {"highway": "platform"}, 1.6, False),
    ("railway=platform", {"railway": "platform"}, 1.6, False),
    ("public_transport=platform", {"public_transport": "platform"}, 1.6, False),
    ("cycleway foot=yes", {"highway": "cycleway", "foot": "yes"}, 1.0, False),
    ("cycleway foot=designated", {"highway": "cycleway", "foot": "designated"}, 1.0, False),
    ("cycleway foot=permissive", {"highway": "cycleway", "foot": "permissive"}, 1.0, False),
    ("cycleway foot=YES", {"highway": "cycleway", "foot": "YES"}, 1.0, False),
    ("cycleway", {"highway": "cycleway"}, 1.8, True),
    ("cycleway foot=use_sidepath", {"highway": "cycleway", "foot": "use_sidepath"}, 1.8, True),
    ("residential", {"highway": "residential"}, 2.0, False),
    ("service", {"highway": "service"}, 2.0, False),
    ("unclassified", {"highway": "unclassified"}, 2.2, False),
    ("tertiary", {"highway": "tertiary"}, 3.5, False),
    ("tertiary_link", {"highway": "tertiary_link"}, 3.5, False),
    ("secondary", {"highway": "secondary"}, 5.0, False),
    ("secondary_link", {"highway": "secondary_link"}, 5.0, False),
    ("primary", {"highway": "primary"}, 8.0, False),
    ("primary_link", {"highway": "primary_link"}, 8.0, False),
    ("construction foot=yes", {"highway": "construction", "foot": "yes"}, 2.5, False),
    ("unknown highway", {"highway": "road"}, 2.5, False),
]

_EXPECTED_HIGHWAY = {
    "railway=platform": "platform",
    "public_transport=platform": "platform",
}


def _osm_xml():
    nodes, ways = [], []
    for i, (name, tags, _, _) in enumerate(_CASES):
        lat = 50.80 + i * 0.002
        a, b = 2 * i + 1, 2 * i + 2
        nodes.append(f'<node id="{a}" lat="{lat:.4f}" lon="4.3000" version="1"/>')
        nodes.append(f'<node id="{b}" lat="{lat:.4f}" lon="4.3010" version="1"/>')
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        ways.append(
            f'<way id="{100 + i}" version="1"><nd ref="{a}"/><nd ref="{b}"/>'
            f'<tag k="name" v="{name}"/>{tag_xml}</way>'
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"test\">\n"
        + "\n".join(nodes) + "\n" + "\n".join(ways) + "\n</osm>\n"
    )


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    folder = tmp_path_factory.mktemp("costs")
    raw, clean = folder / "raw.osm", folder / "clean.osm"
    raw.write_text(_osm_xml())
    clean_osm(str(raw), str(clean))
    return build_graph(str(clean))


def _edges_named(bundle, name):
    return [
        eid for eid, edge_name in enumerate(bundle.edge_names) if edge_name == name
    ]


@pytest.mark.parametrize("name, tags, cost, cycleway_nf", _CASES, ids=[c[0] for c in _CASES])
def test_weight_is_length_times_cost(bundle, name, tags, cost, cycleway_nf):
    eids = _edges_named(bundle, name)

    assert len(eids) == 2
    for eid in eids:
        assert bundle.edge_lengths[eid] > 50.0
        assert bundle.edge_weights[eid] / bundle.edge_lengths[eid] == pytest.approx(cost, abs=1e-9)


@pytest.mark.parametrize("name, tags, cost, cycleway_nf", _CASES, ids=[c[0] for c in _CASES])
def test_cycleway_no_foot_flag(bundle, name, tags, cost, cycleway_nf):
    for eid in _edges_named(bundle, name):
        assert bundle.edge_cycleway_nf[eid] is cycleway_nf


@pytest.mark.parametrize("name, tags, cost, cycleway_nf", _CASES, ids=[c[0] for c in _CASES])
def test_highway_and_foot_are_recorded(bundle, name, tags, cost, cycleway_nf):
    expected_hw = _EXPECTED_HIGHWAY.get(name, tags.get("highway"))
    expected_foot = tags.get("foot", "").lower()
    for eid in _edges_named(bundle, name):
        assert bundle.edge_highways[eid] == expected_hw
        assert bundle.edge_foot_tags[eid] == expected_foot


def test_both_directions_have_the_same_weight(bundle):
    for name, _, _, _ in _CASES:
        first, second = (bundle.edge_weights[e] for e in _edges_named(bundle, name))
        assert first == pytest.approx(second)


def test_igraph_weights_match_bundle(bundle):
    assert bundle.graph.es["weight"] == bundle.edge_weights
    assert bundle.graph.es["length"] == bundle.edge_lengths


def _routing_highway_types():
    workflow = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "build.yml"
    tokens = yaml.safe_load(workflow.read_text())["env"]["HIGHWAY_TYPES_ROUTING"].split()
    return {t.split("=", 1)[1] for t in tokens if t.startswith("w/highway=")}


def test_every_routed_highway_type_has_an_explicit_cost():
    missing = {hw for hw in _routing_highway_types() if hw != "cycleway" and hw not in EDGE_COST}
    assert missing == set()


def test_every_pedestrian_type_has_an_explicit_cost():
    assert PED_HIGHWAY_TYPES - set(EDGE_COST) == set()


def test_cycleway_cost_is_only_decided_by_the_foot_tag():
    assert "cycleway" not in EDGE_COST
    assert "cycleway" in _routing_highway_types()
