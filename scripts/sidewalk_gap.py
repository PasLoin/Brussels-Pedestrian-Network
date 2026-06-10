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

Both inputs are **raw GeoJSON** exported directly by osmium (one OSM
way = one feature):

* ``roads_geojson_path`` — road ways, with sidewalk tags intact.
* ``footways_geojson_path`` — ``highway=footway`` and
  ``highway=pedestrian`` ways, with the ``footway`` sub-tag intact.

Using raw osmium output (rather than graph edges from OSMnx) matters
for both layers:

* For roads, it avoids the tag-bleeding bug where simplification
  merges adjacent ways and shares one's sidewalk tag with the other.
* For footways, it preserves the ``footway`` sub-tag (``sidewalk`` /
  ``crossing`` / ``link`` / …) which OSMnx drops during simplification.
  That sub-tag is what lets us distinguish actual sidewalks from park
  paths, crossings, and shortcut links — all of which share
  ``highway=footway``.

Roads are **excluded** from the analysis only if:

- They are ``highway=service`` (driveways, parking aisles…).
- They carry an explicit ``no`` on ``sidewalk:both``, ``sidewalk:left``
  or ``sidewalk:right`` — the mapper has documented an absence of
  sidewalk on (at least) that side, so flagging the road as a gap
  would be a false positive against confirmed absence.

Every other sidewalk-tag combination is analysed geometrically.  In
particular, ``sidewalk:both=separate`` is treated as a CLAIM that
sidewalks are mapped as separate ways on both sides — not as a
guarantee.  This catches the common OSM mistake where ``separate``
is tagged but only one sidewalk was actually drawn.

Footways are filtered to keep:

- ``highway=footway`` AND ``footway`` in ``{sidewalk, link, crossing}``.
  ``sidewalk`` is the canonical positive; ``link`` and ``crossing``
  are kept because some run parallel to roads and effectively serve
  as a sidewalk for that stretch (e.g. a long crossing along a
  parking strip).  The per-piece parallel check naturally filters
  out the perpendicular crossings — they fail the angle test and
  contribute zero coverage.
- ``highway=pedestrian`` — pedestrian zones, often used as a sidewalk
  at their edges along bordering streets.

