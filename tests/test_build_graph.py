"""Tests for scripts/build_graph.py.

Covers the pure classification helpers and, at the end, a small
end-to-end run of ``build_graph`` on a synthetic OSM XML file that
locks in behaviours fixed in July 2026:

* ``sidewalk=separate`` and the ``sidewalk:left/right/both`` schema
  must count as documented sidewalks.
* one-way streets must be traversable in both directions by the
  pedestrian router (``oneway=yes`` applies to vehicles only).
* the per-street status/penalty is length-weighted: one tagged segment
  can no longer flip a whole multi-segment street to "both" at 100%,
  and untagged streets actually take SIDEWALK_PENALTY_UNKNOWN.
* ``access=private`` roads are excluded from the pedestrian graph
  unless ``foot`` explicitly allows them.
* OSMnx simplification must not merge ways whose name/access/sidewalk
  tags differ (no more tag/name bleeding onto small connector ways).
"""

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
from config import (
    SIDEWALK_PENALTY_NONE,
    SIDEWALK_PENALTY_PARTIAL,
    SIDEWALK_PENALTY_UNKNOWN,
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


# ─────────────────────────────────────────────────────────────────────────────
# _aggregate_sidewalk (length-weighted street aggregation)
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregate_fully_tagged_both():
    info = _aggregate_sidewalk({"both": 500.0})
    assert info.status == "both"
    assert info.penalty == 1.0
    assert info.doc_share == 1.0


def test_aggregate_fully_untagged_street_takes_unknown_penalty():
    """Regression: untagged streets used to escape any penalty because
    they never entered the index (dead SIDEWALK_PENALTY_UNKNOWN branch),
    scoring 84–95% with zero sidewalk information."""
    info = _aggregate_sidewalk({"unknown": 300.0})
    assert info.status == "unknown"
    assert info.penalty == pytest.approx(SIDEWALK_PENALTY_UNKNOWN)
    assert info.doc_share == 0.0


def test_aggregate_one_tagged_segment_does_not_flip_whole_street():
    """Regression (user report): a street with one segment tagged
    ``both`` and a longer untagged segment showed '✅ Deux côtés' at
    ~100%.  Now the untagged length dominates the display status and
    drags the penalty down."""
    info = _aggregate_sidewalk({"both": 50.0, "unknown": 200.0})
    assert info.status == "unknown"          # dominant by length
    expected = (50 * 1.0 + 200 * SIDEWALK_PENALTY_UNKNOWN) / 250
    assert info.penalty == pytest.approx(expected, abs=1e-3)
    assert info.doc_share == pytest.approx(0.2)


def test_aggregate_mixed_documented():
    info = _aggregate_sidewalk({"both": 300.0, "partial": 100.0})
    assert info.status == "both"
    expected = (300 * 1.0 + 100 * SIDEWALK_PENALTY_PARTIAL) / 400
    assert info.penalty == pytest.approx(expected, abs=1e-3)
    assert info.doc_share == 1.0


def test_aggregate_tie_breaks_pessimistically():
    info = _aggregate_sidewalk({"both": 100.0, "none": 100.0})
    assert info.status == "none"
    expected = (100 * 1.0 + 100 * SIDEWALK_PENALTY_NONE) / 200
    assert info.penalty == pytest.approx(expected, abs=1e-3)


def test_aggregate_empty():
    info = _aggregate_sidewalk({})
    assert info == SidewalkInfo("unknown", SIDEWALK_PENALTY_UNKNOWN, 0.0)


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
#
# Layout (all residential unless noted):
#   1──2   Rue Sens Unique     oneway=yes, sidewalk=separate
#   3──4   Rue Moderne         sidewalk:left=yes, sidewalk:right=no
#   5──6──7  Rue Mixte         5-6 sidewalk=both (short), 6-7 untagged (long)
#   8──9   Chemin Privé        access=private (no foot tag) → excluded
#   10─11  Allée Privée Foot   access=private + foot=yes → kept
#   12─13─14  Rue Amont (12-13, sidewalk=both) then Petit Square (13-14,
#            untagged) through a degree-2 node: simplification must NOT
#            merge them, so Petit Square keeps status "unknown".
# ─────────────────────────────────────────────────────────────────────────────

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
    """Regression: with a directed OSMnx graph and no bidirectional=True,
    the router could not walk against traffic on oneway streets."""
    osmid_to_idx = {osmid: i for i, osmid in enumerate(bundle.node_list)}
    n1, n2 = osmid_to_idx[1], osmid_to_idx[2]
    assert (n1, n2) in bundle.edge_tuples
    assert (n2, n1) in bundle.edge_tuples


def test_sidewalk_separate_scores_as_both(bundle):
    info = bundle.street_sidewalk_status["Rue Sens Unique"]
    assert info.status == "both"
    assert info.penalty == 1.0


def test_sidewalk_left_right_schema_is_used(bundle):
    """sidewalk:left=yes + sidewalk:right=no (modern schema, no plain
    ``sidewalk`` tag) must classify as partial — it used to be ignored."""
    info = bundle.street_sidewalk_status["Rue Moderne"]
    assert info.status == "partial"
    assert info.penalty == pytest.approx(SIDEWALK_PENALTY_PARTIAL)


def test_multi_segment_street_is_length_weighted(bundle):
    """Regression (user report): 'Rue Mixte' has one SHORT segment
    tagged sidewalk=both and one LONGER untagged segment.  The old
    set-based rule showed '✅ Deux côtés'; the length-weighted rule
    must report 'unknown' (dominant) with a penalty strictly between
    SIDEWALK_PENALTY_UNKNOWN and 1.0, and a partial doc_share."""
    info = bundle.street_sidewalk_status["Rue Mixte"]
    assert info.status == "unknown"
    assert SIDEWALK_PENALTY_UNKNOWN < info.penalty < 1.0
    assert 0.0 < info.doc_share < 1.0


def test_access_private_is_excluded(bundle):
    """access=private without a foot tag bans pedestrians: the way must
    not enter the routing graph nor the sidewalk index."""
    assert "Chemin Privé" not in bundle.edge_names
    assert "Chemin Privé" not in bundle.street_sidewalk_status


def test_access_private_with_foot_yes_is_kept(bundle):
    """Standard OSM access hierarchy: foot=yes overrides access=private."""
    assert "Allée Privée Foot" in bundle.edge_names


def test_simplification_does_not_merge_different_streets(bundle):
    """Regression (user report, Square de Biarritz): a short untagged
    connector way sharing a degree-2 node with a tagged neighbour used
    to be merged with it during simplification, inheriting its name or
    tags.  With edge_attrs_differ, 'Petit Square' must survive as its
    own street with status 'unknown', not 'both'."""
    assert "Petit Square" in bundle.street_sidewalk_status
    assert bundle.street_sidewalk_status["Petit Square"].status == "unknown"
    assert bundle.street_sidewalk_status["Rue Amont"].status == "both"


def test_surface_and_lit_tags_are_collected(bundle):
    """surface=* / lit=* on pedestrian infra feed the tag-completeness
    penalty — they must survive import and simplification."""
    fw = [i for i, h in enumerate(bundle.edge_highways) if h == "footway"]
    assert fw, "footway missing from test graph"
    assert any(bundle.edge_surfaces[i] == "paving_stones" for i in fw)
    assert any(bundle.edge_lits[i] == "yes" for i in fw)


def test_graph_weights_positive(bundle):
    assert bundle.graph.ecount() == len(bundle.edge_weights)
    assert all(w > 0 and math.isfinite(w) for w in bundle.edge_weights)
