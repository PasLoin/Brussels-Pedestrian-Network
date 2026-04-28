"""
Export sidewalk tag status on road edges — lightweight layer for QA.

Produces ``sidewalk_roads.geojson`` with two properties per feature:

* ``sw`` — classified sidewalk status: ``separate``, ``both``,
  ``left``, ``right``, ``no``, or ``unknown``.
* ``name`` — street name (for popups).

Only road types from ``ROAD_TYPES_SIDEWALK_EXPECTED`` are included
(residential, tertiary, secondary, primary…).  Directed edges are
deduplicated so each physical road segment appears once.

Classification priority
-----------------------
1. ``sidewalk:both`` set → fully documented (separate / both / no).
2. **Both** ``sidewalk:left`` **and** ``sidewalk:right`` set →
   fully documented.  Even ``left=no`` + ``right=separate`` counts
   as complete (green), because the mapper has recorded both sides.
3. General ``sidewalk`` tag (both / yes / left / right / no / separate).
4. Only one of ``sidewalk:left`` or ``sidewalk:right`` set → partial.
5. Nothing → ``unknown`` (not exported, saves PMTiles space).
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

# Tag values that indicate "no sidewalk on this side".
_NEGATIVE = frozenset({"no", "none"})


def _classify_edge_sidewalk(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> str:
    """Classify the sidewalk situation of a single road edge.

    Returns one of: ``separate``, ``both``, ``left``, ``right``,
    ``no``, ``unknown``.

    The key insight: if **both** ``sidewalk:left`` and
    ``sidewalk:right`` are set, the mapper has fully documented the
    situation — even when one side is ``no``.  That gets green
    (``both`` or ``separate``), not amber.  Only when *both* sides
    are explicitly ``no`` does the result become ``no`` (red).
    """
    # ── 1. sidewalk:both takes priority ───────────────────────────────────
    if sw_both:
        if sw_both == "separate":
            return "separate"
        if sw_both in _POSITIVE:
            return "both"
        if sw_both in _NEGATIVE:
            return "no"
        # Any other value (e.g. "mapped") → documented
        return "both"

    # ── 2. Both left AND right documented ─────────────────────────────────
    if sw_left and sw_right:
        left_pos = sw_left in _POSITIVE
        right_pos = sw_right in _POSITIVE

        if left_pos or right_pos:
            # At least one side has a sidewalk → fully documented
            if sw_left == "separate" or sw_right == "separate":
                return "separate"
            return "both"

        # Both sides set, but both negative → no sidewalk at all
        return "no"

    # ── 3. General sidewalk tag ───────────────────────────────────────────
    if sw == "separate":
        return "separate"
    if sw in ("both", "yes"):
        return "both"
    if sw == "left":
        return "left"
    if sw == "right":
        return "right"
    if sw in _NEGATIVE:
        return "no"

    # ── 4. Only one side documented → partial ─────────────────────────────
    if sw_left:
        return "left"
    if sw_right:
        return "right"

    # ── 5. Nothing documented ─────────────────────────────────────────────
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
