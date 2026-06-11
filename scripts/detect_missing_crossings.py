"""
Detect highway=crossing nodes that are missing a corresponding crossing way.

A ``highway=crossing`` node on a road records a pedestrian crossing location
but does not guarantee that the corresponding crossing **way**
(``highway=footway`` + ``footway=crossing``) has been mapped.  Without the
way, walkers have no routable path across the road at that point — the router
silently falls back to the road surface and no flow break appears.

The gap is hard to spot with the sidewalk-gap detector because Dijkstra can
route through a nearby *existing* crossing node without ever flagging a
"road break" in the pedestrian path.

Detection heuristic
-------------------
For each ``highway=crossing`` node located on an eligible road:

1. **Crossing-way check** — if a ``footway=crossing`` way already exists
   within ``CROSSING_WAY_SEARCH_RADIUS_M``, the crossing is mapped → skip.

2. **Short subsegment** — extract a ``±CROSSING_NODE_WINDOW_M`` substring
   of the road centred on the node.  This focuses the geometry checks to
   the immediate neighbourhood rather than the full road.

3. **Parallel-sidewalk check** — apply the same offset-curve + bearing
   analysis used by :mod:`sidewalk_gap` to both sides of the subsegment.
   If parallel sidewalks exist on both sides (coverage ≥
   ``SIDEWALK_GAP_MIN_COVERAGE``), the crossing way is missing → flag.

The parallel-sidewalk requirement keeps the false-positive rate low: only
locations where mappers have *already drawn sidewalks on both sides* are
flagged.  If the sidewalks themselves are missing the node is skipped —
that is a different gap to report.

Inputs
------
* ``highways.geojson`` — slimmed pedestrian layer (contains crossing
  nodes as Point features with ``highway=crossing``).
* ``sidewalk_footways_raw.geojson`` — raw osmium footway export.
* ``sidewalk_roads_raw.geojson`` — raw osmium road export.

Output
------
``missing_crossings.geojson`` — point layer, one feature per detected
missing crossing way, with properties ``name``, ``left_cov``,
``right_cov``.
"""

from __future__ import annotations

import os

import geopandas as gpd
from shapely.ops import substring
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from sidewalk_gap import (
    SIDEWALK_GAP_MIN_COVERAGE,
    SIDEWALK_GAP_OFFSET_M,
    SIDEWALK_GAP_SEARCH_M,
    _line_bearing,
    _load_sidewalk_footways,
    _parallel_coverage,
    _safe_str,
)
from timing import step

# Road types eligible for crossing analysis (service roads excluded —
# driveways and parking aisles rarely have formal crossing infrastructure).
_CROSSING_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

# Minimum road segment length (metres) — very short stubs are unreliable.
_MIN_ROAD_LENGTH = 15.0

# ── Module-level config (readable from env, consistent with sidewalk_gap) ────

# How far from a crossing node to search for an eligible road (metres).
# A crossing node should sit directly on a road way, so 20 m is generous.
CROSSING_NODE_ROAD_SEARCH_M = float(os.environ.get("CROSSING_NODE_ROAD_SEARCH_M", 20.0))

# Half-length of the road subsegment extracted around the crossing node.
# 30 m → we analyse a 60 m stretch of road centred on the node.
CROSSING_NODE_WINDOW_M = float(os.environ.get("CROSSING_NODE_WINDOW_M", 30.0))

# If a footway=crossing way exists within this radius, the crossing is
# already mapped → skip.
CROSSING_WAY_SEARCH_RADIUS_M = float(os.environ.get("CROSSING_WAY_SEARCH_RADIUS_M", 20.0))


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_crossing_nodes(highways_path: str) -> gpd.GeoDataFrame:
    """Read highway=crossing *point* features from the pedestrian layer."""
    gdf = gpd.read_file(highways_path)
    # highways.geojson contains mixed geometry types (LineString + Point).
    mask = (
        (gdf.geometry.geom_type == "Point") &
        (gdf["highway"].apply(_safe_str) == "crossing")
    )
    return gdf[mask].copy().to_crs("EPSG:31370")


