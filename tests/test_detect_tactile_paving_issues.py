"""Tests for scripts/detect_tactile_paving_issues.py — coherence check
between a highway=crossing node's tactile_paving tag and the
tactile_paving tags on the barrier=kerb nodes at each end of its
attached footway=crossing way."""

import json
import math

from shapely.geometry import Point
from shapely.strtree import STRtree

from detect_tactile_paving_issues import (
    _classify,
    _is_footway_crossing,
    _match_crossing_way,
    detect_tactile_paving_issues,
)

LAT0 = 50.85
LON0 = 4.35

_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def _xy(x_m: float, y_m: float) -> list[float]:
    """Convert local ENU metre offsets (from LON0, LAT0) to [lon, lat]."""
    return [LON0 + x_m / _M_PER_DEG_LON, LAT0 + y_m / _M_PER_DEG_LAT]


def _write_geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _crossing_feature(x_m, y_m, tactile_paving, fid):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": {"highway": "crossing", "tactile_paving": tactile_paving, "@id": fid},
    }


def _crossing_way_feature(x0, y0, xc, yc, x1, y1, fid):
    """A footway=crossing way running kerb → crossing node → kerb, so the
    crossing node is an exact vertex of the line (as in real OSM data)."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [_xy(x0, y0), _xy(xc, yc), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "crossing", "@id": fid},
    }


def _crossing_way_2pt_feature(x0, y0, x1, y1, fid):
    """A plain 2-vertex footway=crossing way (e.g. a boulevard split into
    two segments meeting exactly at the crossing node)."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [_xy(x0, y0), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "crossing", "@id": fid},
    }


def _sidewalk_way_feature(x0, y0, x1, y1, fid):
    """A footway=sidewalk way — NOT a crossing, even though it can
    legitimately share a node with one (e.g. where a sidewalk meets a
    crossing)."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [_xy(x0, y0), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "sidewalk", "@id": fid},
    }


def _kerb_feature(x_m, y_m, tactile_paving, fid):
    props = {"barrier": "kerb", "@id": fid}
    if tactile_paving is not None:
        props["tactile_paving"] = tactile_paving
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": props,
    }


# ── Pure classification logic ───────────────────────────────────────────────

def test_classify_yes_coherent_when_both_kerbs_yes():
    assert _classify("yes", "yes", "yes") is None


def test_classify_yes_flagged_when_one_kerb_no():
    assert _classify("yes", "yes", "no") == "value_mismatch"


def test_classify_no_coherent_when_both_kerbs_no():
    assert _classify("no", "no", "no") is None


def test_classify_incorrect_coherent_when_kerbs_are_a_mixed_pair():
    assert _classify("incorrect", "yes", "no") is None
    assert _classify("incorrect", "no", "yes") is None


def test_classify_incorrect_flagged_when_kerbs_not_mixed():
    assert _classify("incorrect", "yes", "yes") == "incorrect_not_mixed"
    assert _classify("incorrect", "no", "no") == "incorrect_not_mixed"


def test_classify_missing_kerb_is_a_reason_code_but_not_flagged_by_caller():
    """_classify itself still reports the pair as inconsistent (there's
    nothing to compare) — it's detect_tactile_paving_issues() that
    decides not to write it to the output layer, see the pipeline test
    below."""
    assert _classify("yes", "yes", None) == "kerb_missing"
    assert _classify("incorrect", None, None) == "kerb_missing"


def test_classify_untagged_kerb_is_a_reason_code_but_not_flagged_by_caller():
    assert _classify("no", "no", "") == "kerb_untagged"


# ── Full pipeline (geometric matching + GeoJSON I/O) ───────────────────────

def test_coherent_yes_crossing_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
        _kerb_feature(3, 0, "yes", fid=202),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["coherent"] == 1
    assert stats["flagged"] == 0


def test_no_crossing_with_mismatched_kerb_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=2),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=102),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no",  fid=203),
        _kerb_feature(3, 0, "yes", fid=204),  # should be "no" too
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 1
    assert stats["value_mismatch"] == 1

    out = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())
    props = out["features"][0]["properties"]
    assert props["osm_id"] == 2
    assert props["reason"] == "value_mismatch"
    assert props["kerb1_tp"] == "no"
    assert props["kerb2_tp"] == "yes"


def test_incorrect_crossing_with_mixed_kerbs_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=3),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=103),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=205),
        _kerb_feature(3, 0, "no",  fid=206),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["coherent"] == 1
    assert stats["flagged"] == 0


def test_incorrect_crossing_with_both_kerbs_yes_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=4),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=104),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=207),
        _kerb_feature(3, 0, "yes", fid=208),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 1
    assert stats["incorrect_not_mixed"] == 1


def test_missing_kerb_at_one_extremity_is_not_flagged(tmp_path, monkeypatch):
    """Out of scope for now: a missing kerb node is a data gap, not a
    contradiction — don't flag it, but keep it visible in stats."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=5),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=105),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=209),
        # no kerb node at the other extremity
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["kerb_missing"] == 1

    out = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())
    # Empty-output placeholder feature only, no real flagged feature.
    assert all(f["properties"].get("osm_id", 0) != 5 for f in out["features"])


