"""
Detect ``highway=crossing`` nodes whose ``tactile_paving`` tag is
inconsistent with the ``tactile_paving`` tags carried by the
``barrier=kerb`` nodes at each end of the attached ``footway=crossing``
way.

Background
----------
A crossing is usually mapped as a short ``footway=crossing`` way running
from one kerb to the other. The kerb at each end is its own node,
tagged ``barrier=kerb`` (+ ``kerb=lowered/flush/...``), and can carry its
own ``tactile_paving=yes/no`` — independent of whatever
``tactile_paving`` value sits on the ``highway=crossing`` node itself
(the crossing node is usually a shared vertex on the same way, roughly
midway between the two kerbs).

Three ``tactile_paving`` values on the crossing node are in scope here:

``yes``
    Tactile paving present on **both** sides. Every kerb at the way's
    extremities is expected to also carry ``tactile_paving=yes``.

``no``
    Tactile paving absent on **both** sides. Every kerb is expected to
    carry ``tactile_paving=no``.

``incorrect``
    Tactile paving present on **one side only**. Exactly one kerb is
    expected to carry ``tactile_paving=yes`` and the other
    ``tactile_paving=no`` (a mixed pair) — a pair that's explicitly
    tagged otherwise (both yes, both no) means the ``incorrect`` tag
    doesn't actually describe a one-sided situation and is flagged.

Any other ``tactile_paving`` value on the crossing node (``contrasted``,
``primitive``, etc.) is out of scope for this specific coherence check
and is skipped.

Missing data is explicitly OUT OF SCOPE for the coherence check itself
------------------------------------------------------------------------
This check only *flags* (in ``tactile_paving_issues.geojson``) a genuine
*contradiction* between two explicitly tagged values. If a kerb node
can't be matched at one (or both) extremities, or a matched kerb simply
has no ``tactile_paving`` tag, that's a data-completeness gap, not an
incoherence — there's nothing to contradict, so it's never counted
towards ``flagged`` and never written to ``tactile_paving_issues.geojson``.

Those gaps are still surfaced, just separately and at lower confidence:
each deficient extremity (crossing-side, not way-side) is written as its
own point to ``kerb_issues.geojson``, tagged ``type=kerb_missing`` (no
kerb node matched at all) or ``type=kerb_untagged`` (a kerb was matched
but carries no ``tactile_paving`` value). Crossing-level counts
(``kerb_missing`` / ``kerb_untagged``) and point-level counts
(``kerb_missing_points`` / ``kerb_untagged_points``) are both returned
in stats — the latter can exceed the former since a single crossing can
have both extremities affected.

Matching crossing ↔ way ↔ kerb is purely geometric (osmium's GeoJSON
export doesn't preserve node/way membership ids), following the same
approach as ``detect_missing_crossings.py`` and
``detect_footway_connectivity.py``.

Crossing node → footway=crossing way is matched by VERTEX coincidence
with a TIGHT tolerance (0.5 m by default), not by point-to-line
distance and not by "nearby". A genuinely shared OSM node sits at ~0 m
from the way regardless of which export reads it — a loose tolerance
(anything in the metre-plus range) risks matching a *different*,
separately-mapped crossing a metre or two away instead (e.g. the node
actually sits on a plain sidewalk/service-road, with no dedicated
crossing way of its own, while a real crossing way for a *different*
nearby crossing has a vertex just within a loose tolerance) — this
produced real false positives. Requiring near-exact vertex coincidence
rules that out. If more than one way qualifies (e.g. a refuge-island
node genuinely shared by two crossing segments), the match is treated
as ambiguous and skipped rather than guessed — see
``ambiguous_way_match`` in the returned stats.

The candidate pool itself is restricted to ``highway=footway`` +
``footway=crossing`` ways at load time (``_load_crossing_ways``), and
that tag is re-checked a second time right before a matched way is
used. A ``footway=sidewalk`` (or any other non-crossing footway) that
happens to share a node with the real crossing way — perfectly normal,
legitimate OSM topology where a sidewalk meets a crossing — must never
be treated as if it were the crossing itself.

Way endpoint → kerb node stays a plain nearest-point-within-tolerance
search (also tightened to 0.5 m for the same reason): kerb nodes are
standalone points, so there's no line/vertex distinction to exploit
there, and a genuinely shared node sits at ~0 m regardless.

Inputs
------
* ``highways.geojson``              — slimmed osmium export; used for
  ``highway=crossing`` points (needs a ``tactile_paving`` property).
* ``sidewalk_footways_raw.geojson`` — raw osmium footway export (needs
  ``footway`` + ``@id``); used for ``footway=crossing`` ways.
* ``kerbs_raw.geojson``             — raw osmium export of
  ``barrier=kerb`` nodes (needs ``tactile_paving`` + ``@id``).

Output
------
``tactile_paving_issues.geojson`` — point layer (at the crossing node's
location) with one feature per **flagged** (genuinely contradictory)
crossing — see "Missing data is explicitly OUT OF SCOPE" above.
Properties:
  ``osm_id``      OSM node id of the flagged crossing node
  ``way_osm_id``  OSM way id of the associated footway=crossing (0 if
                  none could be matched)
  ``crossing_tp`` tactile_paving value on the crossing node
  ``kerb1_tp``    tactile_paving value found at the way's first
                  extremity
  ``kerb1_osm_id`` OSM node id of that kerb
  ``kerb2_tp``    tactile_paving value found at the way's second
                  extremity
  ``kerb2_osm_id`` OSM node id of that kerb
  ``reason``      machine-readable reason code, one of:
                    "value_mismatch"      — a matched kerb's value
                                             disagrees with the crossing
                    "incorrect_not_mixed" — tactile_paving=incorrect but
                                             the two kerbs aren't a
                                             yes/no pair

``kerb_issues.geojson`` — point layer, lower confidence, one feature per
**deficient extremity** (not per crossing — a crossing with both sides
affected produces two points). Located at the footway=crossing way's
endpoint (the matched kerb's own position for ``kerb_untagged``, the
expected-but-absent position for ``kerb_missing`` — within
``TACTILE_PAVING_KERB_MATCH_M`` of each other in practice). Properties:
  ``type``             "kerb_missing" (no barrier=kerb node matched at
                        this extremity) or "kerb_untagged" (a kerb was
                        matched but has no tactile_paving tag)
  ``crossing_osm_id``  OSM node id of the associated crossing
  ``way_osm_id``       OSM way id of the associated footway=crossing
  ``kerb_osm_id``      OSM node id of the matched kerb (0 for
                        kerb_missing, since none was matched)
"""