def _load_crossing_ways(footways_path: str) -> tuple[list, STRtree | None]:
    """Return (geoms, STRtree) for already-mapped footway=crossing ways."""
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")

    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""

    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "crossing")
    )
    geoms = list(gdf[mask].geometry)
    return geoms, (STRtree(geoms) if geoms else None)


def _load_roads(
    roads_path: str,
) -> tuple[gpd.GeoDataFrame, list, STRtree]:
    """Load eligible road ways; return (gdf, geom_list, STRtree)."""
    gdf = gpd.read_file(roads_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    gdf = gdf[gdf["highway"].isin(_CROSSING_ROAD_TYPES)]
    gdf = gdf[gdf.geometry.length >= _MIN_ROAD_LENGTH]
    gdf = gdf.reset_index(drop=True)     # positional index must match list index
    geoms = list(gdf.geometry)
    return gdf, geoms, STRtree(geoms)


def _write_empty_output() -> None:
    """Write a valid but empty missing_crossings.geojson."""
    gpd.GeoDataFrame(
        [{"geometry": None, "name": "", "left_cov": 0.0, "right_cov": 0.0}],
        crs="EPSG:4326",
    ).to_file("missing_crossings.geojson", driver="GeoJSON")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def detect_missing_crossings(
    highways_geojson_path: str = "highways.geojson",
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    roads_geojson_path: str = "sidewalk_roads_raw.geojson",
) -> dict:
    """Detect highway=crossing nodes that lack a footway=crossing way.

    Returns a dict of statistics for stats.json.
    """
    print("Detecting missing crossing ways...")
    print(
        f"  Node→road search: {CROSSING_NODE_ROAD_SEARCH_M} m | "
        f"Subsegment window: ±{CROSSING_NODE_WINDOW_M} m | "
        f"Crossing-way radius: {CROSSING_WAY_SEARCH_RADIUS_M} m"
    )

    # ── Load inputs ───────────────────────────────────────────────────────
    with step("load crossing nodes (highways.geojson)"):
        crossing_nodes = _load_crossing_nodes(highways_geojson_path)
    print(f"  highway=crossing nodes: {len(crossing_nodes)}")

    if crossing_nodes.empty:
        print("  No crossing nodes found — skipping.")
        _write_empty_output()
        return {"crossing_nodes_found": 0, "missing_crossings_detected": 0}

    with step("load crossing ways (footways)"):
        cw_geoms, cw_tree = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways indexed: {len(cw_geoms)}")

    # Sidewalk footways — used for the parallel coverage check.
    # Note: _load_sidewalk_footways also keeps footway=crossing ways, but
    # they run perpendicular to roads and will fail the bearing test, so
    # they do not contribute false coverage.
    with step("load sidewalk footways"):
        sw_geoms, _fw_stats = _load_sidewalk_footways(footways_geojson_path)
        sw_tree = STRtree(sw_geoms) if sw_geoms else None

    with step("load eligible roads"):
        roads_gdf, road_geoms, road_tree = _load_roads(roads_geojson_path)
    print(f"  Road segments: {len(roads_gdf)}")

    # ── Analyse each crossing node ────────────────────────────────────────
    rows: list[dict] = []
    n_no_road = 0        # no eligible road found within search radius
    n_has_way = 0        # crossing way already mapped nearby
    n_no_sidewalks = 0   # insufficient parallel sidewalk coverage
    n_missing = 0        # missing crossing way detected

    with step("crossing node analysis loop"):
        for _, node_row in crossing_nodes.iterrows():
            node_pt = node_row.geometry

            # 1. Associate node with the nearest eligible road ─────────────
            road_candidates = road_tree.query(
                node_pt.buffer(CROSSING_NODE_ROAD_SEARCH_M)
            )
            if not len(road_candidates):
                n_no_road += 1
                continue

            best_idx = min(
                road_candidates,
                key=lambda i: road_geoms[i].distance(node_pt),
            )
            road_geom = road_geoms[best_idx]

            # 2. Skip if a crossing way is already mapped at this location ──
            if cw_tree is not None:
                cw_zone = node_pt.buffer(CROSSING_WAY_SEARCH_RADIUS_M)
                nearby_cw = cw_tree.query(cw_zone)
                if any(cw_geoms[i].intersects(cw_zone) for i in nearby_cw):
                    n_has_way += 1
                    continue

            # 3. Extract a short road subsegment centred on the node ────────
            dist_along = road_geom.project(node_pt)
            start_d = max(0.0, dist_along - CROSSING_NODE_WINDOW_M)
            end_d   = min(road_geom.length, dist_along + CROSSING_NODE_WINDOW_M)

            if end_d - start_d < 5.0:
                n_no_road += 1
                continue

            try:
                subseg = substring(road_geom, start_d, end_d)
            except Exception:
                n_no_road += 1
                continue

            if subseg.is_empty or subseg.length < 5.0:
                n_no_road += 1
                continue

            bearing = _line_bearing(subseg)
            if bearing is None:
                n_no_road += 1
                continue

            # 4. Check for parallel sidewalks on both sides ─────────────────
            # Reuses the same offset-curve + bearing logic as sidewalk_gap.py.
            try:
                left_line  = subseg.offset_curve(SIDEWALK_GAP_OFFSET_M)
                right_line = subseg.offset_curve(-SIDEWALK_GAP_OFFSET_M)
            except Exception:
                n_no_road += 1
                continue

            if left_line.is_empty or right_line.is_empty:
                n_no_road += 1
                continue

            left_zone  = left_line.buffer(SIDEWALK_GAP_SEARCH_M)
            right_zone = right_line.buffer(SIDEWALK_GAP_SEARCH_M)

            if sw_tree is None:
                n_no_sidewalks += 1
                continue

            seg_len = subseg.length
            left_cov  = _parallel_coverage(
                left_zone, bearing, seg_len,
                sw_tree.query(left_zone), sw_geoms,
            )
            right_cov = _parallel_coverage(
                right_zone, bearing, seg_len,
                sw_tree.query(right_zone), sw_geoms,
            )

            if (left_cov  < SIDEWALK_GAP_MIN_COVERAGE or
                    right_cov < SIDEWALK_GAP_MIN_COVERAGE):
                n_no_sidewalks += 1
                continue

            # 5. Flag: crossing node + both-side sidewalks + no crossing way ─
            road_name = ""
            if "name" in roads_gdf.columns:
                road_name = _safe_str(roads_gdf.iloc[best_idx]["name"])

            n_missing += 1
            rows.append({
                "geometry": node_pt,
                "name": road_name,
                "left_cov":  round(left_cov,  2),
                "right_cov": round(right_cov, 2),
            })

    # ── Save output ───────────────────────────────────────────────────────
    with step("write missing_crossings.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = gpd.GeoDataFrame(
                [{"geometry": None, "name": "", "left_cov": 0.0, "right_cov": 0.0}],
                crs="EPSG:4326",
            )
        out_gdf.to_file("missing_crossings.geojson", driver="GeoJSON")

    n_total = len(crossing_nodes)
    print(f"  Nodes analysed: {n_total}")
    print(f"  Skipped — no eligible road: {n_no_road}")
    print(f"  Skipped — crossing way exists: {n_has_way}")
    print(f"  Skipped — sidewalks insufficient: {n_no_sidewalks}")
    print(f"  Missing crossing ways detected: {n_missing}")

    return {
        "crossing_nodes_found":    n_total,
        "no_eligible_road":        n_no_road,
        "crossing_way_exists":     n_has_way,
        "sidewalks_insufficient":  n_no_sidewalks,
        "missing_crossings_detected": n_missing,
    }
