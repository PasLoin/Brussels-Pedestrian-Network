import pytest

from osm_fixtures import cleaned_graph, one_way_per_case_xml

_EXCLUDED = [
    ("footway foot=no", {"highway": "footway", "foot": "no"}),
    ("cycleway foot=no", {"highway": "cycleway", "foot": "no"}),
    ("residential foot=no", {"highway": "residential", "foot": "no"}),
    ("footway foot=NO", {"highway": "footway", "foot": "NO"}),
    ("footway foot=private", {"highway": "footway", "foot": "private"}),
    ("steps foot=private", {"highway": "steps", "foot": "private"}),
    ("pedestrian foot=Private", {"highway": "pedestrian", "foot": "Private"}),
    ("residential foot=private access=yes", {"highway": "residential", "foot": "private", "access": "yes"}),
    ("residential access=no", {"highway": "residential", "access": "no"}),
    ("residential access=private", {"highway": "residential", "access": "private"}),
    ("service access=PRIVATE", {"highway": "service", "access": "PRIVATE"}),
    ("service access=private foot=private", {"highway": "service", "access": "private", "foot": "private"}),
    ("service access=private foot=no", {"highway": "service", "access": "private", "foot": "no"}),
    ("footway access=no foot=use_sidepath", {"highway": "footway", "access": "no", "foot": "use_sidepath"}),
    ("bridleway", {"highway": "bridleway"}),
    ("bridleway foot=private", {"highway": "bridleway", "foot": "private"}),
    ("footway route=ferry", {"highway": "footway", "route": "ferry"}),
    ("service route=FERRY", {"highway": "service", "route": "FERRY"}),
    ("pier foot=yes", {"man_made": "pier", "foot": "yes"}),
    ("building passage foot=yes", {"building": "yes", "foot": "yes"}),
    ("pedestrian area=yes", {"highway": "pedestrian", "area": "yes"}),
    ("pedestrian area=YES", {"highway": "pedestrian", "area": "YES"}),
]

_KEPT = [
    ("residential access=private foot=yes", {"highway": "residential", "access": "private", "foot": "yes"}),
    ("residential access=private foot=designated", {"highway": "residential", "access": "private", "foot": "designated"}),
    ("residential access=no foot=permissive", {"highway": "residential", "access": "no", "foot": "permissive"}),
    ("service access=no foot=YES", {"highway": "service", "access": "no", "foot": "YES"}),
    ("service access=destination", {"highway": "service", "access": "destination"}),
    ("service access=customers", {"highway": "service", "access": "customers"}),
    ("service access=delivery", {"highway": "service", "access": "delivery"}),
    ("residential motor_vehicle=no", {"highway": "residential", "motor_vehicle": "no"}),
    ("residential vehicle=private", {"highway": "residential", "vehicle": "private"}),
    ("footway bicycle=no", {"highway": "footway", "bicycle": "no"}),
    ("bridleway foot=yes", {"highway": "bridleway", "foot": "yes"}),
    ("bridleway foot=designated", {"highway": "bridleway", "foot": "designated"}),
    ("bridleway foot=permissive", {"highway": "bridleway", "foot": "permissive"}),
    ("footway route=hiking", {"highway": "footway", "route": "hiking"}),
    ("footway foot=customers", {"highway": "footway", "foot": "customers"}),
    ("footway foot=destination", {"highway": "footway", "foot": "destination"}),
    ("steps foot=delivery", {"highway": "steps", "foot": "delivery"}),
    ("railway=platform access=private foot=yes", {"railway": "platform", "access": "private", "foot": "yes"}),
    ("pedestrian", {"highway": "pedestrian"}),
    ("pedestrian area=no", {"highway": "pedestrian", "area": "no"}),
    ("footway area=yes", {"highway": "footway", "area": "yes"}),
    ("steps area=yes", {"highway": "steps", "area": "yes"}),
    ("platform area=yes", {"highway": "platform", "area": "yes"}),
]

_ALL = _EXCLUDED + _KEPT


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return cleaned_graph(tmp_path_factory.mktemp("exclusions"), one_way_per_case_xml(_ALL))


@pytest.mark.parametrize("name, tags", _EXCLUDED, ids=[c[0] for c in _EXCLUDED])
def test_way_is_excluded(bundle, name, tags):
    assert name not in bundle.edges.names


@pytest.mark.parametrize("name, tags", _KEPT, ids=[c[0] for c in _KEPT])
def test_way_is_kept_in_both_directions(bundle, name, tags):
    eids = [e for e, n in enumerate(bundle.edges.names) if n == name]
    assert len(eids) == 2
    (u, v), back = bundle.edges.tuples[eids[0]], bundle.edges.tuples[eids[1]]
    assert back == (v, u)


def test_edge_arrays_stay_aligned_after_exclusions(bundle):
    n = bundle.graph.ecount()
    assert n == 2 * len(_KEPT)
    for arr in (
        bundle.edges.tuples, bundle.edges.weights, bundle.edges.lengths,
        bundle.edges.highways, bundle.edges.geoms, bundle.edges.cycleway_nf,
        bundle.edges.foot_tags, bundle.edges.names, bundle.edges.osm_ids,
        bundle.edges.levels,
    ):
        assert len(arr) == n
    assert [(e.source, e.target) for e in bundle.graph.es] == bundle.edges.tuples


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_excluded_way_cuts_the_only_connection(tmp_path):
    xml = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.8500" lon="4.3500" version="1"/>
  <node id="2" lat="50.8500" lon="4.3510" version="1"/>
  <node id="3" lat="50.8500" lon="4.3520" version="1"/>
  <node id="4" lat="50.8500" lon="4.3530" version="1"/>
  <way id="10" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/><tag k="name" v="West"/></way>
  <way id="11" version="1"><nd ref="2"/><nd ref="3"/><tag k="highway" v="service"/><tag k="access" v="private"/><tag k="name" v="Gate"/></way>
  <way id="12" version="1"><nd ref="3"/><nd ref="4"/><tag k="highway" v="footway"/><tag k="name" v="East"/></way>
</osm>
"""
    gb = cleaned_graph(tmp_path, xml)

    index = {osmid: i for i, osmid in enumerate(gb.node_list)}
    paths = gb.graph.get_shortest_paths(index[1], to=index[4], weights="weight", output="epath")
    assert paths == [[]]
    assert "Gate" not in gb.edges.names