from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.geometry import Point
from shapely.strtree import STRtree

from timing import step

# ── Module-level config ─────────────────────────────────────────────────────

# tactile_paving values on the crossing node this check applies to.
# Anything else (contrasted, primitive, ...) is out of scope and skipped.
_IN_SCOPE_VALUES = frozenset({"yes", "no", "incorrect"})

# Tolerance (m) for "this footway=crossing way is the one attached to
# the crossing node" — a genuinely shared OSM node sits at ~0 m from the
# way (same node, same coordinates, whichever export reads it), so this
# only needs to absorb reprojection float noise, not real distance.
# Kept deliberately tight: a *different*, separately-mapped crossing a
# metre or two away (e.g. across a side street a few metres from the
# crossing over the main road) must never be treated as coincident just
# because it happens to be nearby — that produced real false positives
# with a looser value.
TACTILE_PAVING_WAY_MATCH_M = float(os.environ.get("TACTILE_PAVING_WAY_MATCH_M", 0.5))

# Tolerance (m) for "this barrier=kerb node sits at this way extremity"
# — same reasoning: a genuinely shared node is ~0 m away, so this stays
# tight rather than merely "nearby".
TACTILE_PAVING_KERB_MATCH_M = float(os.environ.get("TACTILE_PAVING_KERB_MATCH_M", 0.5))


