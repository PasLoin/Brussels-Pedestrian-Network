"""
Detect sidewalk gaps — roads with a footway on one side but not the other.

For each road segment, the geometry is offset left and right to create
search zones.  A footway is counted on a given side only if:

1. It is tagged ``footway=sidewalk`` (or close equivalent).  Generic
   footways, park paths, crossings, etc. are ignored — they aren't
   sidewalks and previously caused false positives (e.g. Sablon: park
   path mistaken for a sidewalk on one side).
2. It is roughly **parallel** to the road (within ``MAX_ANGLE_DIFF``).
3. The cumulative length of parallel sidewalk-footways on that side
   covers at least ``SIDEWALK_GAP_MIN_COVERAGE`` % of the road length.

Roads are **excluded** from the analysis if:

- They are ``highway=service`` (driveways, parking aisles…).
- Both sides are unambiguously documented with non-``separate`` values
  (e.g. ``sidewalk=both``, ``sidewalk=no``, ``sidewalk:left=yes
  sidewalk:right=yes``).

Roads tagged ``sidewalk=separate`` (or ``sidewalk:both=separate``) are
**NOT** skipped — we verify geometrically that a ``footway=sidewalk``
exists on each side.  Previously, "separate" was treated as proof of
both-sided sidewalks, but in practice mappers often write "separate"
even when only one side has been mapped as a separate way.  This was
the main reason gaps on major streets (e.g. Rue Haute, Rue Blaes) were
never flagged.

Footway data is read from a **raw GeoJSON** exported by osmium (one
OSM way = one feature).  This preserves the ``footway`` sub-tag,
which OSMnx graph simplification can drop or mangle.
"""

from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED

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

# Values of the `footway` sub-tag that we accept as a real sidewalk.
# `sidewalk` is the canonical one; `link` is sometimes used at corners
# to connect two sidewalk segments and is OK to include.  Anything
# else (crossing, traffic_island, access_aisle, …) is ignored.
_SIDEWALK_FOOTWAY_VALUES = frozenset({"sidewalk", "link"})

# Sidewalk tag values that fully document both sides — these allow
# the road to be skipped from geometric gap detection.
# Note: "separate" is intentionally NOT here.  When a mapper writes
# `sidewalk=separate`, they CLAIM the sidewalks are mapped as separate
# ways — but we must verify this geometrically because a single side
# being mapped is a common mistake.
_FULLY_DOCUMENTED_VALUES = frozenset({"yes", "no", "none", "both"})


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


