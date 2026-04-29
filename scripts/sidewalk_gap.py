"""
Detect sidewalk gaps — roads with a footway on one side but not the other.

For each road segment, the geometry is offset left and right to create
search zones.  A footway is counted on a given side only if:

1. It is roughly **parallel** to the road (within ``MAX_ANGLE_DIFF``).
2. The cumulative length of parallel footways on that side covers at
   least ``SIDEWALK_GAP_MIN_COVERAGE`` % of the road segment length.

Roads are **excluded** from the analysis if:

- They are ``highway=service`` (driveways, parking aisles…).
- They carry explicit ``sidewalk``, ``sidewalk:left``, ``sidewalk:right``,
  or ``sidewalk:both`` tags (e.g. ``sidewalk:both=separate``), meaning
  the mapper has already documented the sidewalk situation.
  Flagging these as gaps would be a false positive.

Road data is read from a **raw GeoJSON** exported by osmium (one OSM
way = one feature).  This avoids the tag-bleeding bug caused by OSMnx
graph simplification.  Footway geometries for the spatial index still
come from the graph edges (simplification doesn't affect the spatial
analysis — it only makes some footways longer).

This analysis is purely geometric.  For roads without explicit sidewalk
tags, it checks whether a **separate footway way** has been drawn in
OSM on each side.
"""

from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.strtree import STRtree

from config import PED_HIGHWAY_TYPES, ROAD_TYPES_SIDEWALK_EXPECTED

# Road types to analyse.  service is excluded — too noisy (driveways,
# parking aisles) and rarely has separate footways.
_GAP_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

# How far from the road centerline to look for footways (metres).
SIDEWALK_GAP_OFFSET_M = float(os.environ.get("SIDEWALK_GAP_OFFSET_M", 12))

# Buffer radius around the offset line (metres).
SIDEWALK_GAP_SEARCH_M = float(os.environ.get("SIDEWALK_GAP_SEARCH_M", 8))

# Maximum angle difference (degrees) between road and footway.
MAX_ANGLE_DIFF = float(os.environ.get("SIDEWALK_GAP_MAX_ANGLE", 35))

# Minimum coverage: parallel footways on a side must cover at least
# this fraction of the road length to count as "has sidewalk".
SIDEWALK_GAP_MIN_COVERAGE = float(os.environ.get("SIDEWALK_GAP_MIN_COVERAGE", 0.4))

# Skip road segments shorter than this (metres).
_MIN_ROAD_LENGTH = 20.0

# Skip footway segments shorter than this for angle comparison.
_MIN_FOOTWAY_LENGTH = 5.0

# Sidewalk tag values that indicate the mapper has documented the
# situation.  Roads with any of these on sidewalk/sidewalk:left/right/both
# are excluded from gap detection.
_DOCUMENTED_SIDEWALK_VALUES = frozenset({
    "no", "none", "separate", "yes", "both", "left", "right",
})


def _safe_str(val) -> str:
    """Normalise a GeoJSON property value to a lowercase string."""
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
    return str(val).strip().lower()


def _line_bearing(geom) -> float | None:
    """Return the bearing (0–180°) of a LineString, or None if degenerate."""
    coords = list(geom.coords)
    if len(coords) < 2:
        return None
    dx = coords[-1][0] - coords[0][0]
    dy = coords[-1][1] - coords[0][1]
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return None
    angle = math.degrees(math.atan2(dy, dx)) % 360
    return angle % 180


def _is_parallel(road_bearing: float, footway_bearing: float | None) -> bool:
    """Return True if a footway bearing is within MAX_ANGLE_DIFF of the road."""
    if footway_bearing is None:
        return False
    diff = abs(road_bearing - footway_bearing)
    if diff > 90:
        diff = 180 - diff
    return diff <= MAX_ANGLE_DIFF


def _parallel_coverage(
    zone,
    road_bearing: float,
    road_length: float,
    candidates,
    footway_geoms: list,
    footway_bearings: list,
) -> float:
    """Compute the fraction of road length covered by parallel footways."""
    total_length = 0.0
    for i in candidates:
        if not _is_parallel(road_bearing, footway_bearings[i]):
            continue
        fw = footway_geoms[i]
        if not fw.intersects(zone):
            continue
        try:
            clipped = fw.intersection(zone)
            total_length += clipped.length
        except Exception:
            continue
    return total_length / road_length if road_length > 0 else 0.0