def test_kerb_without_tactile_paving_tag_is_not_flagged(tmp_path, monkeypatch):
    """Out of scope for now: a kerb with no tactile_paving tag at all is
    a data gap, not a contradiction — don't flag it, but keep it visible
    in stats."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=6),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=106),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no", fid=210),
        _kerb_feature(3, 0, None,  fid=211),  # kerb exists, no tactile_paving tag
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["kerb_untagged"] == 1


def test_out_of_scope_tactile_paving_value_is_skipped(tmp_path, monkeypatch):
    """tactile_paving=contrasted/primitive/etc. isn't yes/no/incorrect —
    this check doesn't apply and the node is silently ignored."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "contrasted", fid=7),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=107),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no",  fid=212),
        _kerb_feature(3, 0, "yes", fid=213),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 0
    assert stats["flagged"] == 0


def test_crossing_without_nearby_crossing_way_is_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=8),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        # Way is far away (200 m) — not attached to this crossing node.
        _crossing_way_feature(197, 200, 200, 200, 203, 200, fid=108),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=214),
        _kerb_feature(3, 0, "yes", fid=215),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["no_crossing_way_found"] == 1
    assert stats["flagged"] == 0


# ── Vertex-coincidence matching (not just spatial proximity) ───────────────
#
# Regression coverage for a real false positive: a footway=crossing that
# runs very close (but not coincident) to an unrelated, separately-mapped
# way must never be matched as "the" crossing way just because a plain
# point-to-line distance check would have found it within tolerance.

def test_match_crossing_way_ignores_a_nearby_but_unrelated_way():
    """A distractor way passes 0.3 m from the node (well inside the old
    line-distance tolerance) but the node isn't one of ITS vertices —
    its own vertices are 10 m away. The real crossing way genuinely has
    the node as a vertex. Only the real way must match."""
    real_way    = [(-3, 0), (0, 0), (3, 0)]        # node (0,0) is a real vertex
    distractor  = [(-10, 0.3), (10, 0.3)]           # passes close, but no vertex near (0,0)

    vertex_points, vertex_way_idx = [], []
    for w_idx, coords in enumerate([real_way, distractor]):
        for c in coords:
            vertex_points.append(Point(c))
            vertex_way_idx.append(w_idx)
    tree = STRtree(vertex_points)

    way_idx, ambiguous = _match_crossing_way(
        Point(0, 0), tree, vertex_points, vertex_way_idx, tol_m=1.5,
    )
    assert way_idx == 0        # the real way, not the distractor
    assert ambiguous is False


def test_match_crossing_way_finds_nothing_when_only_the_distractor_is_close():
    """Same distractor, but this time there's no real crossing way at
    all near this node — the old line-distance check would have wrongly
    matched the distractor anyway (0.3 m < old tolerance); the
    vertex-based check must correctly find no match."""
    distractor = [(-10, 0.3), (10, 0.3)]

    vertex_points = [Point(c) for c in distractor]
    vertex_way_idx = [0, 0]
    tree = STRtree(vertex_points)

    way_idx, ambiguous = _match_crossing_way(
        Point(0, 0), tree, vertex_points, vertex_way_idx, tol_m=1.5,
    )
    assert way_idx is None
    assert ambiguous is False


def test_match_crossing_way_flags_ambiguous_when_two_ways_share_the_vertex():
    """A node genuinely shared by two footway=crossing ways (e.g. a
    refuge-island node) — both matches are legitimate, so this must be
    reported as ambiguous rather than silently picking one."""
    way_a = [(-3, 0), (0, 0)]
    way_b = [(0, 0), (3, 0)]

    vertex_points, vertex_way_idx = [], []
    for w_idx, coords in enumerate([way_a, way_b]):
        for c in coords:
            vertex_points.append(Point(c))
            vertex_way_idx.append(w_idx)
    tree = STRtree(vertex_points)

    way_idx, ambiguous = _match_crossing_way(
        Point(0, 0), tree, vertex_points, vertex_way_idx, tol_m=1.5,
    )
    assert way_idx in (0, 1)
    assert ambiguous is True