def _should_skip_road(sw: str, sw_l: str, sw_r: str, sw_b: str) -> bool:
    """Determine if a road should be skipped from geometric gap detection.

    We skip when both sides are *unambiguously* documented — meaning we
    trust the tags so much that geometric verification would just add
    noise.

    We do NOT skip when `sidewalk=separate` (or `sidewalk:both=separate`)
    is involved.  "Separate" says the sidewalks are mapped as separate
    ways elsewhere, but a common mistake is to write "separate" while
    only mapping one side.  By keeping these roads in the geometric pass,
    we catch those documentation/data mismatches — which is exactly the
    kind of gap a mapper would want to fix.

    Cases skipped:
    - `sidewalk:both=yes|no|none|both` (any side covered explicitly)
    - `sidewalk:left` AND `sidewalk:right` both present with non-separate
      values (both sides explicitly documented)
    - `sidewalk=yes|no|none|both` with no left/right overrides

    Cases NOT skipped (analysed geometrically):
    - Anything involving "separate"
    - Only one of left/right tagged (already a documented one-sided case,
      worth verifying)
    - No tags at all
    """
    # sidewalk:both = strongest signal, unless it's "separate"
    if sw_b in _FULLY_DOCUMENTED_VALUES:
        return True

    # Both left and right explicitly tagged, neither is "separate"
    if sw_l and sw_r and sw_l != "separate" and sw_r != "separate":
        return True

    # General sidewalk tag, definitive value, no left/right override
    if sw in _FULLY_DOCUMENTED_VALUES and not sw_l and not sw_r:
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def detect_sidewalk_gaps(
    roads_geojson_path: str,
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
) -> dict:
    """Detect roads with a footway=sidewalk on one side only.

    Parameters
    ----------
    roads_geojson_path : str
        Path to the raw roads GeoJSON (one OSM way = one feature).
    footways_geojson_path : str
        Path to the raw footways GeoJSON (one OSM way = one feature,
        with the `footway` sub-tag preserved).

    Returns
    -------
    dict
        Statistics about the gap detection for stats.json.

    Writes ``sidewalk_gaps.geojson`` with one feature per gap segment.
    """
    print("Detecting sidewalk gaps (footway=sidewalk on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m | "
          f"Max angle: {MAX_ANGLE_DIFF}° | "
          f"Min coverage: {SIDEWALK_GAP_MIN_COVERAGE:.0%}")

    # ── Build footway spatial index from raw footways ─────────────────────
    # Read raw footways and filter to footway=sidewalk only.  Generic
    # footways (park paths, plaza crossings, shortcuts) are excluded —
    # they used to cause false positives like at Place du Grand Sablon
    # where a park path is mistaken for a parallel sidewalk.
    print(f"  Reading footways from: {footways_geojson_path}")
    fw_gdf = gpd.read_file(footways_geojson_path)
    fw_gdf = fw_gdf[fw_gdf.geometry.geom_type == "LineString"].copy()
    fw_gdf = fw_gdf.to_crs("EPSG:31370")
    total_fw = len(fw_gdf)

    # Filter to footway=sidewalk (and footway=link for corner connectors)
    fw_tag = fw_gdf.get("footway")
    if fw_tag is None:
        # Tag missing entirely from export — fall back to all footways
        # (degraded behaviour, will produce more false positives)
        print("  WARN: 'footway' tag missing from export, using all footways")
        sw_fw = fw_gdf
    else:
        sw_mask = fw_tag.fillna("").astype(str).str.lower().isin(_SIDEWALK_FOOTWAY_VALUES)
        sw_fw = fw_gdf[sw_mask]

    print(f"  Footway ways total: {total_fw} | "
          f"with footway=sidewalk: {len(sw_fw)}")

    footway_geoms: list = []
    footway_bearings: list[float | None] = []
    for geom in sw_fw.geometry:
        if geom is None or geom.is_empty:
            continue
        footway_geoms.append(geom)
        if geom.length >= _MIN_FOOTWAY_LENGTH:
            footway_bearings.append(_line_bearing(geom))
        else:
            footway_bearings.append(None)

    footway_tree = STRtree(footway_geoms)
    print(f"  Footway=sidewalk segments indexed: {len(footway_geoms)}")

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
    n_separate_verified_ok = 0
    n_separate_verified_gap = 0
    gap_length_m = 0.0
    both_length_m = 0.0
    none_length_m = 0.0

    for _, road in roads_gdf.iterrows():
        geom = road.geometry

        # ── Skip roads with fully documented sidewalk tags ────────────────
        sw = _safe_str(road.get("sidewalk"))
        sw_l = _safe_str(road.get("sidewalk:left"))
        sw_r = _safe_str(road.get("sidewalk:right"))
        sw_b = _safe_str(road.get("sidewalk:both"))
        if _should_skip_road(sw, sw_l, sw_r, sw_b):
            n_skipped_documented += 1
            continue

        # Flag whether this road claims "separate" somewhere — used
        # for stats only.  Geometric pass still runs.
        claims_separate = (
            sw == "separate"
            or sw_b == "separate"
            or sw_l == "separate"
            or sw_r == "separate"
        )

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
            both_length_m += road_length
            if claims_separate:
                n_separate_verified_ok += 1
        elif not has_left and not has_right:
            n_none += 1
            none_length_m += road_length
        else:
            n_gap += 1
            gap_length_m += road_length
            if claims_separate:
                n_separate_verified_gap += 1
            rows.append({
                "geometry": geom,
                "name": _safe_str(road.get("name")) or "",
                # Track whether this gap was caught because the mapper
                # claimed "separate" but only one side is actually
                # mapped — useful for QA prioritisation.
                "claims_separate": bool(claims_separate),
            })

    # ── Save output ───────────────────────────────────────────────────────
    fb = {"geometry": None, "name": "", "claims_separate": False}
    if rows:
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    gdf.to_file("sidewalk_gaps.geojson", driver="GeoJSON")

    print(f"  Roads analysed: {n_roads} | "
          f"Skipped (fully documented): {n_skipped_documented}")
    print(f"  Both sides: {n_both} | One side (gap): {n_gap} | "
          f"Neither side: {n_none}")
    print(f"  Of which claimed 'separate' — OK: {n_separate_verified_ok} | "
          f"actually one-sided: {n_separate_verified_gap}")
    print(f"  Sidewalk gaps exported: {len(rows)}")

    return {
        "roads_analysed": n_roads,
        "skipped_documented": n_skipped_documented,
        "both_sides": n_both,
        "one_side_gap": n_gap,
        "neither_side": n_none,
        "separate_verified_ok": n_separate_verified_ok,
        "separate_verified_gap": n_separate_verified_gap,
        "gap_length_km": round(gap_length_m / 1000, 2),
        "both_length_km": round(both_length_m / 1000, 2),
        "neither_length_km": round(none_length_m / 1000, 2),
        "footway_sidewalk_segments_indexed": len(footway_geoms),
        "footway_total_segments": total_fw,
    }