# ── String helper ────────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


def _safe_id(val) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


# ── Data loaders ─────────────────────────────────────────────────────────────

def _load_crossing_nodes(highways_path: str) -> gpd.GeoDataFrame:
    """highway=crossing points with an in-scope tactile_paving value."""
    gdf = gpd.read_file(highways_path)
    gdf = gdf[gdf.geometry.geom_type == "Point"].copy()
    for col in ("highway", "tactile_paving"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "crossing") &
        (gdf["tactile_paving"].apply(_safe_str).isin(_IN_SCOPE_VALUES))
    )
    gdf = gdf[mask].copy()
    gdf["tactile_paving"] = gdf["tactile_paving"].apply(_safe_str)
    gdf["osm_id"] = gdf["@id"].apply(_safe_id)
    return gdf.to_crs("EPSG:31370").reset_index(drop=True)


def _load_crossing_ways(
    footways_path: str,
) -> tuple[gpd.GeoDataFrame, STRtree | None, list, list]:
    """footway=crossing ways, plus a VERTEX-level spatial index (every
    individual coordinate of every way, not the lines themselves).

    Matching a crossing node against this vertex index — instead of
    against the lines' overall geometry — is what lets
    ``_match_crossing_way`` require literal vertex coincidence. Two
    footway=crossing ways can legitimately run within a metre or two of
    each other at a busy/complex intersection; a plain point-to-line
    distance check would happily "match" the wrong one just because it
    happens to pass close by, even though the node isn't actually one of
    its vertices.
    """
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "crossing")
    )
    gdf = gdf[mask].reset_index(drop=True)

    vertex_points: list[Point] = []
    vertex_way_idx: list[int] = []
    for w_idx, geom in enumerate(gdf.geometry):
        for coord in geom.coords:
            vertex_points.append(Point(coord))
            vertex_way_idx.append(w_idx)

    vertex_tree = STRtree(vertex_points) if vertex_points else None
    return gdf, vertex_tree, vertex_points, vertex_way_idx


