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

Missing data is explicitly OUT OF SCOPE and never flagged
------------------------------------------------------------
This check only flags a genuine *contradiction* between two explicitly
tagged values. If a kerb node can't be matched at one (or both)
extremities, or a matched kerb simply has no ``tactile_paving`` tag,
that's a data-completeness gap, not an incoherence — there's nothing to
contradict. Those cases are counted separately in the returned stats
(``kerb_missing`` / ``kerb_untagged``) for visibility but are never
written to the output layer. Revisiting that (e.g. surfacing "kerb data
missing near this crossing" as its own, lower-confidence layer) is a
possible future addition, not part of this check.

Matching crossing ↔ way ↔ kerb is purely geometric (osmium's GeoJSON
export doesn't preserve node/way membership ids), following the same
approach as ``detect_missing_crossings.py`` and
``detect_footway_connectivity.py``: a node that is genuinely a vertex of
a way, or genuinely one of its two endpoints, sits at (near-)zero
distance from it after reprojection, so a small tolerance in metres is
enough to recover the topology.

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
# the crossing node" — the node is expected to be a shared vertex of
# the way, so real matches sit at ~0 m; kept small on purpose to avoid
# picking up an unrelated crossing way from a nearby, separately-mapped
# carriageway.
TACTILE_PAVING_WAY_MATCH_M = float(os.environ.get("TACTILE_PAVING_WAY_MATCH_M", 1.5))

# Tolerance (m) for "this barrier=kerb node sits at this way extremity"
# — again expected to be an exact shared node, small on purpose.
TACTILE_PAVING_KERB_MATCH_M = float(os.environ.get("TACTILE_PAVING_KERB_MATCH_M", 1.0))


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
) -> tuple[gpd.GeoDataFrame, list, STRtree | None]:
    """footway=crossing ways, kept as a GeoDataFrame so endpoints and
    ``@id`` stay attached to each geometry for the STRtree lookup."""
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
    geoms = list(gdf.geometry)
    return gdf, geoms, (STRtree(geoms) if geoms else None)


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
        return {"crossings_in_scope": 0, "flagged": 0}

    with step("load footway=crossing ways"):
        way_gdf, way_geoms, way_tree = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways: {len(way_gdf)}")

    with step("load kerb nodes"):
        kerb_gdf, kerb_geoms, kerb_tree = _load_kerb_nodes(kerbs_geojson_path)
    print(f"  barrier=kerb nodes: {len(kerb_gdf)}")

    rows: list[dict] = []
    n_no_way          = 0
    n_kerb_missing     = 0
    n_kerb_untagged    = 0
    n_value_mismatch   = 0
    n_incorrect_mixed  = 0
    n_ok               = 0

    with step("crossing/kerb coherence loop"):
        for _, node_row in crossing_gdf.iterrows():
            node_pt = node_row.geometry
            crossing_tp = node_row["tactile_paving"]

            way_idx = _nearest_within(node_pt, way_tree, way_geoms, TACTILE_PAVING_WAY_MATCH_M)
            if way_idx is None:
                n_no_way += 1
                continue

            way_row = way_gdf.iloc[way_idx]
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
                continue
            elif reason == "kerb_untagged":
                n_kerb_untagged += 1
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

    n_total = len(crossing_gdf)
    n_flagged = len(rows)
    print(f"  Crossings in scope (yes/no/incorrect):     {n_total}")
    print(f"  Skipped — no footway=crossing way found:   {n_no_way}")
    print(f"  Coherent (not flagged):                    {n_ok}")
    print(f"  Skipped — kerb missing at an extremity:    {n_kerb_missing} (data gap, out of scope)")
    print(f"  Skipped — kerb without tactile_paving:     {n_kerb_untagged} (data gap, out of scope)")
    print(f"  Flagged — kerb value mismatch:              {n_value_mismatch}")
    print(f"  Flagged — incorrect not a yes/no pair:       {n_incorrect_mixed}")
    print(f"  Total flagged:                              {n_flagged}")

    return {
        "crossings_in_scope":       n_total,
        "no_crossing_way_found":    n_no_way,
        "coherent":                 n_ok,
        "kerb_missing":             n_kerb_missing,
        "kerb_untagged":            n_kerb_untagged,
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