def _is_sidewalk_documented(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> bool:
    """Return True if the mapper has explicitly tagged the sidewalk situation."""
    if sw_left in _DOCUMENTED_SIDEWALK_VALUES:
        return True
    if sw_right in _DOCUMENTED_SIDEWALK_VALUES:
        return True
    if sw_both in _DOCUMENTED_SIDEWALK_VALUES:
        return True
    if sw in _DOCUMENTED_SIDEWALK_VALUES:
        return True
    return False


def detect_sidewalk_gaps(
    roads_geojson_path: str,
    edge_highways: list[str],
    edge_geoms: list,
) -> None:
    """Detect roads with a footway on one side only.

    Parameters
    ----------
    roads_geojson_path : str
        Path to the raw roads GeoJSON (one OSM way = one feature).
        Used for the road edges to analyse — avoids tag-bleeding
        from OSMnx graph simplification.
    edge_highways : list[str]
        Highway types from the routing graph (all edges).  Used to
        build the footway spatial index.
    edge_geoms : list
        Geometries from the routing graph (all edges, EPSG:31370).
        Used to build the footway spatial index.

    Writes ``sidewalk_gaps.geojson`` with one feature per gap segment.
    """
    print("Detecting sidewalk gaps (footway on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m | "
          f"Max angle: {MAX_ANGLE_DIFF}° | "
          f"Min coverage: {SIDEWALK_GAP_MIN_COVERAGE:.0%}")

    # ── Build footway spatial index from graph edges ──────────────────────
    # Graph simplification is fine for footways: merging two footway
    # segments into one longer LineString doesn't affect the spatial
    # analysis (bearing and distance checks still work).
    footway_geoms: list = []
    footway_bearings: list[float | None] = []
    for eid in range(len(edge_highways)):
        hw = edge_highways[eid]
        geom = edge_geoms[eid]
        if hw in PED_HIGHWAY_TYPES and geom is not None and not geom.is_empty:
            footway_geoms.append(geom)
            if geom.length >= _MIN_FOOTWAY_LENGTH:
                footway_bearings.append(_line_bearing(geom))
            else:
                footway_bearings.append(None)

    footway_tree = STRtree(footway_geoms)
    print(f"  Footway segments indexed: {len(footway_geoms)}")

    # ── Load raw road ways ────────────────────────────────────────────────
    print(f"  Reading raw roads from: {roads_geojson_path}")
    roads_gdf = gpd.read_file(roads_geojson_path)
    roads_gdf = roads_gdf[roads_gdf.geometry.geom_type == "LineString"].copy()
    roads_gdf = roads_gdf.to_crs("EPSG:31370")
    roads_gdf = roads_gdf[roads_gdf["highway"].isin(_GAP_ROAD_TYPES)]
    roads_gdf = roads_gdf[roads_gdf.geometry.length >= _MIN_ROAD_LENGTH]
    print(f"  Road ways after filtering: {len(roads_gdf)}")

    # ── Check each road way ───────────────────────────────────────────────
    rows: list[dict] = []
    n_roads = 0
    n_both = 0
    n_none = 0
    n_gap = 0
    n_skipped_documented = 0

    for _, road in roads_gdf.iterrows():
        geom = road.geometry

        # ── Skip roads with explicit sidewalk tags ────────────────────────
        sw = _safe_str(road.get("sidewalk"))
        sw_l = _safe_str(road.get("sidewalk:left"))
        sw_r = _safe_str(road.get("sidewalk:right"))
        sw_b = _safe_str(road.get("sidewalk:both"))
        if _is_sidewalk_documented(sw, sw_l, sw_r, sw_b):
            n_skipped_documented += 1
            continue

        road_bearing = _line_bearing(geom)
        if road_bearing is None:
            continue

        road_length = geom.length
        n_roads += 1

        # Offset left and right to create search zones
        try:
            left_line = geom.offset_curve(SIDEWALK_GAP_OFFSET_M)
            right_line = geom.offset_curve(-SIDEWALK_GAP_OFFSET_M)
        except Exception:
            continue

        if left_line.is_empty or right_line.is_empty:
            continue

        left_zone = left_line.buffer(SIDEWALK_GAP_SEARCH_M)
        right_zone = right_line.buffer(SIDEWALK_GAP_SEARCH_M)

        # Query footway index
        left_candidates = footway_tree.query(left_zone)
        right_candidates = footway_tree.query(right_zone)

        # Compute coverage on each side
        left_cov = _parallel_coverage(
            left_zone, road_bearing, road_length,
            left_candidates, footway_geoms, footway_bearings,
        )
        right_cov = _parallel_coverage(
            right_zone, road_bearing, road_length,
            right_candidates, footway_geoms, footway_bearings,
        )

        has_left = left_cov >= SIDEWALK_GAP_MIN_COVERAGE
        has_right = right_cov >= SIDEWALK_GAP_MIN_COVERAGE

        if has_left and has_right:
            n_both += 1
        elif not has_left and not has_right:
            n_none += 1
        else:
            n_gap += 1
            rows.append({
                "geometry": geom,
                "name": _safe_str(road.get("name")) or "",
            })

    # ── Save output ───────────────────────────────────────────────────────
    fb = {"geometry": None, "name": ""}
    if rows:
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    gdf.to_file("sidewalk_gaps.geojson", driver="GeoJSON")

    print(f"  Roads analysed: {n_roads} | "
          f"Skipped (documented): {n_skipped_documented}")
    print(f"  Both sides: {n_both} | One side (gap): {n_gap} | "
          f"Neither side: {n_none}")
    print(f"  Sidewalk gaps exported: {len(rows)}")
