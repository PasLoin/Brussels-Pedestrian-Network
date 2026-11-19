from pathlib import Path

import pytest
import yaml

from config import EDGE_COST, PED_HIGHWAY_TYPES
from osm_fixtures import cleaned_graph, one_way_per_case_xml

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


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return cleaned_graph(tmp_path_factory.mktemp("costs"), one_way_per_case_xml([c[:2] for c in _CASES]))


def _edges_named(bundle, name):
    return [
        eid for eid, edge_name in enumerate(bundle.edges.names) if edge_name == name
    ]


@pytest.mark.parametrize("name, tags, cost, cycleway_nf", _CASES, ids=[c[0] for c in _CASES])
def test_weight_is_length_times_cost(bundle, name, tags, cost, cycleway_nf):
    eids = _edges_named(bundle, name)

    assert len(eids) == 2
    for eid in eids:
        assert bundle.edges.lengths[eid] > 50.0
        assert bundle.edges.weights[eid] / bundle.edges.lengths[eid] == pytest.approx(cost, abs=1e-9)


@pytest.mark.parametrize("name, tags, cost, cycleway_nf", _CASES, ids=[c[0] for c in _CASES])
def test_cycleway_no_foot_flag(bundle, name, tags, cost, cycleway_nf):
    for eid in _edges_named(bundle, name):
        assert bundle.edges.cycleway_nf[eid] is cycleway_nf


@pytest.mark.parametrize("name, tags, cost, cycleway_nf", _CASES, ids=[c[0] for c in _CASES])
def test_highway_and_foot_are_recorded(bundle, name, tags, cost, cycleway_nf):
    expected_hw = _EXPECTED_HIGHWAY.get(name, tags.get("highway"))
    expected_foot = tags.get("foot", "").lower()
    for eid in _edges_named(bundle, name):
        assert bundle.edges.highways[eid] == expected_hw
        assert bundle.edges.foot_tags[eid] == expected_foot


def test_both_directions_have_the_same_weight(bundle):
    for name, _, _, _ in _CASES:
        first, second = (bundle.edges.weights[e] for e in _edges_named(bundle, name))
        assert first == pytest.approx(second)


def test_igraph_weights_match_bundle(bundle):
    assert bundle.graph.es["weight"] == bundle.edges.weights
    assert bundle.graph.es["length"] == bundle.edges.lengths


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