This drops untagged ``highway=footway`` (most often park paths) and
``footway=traffic_island`` (physical refuge in the middle of the
road) — common sources of false positives such as the Sablon park
paths.
"""

from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from timing import step

# Road types to analyse.  service is excluded — too noisy (driveways,
# parking aisles) and rarely has separate footways.
_GAP_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

# How far from the road centerline to look for footways (metres).
SIDEWALK_GAP_OFFSET_M = float(os.environ.get("SIDEWALK_GAP_OFFSET_M", 7))

# Buffer radius around the offset line (metres).
SIDEWALK_GAP_SEARCH_M = float(os.environ.get("SIDEWALK_GAP_SEARCH_M", 7))

# Maximum angle difference (degrees) between road and footway sub-piece.
MAX_ANGLE_DIFF = float(os.environ.get("SIDEWALK_GAP_MAX_ANGLE", 35))

# Minimum coverage: parallel footway pieces on a side must cover at
# least this fraction of the road length to count as "has sidewalk".
SIDEWALK_GAP_MIN_COVERAGE = float(os.environ.get("SIDEWALK_GAP_MIN_COVERAGE", 0.4))

# Skip road segments shorter than this (metres).
_MIN_ROAD_LENGTH = 20.0

# Minimum length (m) of a clipped footway sub-piece for its bearing
# to be reliable enough to test parallelism.
_MIN_CLIPPED_LENGTH = 3.0


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


def _iter_linestrings(geom):
    """Yield each ``LineString`` contained in *geom*."""
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
    """Compute the fraction of road length covered by parallel footways."""
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


def _should_skip_road(sw: str, sw_left: str, sw_right: str, sw_both: str) -> bool:
    """Return True if the road should be skipped from gap detection."""
    return sw_both == "no" or sw_left == "no" or sw_right == "no"


def _load_sidewalk_footways(footways_geojson_path: str) -> tuple[list, dict]:
    """Load raw footways and filter down to those usable as sidewalks."""
    print(f"  Reading raw footways from: {footways_geojson_path}")
    fw_gdf = gpd.read_file(footways_geojson_path)
    fw_gdf = fw_gdf[fw_gdf.geometry.geom_type == "LineString"].copy()
    fw_gdf = fw_gdf.to_crs("EPSG:31370")

    n_raw = len(fw_gdf)

    for col in ("highway", "footway"):
        if col not in fw_gdf.columns:
            fw_gdf[col] = ""

    fw_gdf["_highway"] = fw_gdf["highway"].apply(_safe_str)
    fw_gdf["_footway"] = fw_gdf["footway"].apply(_safe_str)

    mask_sidewalk = (
        (fw_gdf["_highway"] == "footway") & (fw_gdf["_footway"] == "sidewalk")
    )
    mask_link = (
        (fw_gdf["_highway"] == "footway") & (fw_gdf["_footway"] == "link")
    )
    mask_crossing = (
        (fw_gdf["_highway"] == "footway") & (fw_gdf["_footway"] == "crossing")
    )
    mask_pedestrian = (fw_gdf["_highway"] == "pedestrian")
    keep_mask = mask_sidewalk | mask_link | mask_crossing | mask_pedestrian

    n_sidewalk = int(mask_sidewalk.sum())
    n_link = int(mask_link.sum())
    n_crossing = int(mask_crossing.sum())
    n_pedestrian = int(mask_pedestrian.sum())
    n_kept = int(keep_mask.sum())
    n_dropped = n_raw - n_kept

    fw_gdf = fw_gdf[keep_mask]
    geoms = list(fw_gdf.geometry)

    print(f"  Footways kept: {n_kept} "
          f"(sidewalk: {n_sidewalk} | link: {n_link} | crossing: {n_crossing} "
          f"| pedestrian: {n_pedestrian}) "
          f"| dropped: {n_dropped} / {n_raw}")

    return geoms, {
        "raw": n_raw,
        "kept": n_kept,
        "kept_sidewalk": n_sidewalk,
        "kept_link": n_link,
        "kept_crossing": n_crossing,
        "kept_pedestrian": n_pedestrian,
        "dropped": n_dropped,
    }


def detect_sidewalk_gaps(
    roads_geojson_path: str,
    footways_geojson_path: str,
) -> dict:
    """Detect roads with a footway on one side only."""
    print("Detecting sidewalk gaps (footway on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m | "
          f"Max angle: {MAX_ANGLE_DIFF}° | "
          f"Min coverage: {SIDEWALK_GAP_MIN_COVERAGE:.0%}")

    # ── Load and filter footways ──────────────────────────────────────────
    with step("load + filter footways"):
        footway_geoms, footway_filter_stats = _load_sidewalk_footways(
            footways_geojson_path,
        )
        footway_tree = STRtree(footway_geoms) if footway_geoms else None
    print(f"  Footway segments indexed: {len(footway_geoms)}")

    # ── Load raw road ways ────────────────────────────────────────────────
    with step("load + filter roads"):
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
    n_skipped_no_sidewalk = 0
    gap_length_m = 0.0
    both_length_m = 0.0
    none_length_m = 0.0

    # ── Main analysis loop ────────────────────────────────────────────────
    # Likely-expensive: per-road offset_curve + buffer + STRtree.query
    # + per-candidate intersection().  Worth confirming.
    with step("main road analysis loop"):
        for _, road in roads_gdf.iterrows():
            geom = road.geometry

            # ── Skip roads with explicit sidewalk=no on any side ──────────
            sw = _safe_str(road.get("sidewalk"))
            sw_l = _safe_str(road.get("sidewalk:left"))
            sw_r = _safe_str(road.get("sidewalk:right"))
            sw_b = _safe_str(road.get("sidewalk:both"))
            if _should_skip_road(sw, sw_l, sw_r, sw_b):
                n_skipped_no_sidewalk += 1
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

            # Query footway index (empty if no sidewalks were found at all)
            if footway_tree is None:
                left_candidates: list[int] = []
                right_candidates: list[int] = []
            else:
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
    with step("write sidewalk_gaps.geojson"):
        fb = {"geometry": None, "name": ""}
        if rows:
            gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
        gdf.to_file("sidewalk_gaps.geojson", driver="GeoJSON")

    print(f"  Roads analysed: {n_roads} | "
          f"Skipped (sidewalk=no on a side): {n_skipped_no_sidewalk}")
    print(f"  Both sides: {n_both} | One side (gap): {n_gap} | "
          f"Neither side: {n_none}")
    print(f"  Sidewalk gaps exported: {len(rows)}")

    return {
        "roads_analysed": n_roads,
        "skipped_no_sidewalk": n_skipped_no_sidewalk,
        "both_sides": n_both,
        "one_side_gap": n_gap,
        "neither_side": n_none,
        "gap_length_km": round(gap_length_m / 1000, 2),
        "both_length_km": round(both_length_m / 1000, 2),
        "neither_length_km": round(none_length_m / 1000, 2),
        "footway_segments_indexed": len(footway_geoms),
        "footway_filter": footway_filter_stats,
    }
