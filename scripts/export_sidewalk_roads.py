"""
Export sidewalk tag status on road edges — QA layer for OSM mappers.

Produces ``sidewalk_roads.geojson`` with two properties per feature:

* ``sw`` — classified sidewalk documentation status.
* ``name`` — street name (for popups).

This module reads **raw road ways** exported directly by osmium (one
OSM way = one GeoJSON feature).  This avoids the tag-bleeding bug
caused by OSMnx graph simplification, where two adjacent ways merged
at a degree-2 node would share the sidewalk tag of whichever segment
had one — even if the other segment had no tag at all.

Classification (``sw`` values)
------------------------------
``separate``
    Best practice.  ``sidewalk:both=separate``, or both left and right
    tagged as ``separate``.  The sidewalks are mapped as distinct ways.

``yes``
    Positive but upgradeable.  ``sidewalk=yes``, ``sidewalk=both``, or
    ``sidewalk:both=yes``.  Sidewalk exists but isn't mapped as a
    separate way yet — could become ``separate`` in OSM.

``documented``
    Both sides are explicitly tagged, even if the value is ``no``.
    This includes ``sidewalk=no``, ``sidewalk:both=no``,
    ``sidewalk:left=no + sidewalk:right=no``, or any combination where
    both sides have an explicit value.  The mapper did the work.

``partial``
    Only one side (``sidewalk:left`` or ``sidewalk:right``) is tagged.
    The other side is undocumented.

``unknown``
    No sidewalk tag at all.  Missing data — not an error, just a gap
    in documentation that a mapper could fill.
"""

from __future__ import annotations

from collections import Counter

import geopandas as gpd

from config import ROAD_TYPES_SIDEWALK_EXPECTED

# Exclude service roads — too noisy (driveways, parking aisles).
_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

# Minimum edge length (metres) to include.
_MIN_LENGTH = 15.0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    """Normalise a GeoJSON property value to a lowercase string.

    Handles None, NaN, and missing values that geopandas may produce
    when reading GeoJSON features with heterogeneous properties.
    """
    if val is None:
        return ""
    if isinstance(val, float):
        import math
        if math.isnan(val):
            return ""
    return str(val).strip().lower()


def _classify_edge_sidewalk(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> str:
    """Classify sidewalk documentation completeness for a road edge.

    Returns one of: ``separate``, ``yes``, ``documented``, ``partial``,
    ``unknown``.
    """
    # ── 1. sidewalk:both takes priority ───────────────────────────────────
    if sw_both:
        if sw_both == "separate":
            return "separate"
        if sw_both in ("yes", "both"):
            return "yes"
        # Any other explicit value (no, mapped, …) → documented
        return "documented"

    # ── 2. Both left AND right documented ─────────────────────────────────
    if sw_left and sw_right:
        if sw_left == "separate" and sw_right == "separate":
            return "separate"
        if sw_left == "separate" or sw_right == "separate":
            return "documented"
        return "documented"

    # ── 3. General sidewalk tag ───────────────────────────────────────────
    if sw:
        if sw == "separate":
            return "separate"
        if sw in ("both", "yes"):
            return "yes"
        if sw in ("left", "right"):
            return "partial"
        return "documented"

    # ── 4. Only one side documented → partial ─────────────────────────────
    if sw_left or sw_right:
        return "partial"

    # ── 5. Nothing documented ─────────────────────────────────────────────
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def export_sidewalk_roads(
    raw_geojson_path: str = "sidewalk_roads_raw.geojson",
) -> dict:
    """Write ``sidewalk_roads.geojson`` with per-way sidewalk tag status.

    Returns a dict of statistics for stats.json.
    """
    print("Exporting sidewalk tag status on roads (QA layer)...")
    print(f"  Reading raw roads from: {raw_geojson_path}")

    gdf = gpd.read_file(raw_geojson_path)

    # Filter for LineString geometries only
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy()

    # Project to EPSG:31370 for length calculation
    gdf_proj = gdf.to_crs("EPSG:31370")

    # Filter by road type and minimum length
    gdf_proj = gdf_proj[gdf_proj["highway"].isin(_ROAD_TYPES)]
    gdf_proj = gdf_proj[gdf_proj.geometry.length >= _MIN_LENGTH]

    print(f"  Road ways after filtering: {len(gdf_proj)}")

    rows: list[dict] = []
    length_by_status: dict[str, float] = {}

    for _, row in gdf_proj.iterrows():
        sw = _safe_str(row.get("sidewalk"))
        sw_l = _safe_str(row.get("sidewalk:left"))
        sw_r = _safe_str(row.get("sidewalk:right"))
        sw_b = _safe_str(row.get("sidewalk:both"))

        status = _classify_edge_sidewalk(sw, sw_l, sw_r, sw_b)

        road_length = row.geometry.length
        length_by_status[status] = length_by_status.get(status, 0.0) + road_length

        rows.append({
            "geometry": row.geometry,
            "sw": status,
            "name": _safe_str(row.get("name")) or "",
        })

    # Write output
    fb = {"geometry": None, "sw": "", "name": ""}
    if rows:
        out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        out_gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    out_gdf.to_file("sidewalk_roads.geojson", driver="GeoJSON")

    print(f"  Road ways exported: {len(rows)}")

    # Breakdown by status
    counts = Counter(r["sw"] for r in rows)
    for st in ("separate", "yes", "documented", "partial", "unknown"):
        print(f"    {st}: {counts.get(st, 0)}")

    total_ways = len(rows)

    return {
        "total_road_ways": total_ways,
        "by_status": {
            st: counts.get(st, 0) for st in ("separate", "yes", "documented", "partial", "unknown")
        },
        "pct_by_status": {
            st: round(counts.get(st, 0) / total_ways * 100, 1) if total_ways > 0 else 0
            for st in ("separate", "yes", "documented", "partial", "unknown")
        },
        "km_by_status": {
            st: round(length_by_status.get(st, 0) / 1000, 2)
            for st in ("separate", "yes", "documented", "partial", "unknown")
        },
    }
