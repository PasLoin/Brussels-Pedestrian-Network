import math

import pytest

from build_graph import (
    SidewalkInfo,
    _aggregate_sidewalk,
    _edge_sidewalk_status,
    _first_str,
    _unanimous_str,
    build_graph,
)


@pytest.mark.parametrize(
    "sw, left, right, both, expected",
    [
        ("both", "", "", "", "both"),
        ("yes", "", "", "", "both"),
        ("separate", "", "", "", "both"),
        ("left", "", "", "", "partial"),
        ("right", "", "", "", "partial"),
        ("no", "", "", "", "none"),
        ("", "", "", "", "unknown"),
        ("", "", "", "yes", "both"),
        ("", "", "", "separate", "both"),
        ("", "", "", "no", "none"),
        ("", "yes", "yes", "", "both"),
        ("", "separate", "separate", "", "both"),
        ("", "yes", "no", "", "partial"),
        ("", "separate", "no", "", "partial"),
        ("", "no", "yes", "", "partial"),
        ("", "no", "no", "", "none"),
        ("", "yes", "", "", "partial"),
        ("", "no", "", "", "unknown"),
        ("left", "", "yes", "", "both"),
    ],
)
def test_edge_sidewalk_status(sw, left, right, both, expected):
    assert _edge_sidewalk_status(sw, left, right, both) == expected


def test_aggregate_fully_tagged_both():
    info = _aggregate_sidewalk({"both": 500.0})
    assert info.status == "both"
    assert info.doc_share == 1.0


def test_aggregate_fully_untagged_street():
    info = _aggregate_sidewalk({"unknown": 300.0})
    assert info.status == "unknown"
    assert info.doc_share == 0.0


def test_aggregate_one_tagged_segment_does_not_flip_whole_street():
    info = _aggregate_sidewalk({"both": 50.0, "unknown": 200.0})
    assert info.status == "unknown"
    assert info.doc_share == pytest.approx(0.2)


def test_aggregate_mixed_documented():
    info = _aggregate_sidewalk({"both": 300.0, "partial": 100.0})
    assert info.status == "both"
    assert info.doc_share == 1.0


def test_aggregate_tie_breaks_pessimistically():
    info = _aggregate_sidewalk({"both": 100.0, "none": 100.0})
    assert info.status == "none"


def test_aggregate_empty():
    info = _aggregate_sidewalk({})
    assert info == SidewalkInfo("unknown", 0.0)


def test_first_str():
    nan = float("nan")
    assert _first_str(None) == ""
    assert _first_str(nan) == ""
    assert _first_str("  yes ") == "yes"
    assert _first_str(["", None, nan, "left"]) == "left"
    assert _first_str([nan, nan]) == ""


def test_unanimous_str():
    nan = float("nan")
    assert _unanimous_str("yes") == "yes"
    assert _unanimous_str(["yes", "yes"]) == "yes"
    assert _unanimous_str(["yes", "no"]) == ""
    assert _unanimous_str(["yes", nan]) == ""
    assert _unanimous_str(["yes", None]) == ""
    assert _unanimous_str([nan, nan]) == ""
    assert _unanimous_str(None) == ""


