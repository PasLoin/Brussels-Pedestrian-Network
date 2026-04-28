"""
Export sidewalk tag status on road edges — QA layer for OSM mappers.

Produces ``sidewalk_roads.geojson`` with two properties per feature:

* ``sw`` — classified sidewalk documentation status.
* ``name`` — street name (for popups).

This is a **mapping completeness** tool, not a walkability assessment.
A road tagged ``sidewalk=no`` is just as green as ``sidewalk=both``
because the mapper has documented the situation.

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

def _canon_geom_hash(geom) -> int:
    """Direction-independent hash of a LineString geometry.

    Two directed versions of the same physical segment (u→v and v→u)
    will have reversed coordinate order but are the same road — this
    function normalises them to the same hash.  Distinct parallel
    segments between the same nodes will produce different hashes.
    """
    coords = geom.coords[:]
    if coords[0] > coords[-1]:
        coords = coords[::-1]
    # Round to 1 decimal (~10 cm in EPSG:31370) to absorb float noise
    return hash(tuple(round(c, 1) for pt in coords for c in pt))


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
        # Any other explicit value (no, none, mapped, …) → documented
        return "documented"

    # ── 2. Both left AND right documented ─────────────────────────────────
    if sw_left and sw_right:
        if sw_left == "separate" and sw_right == "separate":
            return "separate"
        if sw_left == "separate" or sw_right == "separate":
            # One side separate, other side explicitly tagged → documented
            return "documented"
        # Both sides have an explicit value (yes, no, none, …)
        return "documented"

    # ── 3. General sidewalk tag ───────────────────────────────────────────
    if sw:
        if sw == "separate":
            return "separate"
        if sw in ("both", "yes"):
            return "yes"
        if sw in ("left", "right"):
            return "partial"
        # Any other explicit value (no, none, …) → documented
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

    All road edges are exported, including ``unknown`` (no tag), so
    mappers can see where documentation is missing.

    Deduplication uses (node pair + geometry hash) so that distinct
    multigraph edges between the same nodes are preserved while
    directed duplicates (u→v / v→u of the same segment) are dropped.
    """
    print("Exporting sidewalk tag status on roads (QA layer)...")

    rows: list[dict] = []
    seen: set[tuple[int, int, int]] = set()

    for eid in range(len(edge_tuples)):
        hw = edge_highways[eid]
        if hw not in _ROAD_TYPES:
            continue
        geom = edge_geoms[eid]
        if geom is None or geom.is_empty or geom.length < _MIN_LENGTH:
            continue

        # Deduplicate directed edges while keeping distinct multigraph
        # segments.  The geometry hash is direction-independent so
        # u→v and v→u of the same road collapse, but parallel roads
        # between the same nodes stay separate.
        src, tgt = edge_tuples[eid]
        key = (min(src, tgt), max(src, tgt), _canon_geom_hash(geom))
        if key in seen:
            continue
        seen.add(key)

        sw = edge_sidewalks[eid] if eid < len(edge_sidewalks) else ""
        sw_l = edge_sidewalk_left[eid] if eid < len(edge_sidewalk_left) else ""
        sw_r = edge_sidewalk_right[eid] if eid < len(edge_sidewalk_right) else ""
        sw_b = edge_sidewalk_both[eid] if eid < len(edge_sidewalk_both) else ""

        status = _classify_edge_sidewalk(sw, sw_l, sw_r, sw_b)

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

    print(f"  Road edges exported: {len(rows)}")

    # Breakdown by status
    counts = Counter(r["sw"] for r in rows)
    for st in ("separate", "yes", "documented", "partial", "unknown"):
        print(f"    {st}: {counts.get(st, 0)}")
