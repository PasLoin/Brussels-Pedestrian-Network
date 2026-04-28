"""
Export sidewalk tag status on road edges — lightweight layer for QA.

Produces ``sidewalk_roads.geojson`` with two properties per feature:

* ``sw`` — classified sidewalk status: ``separate``, ``both``,
  ``left``, ``right``, ``no``, or ``unknown``.
* ``name`` — street name (for popups).

Only road types from ``ROAD_TYPES_SIDEWALK_EXPECTED`` are included
(residential, tertiary, secondary, primary…).  Directed edges are
deduplicated so each physical road segment appears once.

This module is intentionally separate from ``export.py`` to keep the
diff small and the responsibility clear.
"""

from __future__ import annotations

from collections import Counter

import geopandas as gpd

from config import ROAD_TYPES_SIDEWALK_EXPECTED

# Exclude service roads — too noisy (driveways, parking aisles).
_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

# Minimum edge length (metres) to include.
_MIN_LENGTH = 15.0

# Tag values that indicate "yes, there's a sidewalk on this side".
_POSITIVE = frozenset({"yes", "separate", "both"})


def _classify_edge_sidewalk(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> str:
    """Classify the sidewalk situation of a single road edge.

    Returns one of: ``separate``, ``both``, ``left``, ``right``,
    ``no``, ``unknown``.
    """
    # ── Explicit "separate" documentation ─────────────────────────────────
    if sw_both == "separate" or sw == "separate":
        return "separate"

    # ── Both sides present ────────────────────────────────────────────────
    if sw_both in ("yes",):
        return "both"
    if sw in ("both", "yes"):
        return "both"

    has_left = sw_left in _POSITIVE or sw == "left"
    has_right = sw_right in _POSITIVE or sw == "right"

    if has_left and has_right:
        return "both"
    if has_left:
        return "left"
    if has_right:
        return "right"

    # ── Explicitly no sidewalk ────────────────────────────────────────────
    if sw in ("no", "none"):
        return "no"
    if sw_left in ("no", "none") and sw_right in ("no", "none"):
        return "no"

    # ── Nothing documented ────────────────────────────────────────────────
    return "unknown"


def export_sidewalk_roads(
    edge_tuples: list[tuple[int, int]],
    edge_highways: list[str],
    edge_geoms: list,
    edge_names: list[str],
    edge_sidewalks: list[str],
    edge_sidewalk_left: list[str],
    edge_sidewalk_right: list[str],
    edge_sidewalk_both: list[str],
) -> None:
    """Write ``sidewalk_roads.geojson`` with per-edge sidewalk tag status.

    Only road edges with an actual sidewalk tag (status != ``unknown``)
    are exported to keep the layer lightweight.
    """
    print("Exporting sidewalk tag status on roads...")

    rows: list[dict] = []
    seen: set[tuple[int, int]] = set()
    n_unknown = 0

    for eid in range(len(edge_tuples)):
        hw = edge_highways[eid]
        if hw not in _ROAD_TYPES:
            continue
        geom = edge_geoms[eid]
        if geom is None or geom.is_empty or geom.length < _MIN_LENGTH:
            continue

        # Deduplicate directed edges
        src, tgt = edge_tuples[eid]
        key = (min(src, tgt), max(src, tgt))
        if key in seen:
            continue
        seen.add(key)

        sw = edge_sidewalks[eid] if eid < len(edge_sidewalks) else ""
        sw_l = edge_sidewalk_left[eid] if eid < len(edge_sidewalk_left) else ""
        sw_r = edge_sidewalk_right[eid] if eid < len(edge_sidewalk_right) else ""
        sw_b = edge_sidewalk_both[eid] if eid < len(edge_sidewalk_both) else ""

        status = _classify_edge_sidewalk(sw, sw_l, sw_r, sw_b)

        if status == "unknown":
            n_unknown += 1
            continue  # skip untagged roads to keep PMTiles lean

        rows.append({
            "geometry": geom,
            "sw": status,
            "name": edge_names[eid] if eid < len(edge_names) else "",
        })

    # Write output
    fb = {"geometry": None, "sw": "", "name": ""}
    if rows:
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    gdf.to_file("sidewalk_roads.geojson", driver="GeoJSON")

    n_total = len(rows) + n_unknown
    print(f"  Road edges analysed: {n_total}")
    print(f"  Tagged (exported): {len(rows)} | Unknown (skipped): {n_unknown}")

    # Breakdown by status
    counts = Counter(r["sw"] for r in rows)
    for st in ("separate", "both", "left", "right", "no"):
        print(f"    {st}: {counts.get(st, 0)}")