def test_nearby_unrelated_way_does_not_produce_a_false_positive_end_to_end(
    tmp_path, monkeypatch,
):
    """End-to-end regression: a crossing node with tactile_paving=no
    sits right next to an unrelated footway=crossing way whose own
    (far-away) kerbs are tagged "yes" — a value that would flag a false
    mismatch if that unrelated way got matched. There's no real
    footway=crossing way for this node at all, so it must be skipped,
    not flagged."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=9),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        # Passes ~0.3 m from the node — close enough to fool a plain
        # line-distance check — but its own vertices (only at the two
        # far ends) are nowhere near (0, 0).
        _crossing_way_2pt_feature(-10, 0.3, 10, 0.3, fid=109),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-10, 0.3, "yes", fid=216),
        _kerb_feature(10, 0.3, "yes", fid=217),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["no_crossing_way_found"] == 1


def test_ambiguous_way_match_is_skipped_not_flagged_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=10),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        # Two footway=crossing ways genuinely sharing the (0,0) vertex.
        _crossing_way_2pt_feature(-3, 0, 0, 0, fid=110),
        _crossing_way_2pt_feature(0, 0, 3, 0, fid=111),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=218),
        _kerb_feature(3, 0, "yes", fid=219),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["ambiguous_way_match"] == 1


# ── Way must genuinely be footway=crossing, not just footway=sidewalk ──────
#
# Regression coverage for a real false positive spotted in JOSM: a node
# that legitimately sits where a footway=sidewalk meets the crossing was
# being treated as if the sidewalk itself were the crossing way.

def test_is_footway_crossing():
    assert _is_footway_crossing({"highway": "footway", "footway": "crossing"}) is True
    assert _is_footway_crossing({"highway": "footway", "footway": "sidewalk"}) is False
    assert _is_footway_crossing({"highway": "footway", "footway": ""}) is False
    assert _is_footway_crossing({"highway": "path", "footway": "crossing"}) is False
    assert _is_footway_crossing({}) is False


def test_sidewalk_way_sharing_the_crossing_nodes_vertex_is_never_used(
    tmp_path, monkeypatch,
):
    """A footway=sidewalk way has a vertex exactly at the crossing
    node's location (normal topology: the sidewalk meets the crossing
    there) — it must never be picked up as "the" crossing way, even
    though it passes the vertex-coincidence check that a plain
    footway=crossing way would."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=11),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        # Only a sidewalk here — no footway=crossing way at all for
        # this node, mirroring the real-world case in JOSM.
        _sidewalk_way_feature(0, 0, 10, 5, fid=112),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no", fid=220),
        _kerb_feature(3, 0, "no", fid=221),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["no_crossing_way_found"] == 1

# ── Tolerance must be tight (near-exact), not merely "nearby" ──────────────
#
# Regression coverage for a real false positive spotted in JOSM: a
# highway=crossing node with no dedicated footway=crossing way of its
# own (it just sits on a plain sidewalk/service-road) was matched to a
# genuinely different, separately-mapped crossing ~1.2 m away, because
# the old tolerance (1.5 m) was loose enough to treat "nearby" as if it
# meant "the same shared node".

def test_a_different_nearby_crossing_does_not_hijack_the_match(tmp_path, monkeypatch):
    """No footway=crossing way actually touches this node (it's on a
    plain sidewalk, matching the real-world case) — but a genuine
    footway=crossing way for a DIFFERENT nearby crossing has a vertex
    1.2 m away. That's a different physical node, not this one, and
    must not be matched."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=12),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        # The node's own path: a sidewalk, not a crossing.
        _sidewalk_way_feature(0, 0, -8, 4, fid=113),
        # A real footway=crossing way — but for a different crossing,
        # 1.2 m away (well within the old 1.5 m tolerance, outside the
        # new 0.5 m one).
        _crossing_way_2pt_feature(1.2, -3, 1.2, 3, fid=114),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(1.2, -3, "no", fid=222),
        _kerb_feature(1.2, 3, "no", fid=223),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["no_crossing_way_found"] == 1