_TEST_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1"  lat="50.8500" lon="4.3500" version="1"/>
  <node id="2"  lat="50.8510" lon="4.3510" version="1"/>
  <node id="3"  lat="50.8600" lon="4.3600" version="1"/>
  <node id="4"  lat="50.8610" lon="4.3610" version="1"/>
  <node id="5"  lat="50.8700" lon="4.3700" version="1"/>
  <node id="6"  lat="50.8702" lon="4.3702" version="1"/>
  <node id="7"  lat="50.8720" lon="4.3720" version="1"/>
  <node id="8"  lat="50.8800" lon="4.3800" version="1"/>
  <node id="9"  lat="50.8810" lon="4.3810" version="1"/>
  <node id="10" lat="50.8900" lon="4.3900" version="1"/>
  <node id="11" lat="50.8910" lon="4.3910" version="1"/>
  <node id="12" lat="50.9000" lon="4.4000" version="1"/>
  <node id="13" lat="50.9010" lon="4.4010" version="1"/>
  <node id="14" lat="50.9020" lon="4.4020" version="1"/>
  <way id="10" version="1">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="residential"/>
    <tag k="oneway" v="yes"/>
    <tag k="name" v="Rue Sens Unique"/>
    <tag k="sidewalk" v="separate"/>
  </way>
  <way id="11" version="1">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Rue Moderne"/>
    <tag k="sidewalk:left" v="yes"/>
    <tag k="sidewalk:right" v="no"/>
  </way>
  <way id="12" version="1">
    <nd ref="5"/><nd ref="6"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Rue Mixte"/>
    <tag k="sidewalk" v="both"/>
  </way>
  <way id="13" version="1">
    <nd ref="6"/><nd ref="7"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Rue Mixte"/>
  </way>
  <way id="14" version="1">
    <nd ref="8"/><nd ref="9"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Chemin Privé"/>
    <tag k="access" v="private"/>
  </way>
  <way id="15" version="1">
    <nd ref="10"/><nd ref="11"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Allée Privée Foot"/>
    <tag k="access" v="private"/>
    <tag k="foot" v="yes"/>
  </way>
  <way id="16" version="1">
    <nd ref="12"/><nd ref="13"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Rue Amont"/>
    <tag k="sidewalk" v="both"/>
  </way>
  <way id="17" version="1">
    <nd ref="13"/><nd ref="14"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Petit Square"/>
  </way>
  <node id="15" lat="50.9100" lon="4.4100" version="1"/>
  <node id="16" lat="50.9110" lon="4.4110" version="1"/>
  <way id="18" version="1">
    <nd ref="15"/><nd ref="16"/>
    <tag k="highway" v="footway"/>
    <tag k="surface" v="paving_stones"/>
    <tag k="lit" v="yes"/>
  </way>
</osm>
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    path = tmp_path_factory.mktemp("osm") / "mini.osm"
    path.write_text(_TEST_OSM)
    return build_graph(str(path))


def test_oneway_street_is_bidirectional_for_pedestrians(bundle):
    osmid_to_idx = {osmid: i for i, osmid in enumerate(bundle.node_list)}
    n1, n2 = osmid_to_idx[1], osmid_to_idx[2]
    assert (n1, n2) in bundle.edge_tuples
    assert (n2, n1) in bundle.edge_tuples


def test_sidewalk_separate_scores_as_both(bundle):
    info = bundle.street_sidewalk_status["Rue Sens Unique"]
    assert info.status == "both"


def test_sidewalk_left_right_schema_is_used(bundle):
    info = bundle.street_sidewalk_status["Rue Moderne"]
    assert info.status == "partial"


def test_multi_segment_street_is_length_weighted(bundle):
    info = bundle.street_sidewalk_status["Rue Mixte"]
    assert info.status == "unknown"
    assert 0.0 < info.doc_share < 1.0


def test_access_private_is_excluded(bundle):
    assert "Chemin Privé" not in bundle.edge_names
    assert "Chemin Privé" not in bundle.street_sidewalk_status


def test_access_private_with_foot_yes_is_kept(bundle):
    assert "Allée Privée Foot" in bundle.edge_names


def test_simplification_does_not_merge_different_streets(bundle):
    assert "Petit Square" in bundle.street_sidewalk_status
    assert bundle.street_sidewalk_status["Petit Square"].status == "unknown"
    assert bundle.street_sidewalk_status["Rue Amont"].status == "both"


def test_graph_weights_positive(bundle):
    assert bundle.graph.ecount() == len(bundle.edge_weights)
    assert all(w > 0 and math.isfinite(w) for w in bundle.edge_weights)
