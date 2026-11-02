import pytest

from build_graph import build_graph
from clean_osm import clean_osm

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
]

_ALL = _EXCLUDED + _KEPT


def _osm_xml():
    nodes, ways = [], []
    for i, (name, tags) in enumerate(_ALL):
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
    folder = tmp_path_factory.mktemp("exclusions")
    raw, clean = folder / "raw.osm", folder / "clean.osm"
    raw.write_text(_osm_xml())
    clean_osm(str(raw), str(clean))
    return build_graph(str(clean))


@pytest.mark.parametrize("name, tags", _EXCLUDED, ids=[c[0] for c in _EXCLUDED])
def test_way_is_excluded(bundle, name, tags):
    assert name not in bundle.edge_names


@pytest.mark.parametrize("name, tags", _KEPT, ids=[c[0] for c in _KEPT])
def test_way_is_kept_in_both_directions(bundle, name, tags):
    eids = [e for e, n in enumerate(bundle.edge_names) if n == name]
    assert len(eids) == 2
    (u, v), back = bundle.edge_tuples[eids[0]], bundle.edge_tuples[eids[1]]
    assert back == (v, u)


def test_edge_arrays_stay_aligned_after_exclusions(bundle):
    n = bundle.graph.ecount()
    assert n == 2 * len(_KEPT)
    for arr in (
        bundle.edge_tuples, bundle.edge_weights, bundle.edge_lengths,
        bundle.edge_highways, bundle.edge_geoms, bundle.edge_cycleway_nf,
        bundle.edge_foot_tags, bundle.edge_names, bundle.edge_osm_ids,
        bundle.edge_levels,
    ):
        assert len(arr) == n
    assert [(e.source, e.target) for e in bundle.graph.es] == bundle.edge_tuples


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
    raw, clean = tmp_path / "raw.osm", tmp_path / "clean.osm"
    raw.write_text(xml)
    clean_osm(str(raw), str(clean))
    gb = build_graph(str(clean))

    index = {osmid: i for i, osmid in enumerate(gb.node_list)}
    paths = gb.graph.get_shortest_paths(index[1], to=index[4], weights="weight", output="epath")
    assert paths == [[]]
    assert "Gate" not in gb.edge_names
