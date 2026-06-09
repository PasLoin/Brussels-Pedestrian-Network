"""
Detect sidewalk gaps — roads with a footway on one side but not the other.

For each road segment, the geometry is offset left and right to create
search zones.  A footway is counted on a given side only if the portion
of it lying inside the search zone is roughly **parallel** to the road
(within ``MAX_ANGLE_DIFF``).  Coverage is summed per side; the side
must reach ``SIDEWALK_GAP_MIN_COVERAGE`` of the road length to count.

The parallel check is done **per clipped sub-piece**, not on the
footway as a whole.  This avoids a class of false positives where a
single OSM ``way`` traces multiple sides of a block (e.g. a footway
drawn all the way around a triangular pâté de maisons).  In that case
the way's first→last bearing is meaningless — it can even be zero if
the way is closed — but the portion of the way running alongside any
given road is locally parallel, and the per-piece check picks that up.

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

# Maximum angle difference (degrees) between road and footway sub-piece.
MAX_ANGLE_DIFF = float(os.environ.get("SIDEWALK_GAP_MAX_ANGLE", 35))

# Minimum coverage: parallel footway pieces on a side must cover at
# least this fraction of the road length to count as "has sidewalk".
SIDEWALK_GAP_MIN_COVERAGE = float(os.environ.get("SIDEWALK_GAP_MIN_COVERAGE", 0.4))

# Skip road segments shorter than this (metres).
_MIN_ROAD_LENGTH = 20.0

# Minimum length (m) of a clipped footway sub-piece for its bearing
# to be reliable enough to test parallelism.  Below this, the piece
# is too short to draw a meaningful direction from and is ignored.
_MIN_CLIPPED_LENGTH = 3.0

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
    """Return the bearing (0–180°) of a LineString, or None if degenerate.

    Computed from the first and last coordinate of the geometry.  This
    is only meaningful for short, roughly straight LineStrings — used
    here on road ways (typically straight between intersections in the
    raw osmium export) and on clipped footway sub-pieces, not on whole
    footway ways which can wrap around a block.
    """
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


def _iter_linestrings(geom):
    """Yield each ``LineString`` contained in *geom*.

    A ``shapely.intersection`` result can be:

    * ``LineString`` — the common case;
    * ``MultiLineString`` — when the footway enters/exits the zone
      several times (e.g. a way that wraps around a block re-enters
      the same side's buffer multiple times);
    * ``GeometryCollection`` — mixed with stray ``Point`` parts at
      touch boundaries.

    Point and Polygon parts are silently dropped.
    """
    gt = geom.geom_type
    if gt == "LineString":
        yield geom
    elif gt == "MultiLineString":
        yield from geom.geoms
    elif gt == "GeometryCollection":
        for sub in geom.geoms:
            yield from _iter_linestrings(sub)


def _parallel_coverage(
    zone,
    road_bearing: float,
    road_length: float,
    candidates,
    footway_geoms: list,
) -> float:
    """Compute the fraction of road length covered by parallel footways.

    Each candidate footway is **clipped to the search zone first**, then
    each resulting LineString piece is tested for parallelism on its own.
    This is the key fix for footway ways that wrap multiple sides of a
    block: their global first→last bearing is meaningless, but the
    portion lying inside any given side's zone is locally parallel and
    is picked up here.

    Pieces shorter than ``_MIN_CLIPPED_LENGTH`` are skipped — too short
    to draw a reliable direction from (they would be over-sensitive to
    micro-jitter in the OSM geometry).
    """
    total_length = 0.0
    for i in candidates:
        fw = footway_geoms[i]
        if not fw.intersects(zone):
            continue
        try:
            clipped = fw.intersection(zone)
        except Exception:
            continue
        if clipped.is_empty:
            continue
        for piece in _iter_linestrings(clipped):
            piece_length = piece.length
            if piece_length < _MIN_CLIPPED_LENGTH:
                continue
            piece_bearing = _line_bearing(piece)
            if _is_parallel(road_bearing, piece_bearing):
                total_length += piece_length
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
) -> dict:
    """Detect roads with a footway on one side only.

    Parameters
    ----------
    roads_geojson_path : str
        Path to the raw roads GeoJSON (one OSM way = one feature).
    edge_highways : list[str]
        Highway types from the routing graph (all edges).
    edge_geoms : list
        Geometries from the routing graph (all edges, EPSG:31370).

    Returns
    -------
    dict
        Statistics about the gap detection for stats.json.

    Writes ``sidewalk_gaps.geojson`` with one feature per gap segment.
    """
    print("Detecting sidewalk gaps (footway on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m | "
          f"Max angle: {MAX_ANGLE_DIFF}° | "
          f"Min coverage: {SIDEWALK_GAP_MIN_COVERAGE:.0%}")

    # ── Build footway spatial index from graph edges ──────────────────────
    # NOTE: bearings are NOT precomputed here anymore.  The global
    # first→last bearing of a whole footway can be totally misleading
    # (e.g. a way drawn around several sides of a block, or a closed
    # loop where first ≈ last).  Bearings are now computed on each
    # clipped sub-piece inside _parallel_coverage().
    footway_geoms: list = []
    for eid in range(len(edge_highways)):
        hw = edge_highways[eid]
        geom = edge_geoms[eid]
        if hw in PED_HIGHWAY_TYPES and geom is not None and not geom.is_empty:
            footway_geoms.append(geom)

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
    gap_length_m = 0.0
    both_length_m = 0.0
    none_length_m = 0.0

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
            left_candidates, footway_geoms,
        )
        right_cov = _parallel_coverage(
            right_zone, road_bearing, road_length,
            right_candidates, footway_geoms,
        )

        has_left = left_cov >= SIDEWALK_GAP_MIN_COVERAGE
        has_right = right_cov >= SIDEWALK_GAP_MIN_COVERAGE

        if has_left and has_right:
            n_both += 1
            both_length_m += road_length
        elif not has_left and not has_right:
            n_none += 1
            none_length_m += road_length
        else:
            n_gap += 1
            gap_length_m += road_length
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

    return {
        "roads_analysed": n_roads,
        "skipped_documented": n_skipped_documented,
        "both_sides": n_both,
        "one_side_gap": n_gap,
        "neither_side": n_none,
        "gap_length_km": round(gap_length_m / 1000, 2),
        "both_length_km": round(both_length_m / 1000, 2),
        "neither_length_km": round(none_length_m / 1000, 2),
        "footway_segments_indexed": len(footway_geoms),
    }
