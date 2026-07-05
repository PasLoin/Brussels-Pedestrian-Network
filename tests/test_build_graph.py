"""Tests for scripts/build_graph.py.

Covers the pure classification helpers and, at the end, a small
end-to-end run of ``build_graph`` on a synthetic OSM XML file that
locks in the two behaviours fixed in July 2026:

* ``sidewalk=separate`` (and ``sidewalk:left/right/both``) must count
  as documented sidewalks instead of falling through to ``unknown``.
* one-way streets must be traversable in both directions by the
  pedestrian router (``oneway=yes`` applies to vehicles only).
"""

import math

import pytest

from build_graph import (
    _classify_sidewalk,
    _edge_sidewalk_status,
    _first_str,
    _unanimous_str,
    build_graph,
)


# ─────────────────────────────────────────────────────────────────────────────
# _edge_sidewalk_status
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sw, left, right, both, expected",
    [
        # sidewalk=* alone
        ("both", "", "", "", "both"),
        ("yes", "", "", "", "both"),
        ("separate", "", "", "", "both"),      # the July 2026 bug fix
        ("left", "", "", "", "partial"),
        ("right", "", "", "", "partial"),
        ("no", "", "", "", "none"),
        ("", "", "", "", "unknown"),
        # sidewalk:both=*
        ("", "", "", "yes", "both"),
        ("", "", "", "separate", "both"),
        ("", "", "", "no", "none"),
        # sidewalk:left / sidewalk:right combinations
        ("", "yes", "yes", "", "both"),
        ("", "separate", "separate", "", "both"),
        ("", "yes", "no", "", "partial"),
        ("", "separate", "no", "", "partial"),
        ("", "no", "yes", "", "partial"),
        ("", "no", "no", "", "none"),
        # one side documented, the other unknown → inconclusive
        ("", "yes", "", "", "partial"),
        ("", "no", "", "", "unknown"),
        # sidewalk=left + explicit right → both sides covered
        ("left", "", "yes", "", "both"),
    ],
)
def test_edge_sidewalk_status(sw, left, right, both, expected):
    assert _edge_sidewalk_status(sw, left, right, both) == expected


def test_separate_is_never_penalised_as_unknown():
    """Regression: sidewalk=separate used to be classified 'unknown'
    and take the SIDEWALK_PENALTY_UNKNOWN multiplier — punishing the
    best-mapped streets."""
    assert _edge_sidewalk_status("separate", "", "", "") == "both"
    assert _classify_sidewalk(["both"]) == "both"


# ─────────────────────────────────────────────────────────────────────────────
# _classify_sidewalk (street-level aggregation)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "statuses, expected",
    [
        (["both"], "both"),
        (["partial"], "partial"),
        (["none"], "none"),
        ([], "unknown"),
        # priority: both > partial > none
        (["none", "partial", "both"], "both"),
        (["none", "partial"], "partial"),
        (["none", "none"], "none"),
    ],
)
def test_classify_sidewalk(statuses, expected):
    assert _classify_sidewalk(statuses) == expected


# ─────────────────────────────────────────────────────────────────────────────
# _first_str / _unanimous_str (OSMnx simplification quirks)
# ─────────────────────────────────────────────────────────────────────────────

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
    # disagreement → not unanimous
    assert _unanimous_str(["yes", "no"]) == ""
    # partially missing → not unanimous (anti tag-bleeding)
    assert _unanimous_str(["yes", nan]) == ""
    assert _unanimous_str(["yes", None]) == ""
    assert _unanimous_str([nan, nan]) == ""
    assert _unanimous_str(None) == ""


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: build_graph on a tiny synthetic network
# ─────────────────────────────────────────────────────────────────────────────

# NOTE: the two test streets are deliberately DISJOINT (no shared node).
# If they shared an intermediate degree-2 node, OSMnx simplification
# would merge them into a single edge with mixed list-valued tags,
# which is not what these tests exercise.
_TEST_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.8500" lon="4.3500" version="1"/>
  <node id="2" lat="50.8510" lon="4.3510" version="1"/>
  <node id="3" lat="50.8600" lon="4.3600" version="1"/>
  <node id="4" lat="50.8610" lon="4.3610" version="1"/>
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
</osm>
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    path = tmp_path_factory.mktemp("osm") / "mini.osm"
    path.write_text(_TEST_OSM)
    return build_graph(str(path))


def test_oneway_street_is_bidirectional_for_pedestrians(bundle):
    """Regression: with a directed OSMnx graph and no bidirectional=True,
    the router could not walk against traffic on oneway streets."""
    osmid_to_idx = {osmid: i for i, osmid in enumerate(bundle.node_list)}
    n1, n2 = osmid_to_idx[1], osmid_to_idx[2]
    assert (n1, n2) in bundle.edge_tuples
    assert (n2, n1) in bundle.edge_tuples


def test_sidewalk_separate_scores_as_both(bundle):
    assert bundle.street_sidewalk_status["Rue Sens Unique"] == "both"


def test_sidewalk_left_right_schema_is_used(bundle):
    """sidewalk:left=yes + sidewalk:right=no (modern schema, no plain
    ``sidewalk`` tag) must classify as partial — it used to be ignored."""
    assert bundle.street_sidewalk_status["Rue Moderne"] == "partial"


def test_graph_weights_positive(bundle):
    assert bundle.graph.ecount() == len(bundle.edge_weights)
    assert all(w > 0 and math.isfinite(w) for w in bundle.edge_weights)