def _load_kerb_nodes(
    kerbs_path: str,
) -> tuple[gpd.GeoDataFrame, list, STRtree | None]:
    """barrier=kerb points, with tactile_paving (may be absent/empty)."""
    try:
        gdf = gpd.read_file(kerbs_path)
    except Exception as e:
        print(f"  {kerbs_path} not available: {e}")
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:31370"), [], None
    gdf = gdf[gdf.geometry.geom_type == "Point"].copy()
    for col in ("barrier", "tactile_paving"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = gdf["barrier"].apply(_safe_str) == "kerb"
    gdf = gdf[mask].copy()
    gdf["tactile_paving"] = gdf["tactile_paving"].apply(_safe_str)
    gdf["osm_id"] = gdf["@id"].apply(_safe_id)
    gdf = gdf.to_crs("EPSG:31370").reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, (STRtree(geoms) if geoms else None)


# ── Matching helpers ─────────────────────────────────────────────────────────
#
# Mirrors the ``min(cands, key=lambda i: geoms[i].distance(pt))`` pattern
# used throughout detect_missing_crossings.py / detect_footway_connectivity.py
# rather than relying on STRtree internals, so index *i* always refers to
# the position in the *geoms* list (and, since every GeoDataFrame here is
# reset_index(drop=True)-ed right after being built, also to gdf.iloc[i]).

def _nearest_within(pt: Point, tree: STRtree | None, geoms: list, tol_m: float):
    """Index into *geoms* of the nearest candidate to *pt* within *tol_m*,
    or None if nothing is close enough."""
    if tree is None:
        return None
    zone = pt.buffer(tol_m)
    cands = list(tree.query(zone))
    if not cands:
        return None
    return min(cands, key=lambda i: geoms[i].distance(pt))


def _match_crossing_way(
    node_pt: Point,
    vertex_tree: STRtree | None,
    vertex_points: list,
    vertex_way_idx: list,
    tol_m: float,
) -> tuple[int | None, bool]:
    """Return (way_idx, ambiguous).

    *way_idx* is the index (into way_gdf) of the footway=crossing way
    that genuinely has *node_pt* as one of its OWN vertices within
    *tol_m* — i.e. the crossing node is a real, shared OSM node on that
    way — or None if no way qualifies.

    This is deliberately a vertex-coincidence check, not a
    point-to-line distance check: a different way that merely runs
    close to the node without the node actually being one of its
    vertices must never be picked up (see the module docstring for the
    real-world case that motivated this).

    *ambiguous* is True when more than one distinct way has a
    qualifying vertex (e.g. a refuge-island node shared by two crossing
    segments). The caller treats this conservatively — it means "can't
    be sure which way owns this node", not "pick the nearest anyway".
    """
    if vertex_tree is None:
        return None, False
    zone = node_pt.buffer(tol_m)
    cand_idxs = list(vertex_tree.query(zone))
    if not cand_idxs:
        return None, False
    best = min(cand_idxs, key=lambda i: vertex_points[i].distance(node_pt))
    distinct_ways = {vertex_way_idx[i] for i in cand_idxs}
    return vertex_way_idx[best], len(distinct_ways) > 1


def _kerb_tp_at(
    endpoint: Point, kerb_gdf: gpd.GeoDataFrame,
    kerb_tree: STRtree | None, kerb_geoms: list,
) -> tuple[str | None, int]:
    """Return (tactile_paving value or None if no kerb matched, osm_id)."""
    idx = _nearest_within(endpoint, kerb_tree, kerb_geoms, TACTILE_PAVING_KERB_MATCH_M)
    if idx is None:
        return None, 0
    row = kerb_gdf.iloc[idx]
    tp = row["tactile_paving"] or ""
    return (tp if tp else ""), int(row["osm_id"])


def _is_footway_crossing(way_row) -> bool:
    """True if *way_row* is genuinely tagged highway=footway +
    footway=crossing. Used as a defense-in-depth re-check right before a
    matched way is actually used — see the module docstring ("The
    candidate pool itself...") for why this matters even though
    way_gdf is already filtered to this at load time."""
    return (
        _safe_str(way_row.get("highway")) == "footway" and
        _safe_str(way_row.get("footway")) == "crossing"
    )


def _classify(crossing_tp: str, tp1: str | None, tp2: str | None) -> str | None:
    """Return a reason code if the pair (tp1, tp2) is inconsistent with
    *crossing_tp*, or None if it's coherent."""
    if tp1 is None or tp2 is None:
        return "kerb_missing"
    if tp1 == "" or tp2 == "":
        return "kerb_untagged"
    if crossing_tp in ("yes", "no"):
        if tp1 != crossing_tp or tp2 != crossing_tp:
            return "value_mismatch"
        return None
    # crossing_tp == "incorrect" — expect exactly one yes + one no.
    if {tp1, tp2} != {"yes", "no"}:
        return "incorrect_not_mixed"
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def detect_tactile_paving_issues(
    highways_geojson_path: str = "highways.geojson",
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    kerbs_geojson_path:    str = "kerbs_raw.geojson",
) -> dict:
    """Detect tactile_paving incoherences between crossing nodes and the
    kerb nodes at each end of their attached footway=crossing way.

    Returns a statistics dict for stats.json.
    """
    print("Detecting tactile_paving incoherences (crossing ↔ kerb)...")
    print(
        f"  Way match tolerance: {TACTILE_PAVING_WAY_MATCH_M} m | "
        f"Kerb match tolerance: {TACTILE_PAVING_KERB_MATCH_M} m"
    )

    with step("load crossing nodes with tactile_paving"):
        crossing_gdf = _load_crossing_nodes(highways_geojson_path)
    print(f"  highway=crossing nodes with in-scope tactile_paving "
          f"(yes/no/incorrect): {len(crossing_gdf)}")

    if crossing_gdf.empty:
        print("  Nothing to analyse — skipping.")
        _write_empty_output()
        _write_empty_kerb_issues_output()
        return {"crossings_in_scope": 0, "flagged": 0}

    with step("load footway=crossing ways"):
        way_gdf, vertex_tree, vertex_points, vertex_way_idx = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways: {len(way_gdf)} ({len(vertex_points)} vertices indexed)")

    with step("load kerb nodes"):
        kerb_gdf, kerb_geoms, kerb_tree = _load_kerb_nodes(kerbs_geojson_path)
    print(f"  barrier=kerb nodes: {len(kerb_gdf)}")

    rows: list[dict] = []
    kerb_issue_rows: list[dict] = []
    n_no_way          = 0
    n_ambiguous_way    = 0
    n_kerb_missing     = 0
    n_kerb_untagged    = 0
    n_kerb_missing_points  = 0
    n_kerb_untagged_points = 0
    n_value_mismatch   = 0
    n_incorrect_mixed  = 0
    n_ok               = 0

    with step("crossing/kerb coherence loop"):
        for _, node_row in crossing_gdf.iterrows():
            node_pt = node_row.geometry
            crossing_tp = node_row["tactile_paving"]

            way_idx, ambiguous = _match_crossing_way(
                node_pt, vertex_tree, vertex_points, vertex_way_idx,
                TACTILE_PAVING_WAY_MATCH_M,
            )
            if way_idx is None:
                n_no_way += 1
                continue
            if ambiguous:
                # More than one footway=crossing way has a vertex here —
                # can't be sure which one actually owns this crossing
                # node, so don't guess (that's exactly the kind of false
                # match this check exists to avoid).
                n_ambiguous_way += 1
                continue

            way_row = way_gdf.iloc[way_idx]

            # Defense in depth: way_gdf is already filtered to
            # highway=footway + footway=crossing when it's loaded (see
            # _load_crossing_ways), so this should always hold. Re-check
            # it here anyway, right before the way is actually used, so
            # a footway=sidewalk (or any other non-crossing way) can
            # never silently slip through — e.g. if that upstream filter
            # is ever loosened, or on malformed/unexpected input data.
            if not _is_footway_crossing(way_row):
                n_no_way += 1
                continue

            way_geom = way_row.geometry
            p1 = Point(way_geom.coords[0])
            p2 = Point(way_geom.coords[-1])

            tp1, kerb1_id = _kerb_tp_at(p1, kerb_gdf, kerb_tree, kerb_geoms)
            tp2, kerb2_id = _kerb_tp_at(p2, kerb_gdf, kerb_tree, kerb_geoms)

            reason = _classify(crossing_tp, tp1, tp2)
            if reason is None:
                n_ok += 1
                continue

            if reason == "kerb_missing":
                n_kerb_missing += 1
                # One point per extremity that has no matched kerb node
                # at all — located at the way's endpoint (the "expected"
                # kerb position), since there's no real kerb to point to.
                for pt, tp in ((p1, tp1), (p2, tp2)):
                    if tp is None:
                        n_kerb_missing_points += 1
                        kerb_issue_rows.append({
                            "geometry":        pt,
                            "type":            "kerb_missing",
                            "crossing_osm_id": int(node_row["osm_id"]),
                            "way_osm_id":       _safe_id(way_row.get("@id")),
                            "kerb_osm_id":      0,
                        })
                continue
            elif reason == "kerb_untagged":
                n_kerb_untagged += 1
                # One point per extremity whose matched kerb node has no
                # tactile_paving value at all.
                for pt, tp, kid in ((p1, tp1, kerb1_id), (p2, tp2, kerb2_id)):
                    if tp == "":
                        n_kerb_untagged_points += 1
                        kerb_issue_rows.append({
                            "geometry":        pt,
                            "type":            "kerb_untagged",
                            "crossing_osm_id": int(node_row["osm_id"]),
                            "way_osm_id":       _safe_id(way_row.get("@id")),
                            "kerb_osm_id":      kid,
                        })
                continue
            elif reason == "value_mismatch":
                n_value_mismatch += 1
            else:
                n_incorrect_mixed += 1

            rows.append({
                "geometry":     node_pt,
                "osm_id":       int(node_row["osm_id"]),
                "way_osm_id":   _safe_id(way_row.get("@id")),
                "crossing_tp":  crossing_tp,
                "kerb1_tp":     tp1 or "",
                "kerb1_osm_id": kerb1_id,
                "kerb2_tp":     tp2 or "",
                "kerb2_osm_id": kerb2_id,
                "reason":       reason,
            })

    with step("write tactile_paving_issues.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = _empty_gdf()
        out_gdf.to_file("tactile_paving_issues.geojson", driver="GeoJSON")

    with step("write kerb_issues.geojson"):
        if kerb_issue_rows:
            kerb_out_gdf = gpd.GeoDataFrame(kerb_issue_rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            kerb_out_gdf = _empty_kerb_issues_gdf()
        kerb_out_gdf.to_file("kerb_issues.geojson", driver="GeoJSON")

    n_total = len(crossing_gdf)
    n_flagged = len(rows)
    print(f"  Crossings in scope (yes/no/incorrect):     {n_total}")
    print(f"  Skipped — no footway=crossing way found:   {n_no_way}")
    print(f"  Skipped — ambiguous way match (≥2 ways):   {n_ambiguous_way}")
    print(f"  Coherent (not flagged):                    {n_ok}")
    print(f"  Skipped — kerb missing at an extremity:    {n_kerb_missing} (data gap, not flagged — see kerb_issues.geojson)")
    print(f"  Skipped — kerb without tactile_paving:     {n_kerb_untagged} (data gap, not flagged — see kerb_issues.geojson)")
    print(f"  Kerb-issue points — kerb absent:            {n_kerb_missing_points}")
    print(f"  Kerb-issue points — kerb sans tactile_paving:{n_kerb_untagged_points}")
    print(f"  Flagged — kerb value mismatch:              {n_value_mismatch}")
    print(f"  Flagged — incorrect not a yes/no pair:       {n_incorrect_mixed}")
    print(f"  Total flagged:                              {n_flagged}")

    return {
        "crossings_in_scope":       n_total,
        "no_crossing_way_found":    n_no_way,
        "ambiguous_way_match":      n_ambiguous_way,
        "coherent":                 n_ok,
        "kerb_missing":             n_kerb_missing,
        "kerb_untagged":            n_kerb_untagged,
        "kerb_missing_points":      n_kerb_missing_points,
        "kerb_untagged_points":     n_kerb_untagged_points,
        "value_mismatch":           n_value_mismatch,
        "incorrect_not_mixed":      n_incorrect_mixed,
        "flagged":                  n_flagged,
    }


def _empty_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"geometry": None, "osm_id": 0, "way_osm_id": 0,
          "crossing_tp": "", "kerb1_tp": "", "kerb1_osm_id": 0,
          "kerb2_tp": "", "kerb2_osm_id": 0, "reason": ""}],
        crs="EPSG:4326",
    )


def _write_empty_output() -> None:
    _empty_gdf().to_file("tactile_paving_issues.geojson", driver="GeoJSON")


def _empty_kerb_issues_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"geometry": None, "type": "", "crossing_osm_id": 0,
          "way_osm_id": 0, "kerb_osm_id": 0}],
        crs="EPSG:4326",
    )


def _write_empty_kerb_issues_output() -> None:
    _empty_kerb_issues_gdf().to_file("kerb_issues.geojson", driver="GeoJSON")
