"""
Detect sidewalk gaps — roads with a footway=sidewalk drawn on one side
but not the other in OSM.

This is a purely **spatial** analysis: for each road segment, the
geometry is offset left and right, and we check whether a separately
mapped sidewalk (`highway=footway footway=sidewalk`) is actually drawn
parallel to each side.

The goal is to surface places where OSM mapping of separate sidewalks
is incomplete — drawing sidewalks is tedious, so mappers often map
just one side and leave the other for later.  Our pedestrian flow
simulation avoids the road wherever a separate sidewalk exists, so a
"white" road in our flow layer is a signal that the sidewalk on that
side might be missing.

Tags on the road are **not** used to determine whether a sidewalk
exists — that's a separate concept handled by ``export_sidewalk_roads``
in the "tags sidewalks" QA layer.  Here, we only use tags to decide
whether to **exclude** a road from analysis, in one specific case:

  When the asymmetry is **explicitly documented** in OSM as the
  physical reality (e.g. ``sidewalk:left=yes sidewalk:right=no``,
  ``sidewalk=left``).  In those cases, a single drawn footway is
  correct — the other side genuinely has no sidewalk on the ground.

Everything else (`sidewalk=both`, `sidewalk=yes`, `sidewalk=separate`,
`sidewalk:both=separate`, no tag at all) is analysed geometrically.
In particular, ``sidewalk=both`` is NOT a reason to skip: it documents
physical reality, but says nothing about whether the sidewalk has
been drawn as a separate way in OSM — which is exactly what this
layer is meant to detect.

Other exclusions:
- ``highway=service`` roads (driveways, parking aisles) — too noisy.
- Roads shorter than ``_MIN_ROAD_LENGTH``.

Footway data is read from a **raw GeoJSON** exported by osmium, with
the ``footway`` sub-tag preserved.  A way counts as a sidewalk when
either:

- ``highway=footway`` with ``footway=sidewalk`` or ``footway=link``
  (canonical sidewalk tagging, plus link connectors at corners), or
- ``highway=pedestrian`` (used in pedestrian zones, where mappers
  commonly tag the sidewalk-equivalent ways this way rather than as
  ``footway=sidewalk``).

Other footways (park paths, plaza crossings, shortcuts, generic
``highway=footway`` without a ``footway`` sub-tag) are ignored —
they would otherwise cause false positives like the park path at
Place du Grand Sablon being mistaken for a parallel sidewalk.
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

# Values of the `footway` sub-tag that count as a real sidewalk.
# `sidewalk` is the canonical one.  `link` is sometimes used at corners
# to connect two sidewalk segments — fine to include.  Anything else
# 
_SIDEWALK_FOOTWAY_VALUES = frozenset({"sidewalk", "link", "crossing", "traffic_island"})

# Tag values used by the skip logic.
_POSITIVE_SIDE = frozenset({"yes", "separate", "both", "left", "right"})
_NEGATIVE_SIDE = frozenset({"no"})


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
    """Determine if a road should be excluded from geometric gap detection.

    We skip ONLY when the OSM tags explicitly document a physical reality
    that is genuinely one-sided (or zero-sided), so a single drawn
    footway (or none) is correct and not a mapping gap to surface.

    Skip cases:

    1. Asymmetric per-side tags — one side positive, other side negative
       (e.g. ``sidewalk:left=yes sidewalk:right=no``,
       ``sidewalk:left=separate sidewalk:right=no``).  The mapper has
       said "there's a sidewalk on this side, not on that one".
    2. ``sidewalk=left`` or ``sidewalk=right`` — explicit single side.
    3. ``sidewalk=no`` or ``sidewalk:both=no`` — no sidewalk at all.
       Not a one-sided situation; a different QA concern.

    DO NOT skip:

    - ``sidewalk=both``, ``sidewalk=yes``, ``sidewalk:both=yes``,
      ``sidewalk=separate``, ``sidewalk:both=separate``, missing tags…
      These say something about physical reality, but tell us nothing
      about whether OSM actually has both sidewalks **drawn** as
      separate ways — which is what this layer is meant to detect.
    """
    # ── 1. Per-side asymmetry explicitly documented ───────────────────────
    if sw_l in _POSITIVE_SIDE and sw_r in _NEGATIVE_SIDE:
        return True
    if sw_r in _POSITIVE_SIDE and sw_l in _NEGATIVE_SIDE:
        return True

    # ── 2. Single-side explicit ───────────────────────────────────────────
    if sw in ("left", "right"):
        return True

    # ── 3. No sidewalk at all (different problem) ─────────────────────────
    if sw in _NEGATIVE_SIDE:
        return True
    if sw_b in _NEGATIVE_SIDE:
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def detect_sidewalk_gaps(
    roads_geojson_path: str,
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
) -> dict:
    """Detect roads with a footway=sidewalk drawn on one side only.

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
    print("Detecting sidewalk gaps (footway=sidewalk drawn on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m | "
          f"Max angle: {MAX_ANGLE_DIFF}° | "
          f"Min coverage: {SIDEWALK_GAP_MIN_COVERAGE:.0%}")

    # ── Build footway spatial index from raw footways ─────────────────────
    # A way counts as a sidewalk for gap detection when it is either:
    #   - highway=footway + footway=sidewalk/link  (canonical sidewalk)
    #   - highway=pedestrian (any sub-tag)         (pedestrian-zone sidewalks)
    # Generic footways (park paths, plaza crossings, shortcuts) are
    # excluded — without this filter, the park path at Place du Grand
    # Sablon was mistaken for a parallel sidewalk.
    print(f"  Reading footways from: {footways_geojson_path}")
    fw_gdf = gpd.read_file(footways_geojson_path)
    fw_gdf = fw_gdf[fw_gdf.geometry.geom_type == "LineString"].copy()
    fw_gdf = fw_gdf.to_crs("EPSG:31370")
    total_fw = len(fw_gdf)

    hw_col = fw_gdf.get("highway")
    fw_col = fw_gdf.get("footway")

    if hw_col is None:
        # Highway tag missing entirely — severely degraded; accept all
        # features and warn loudly.
        print("  WARN: 'highway' tag missing from export, using all features")
        sw_fw = fw_gdf
    else:
        hw_lower = hw_col.fillna("").astype(str).str.lower()
        is_pedestrian = hw_lower == "pedestrian"
        if fw_col is None:
            # No footway sub-tag info — keep highway=pedestrian, and fall
            # back to all highway=footway (will produce some false
            # positives at parks but is still better than nothing).
            print("  WARN: 'footway' sub-tag missing, accepting all footways")
            is_sidewalk_footway = hw_lower == "footway"
        else:
            fw_lower = fw_col.fillna("").astype(str).str.lower()
            is_sidewalk_footway = (
                (hw_lower == "footway")
                & fw_lower.isin(_SIDEWALK_FOOTWAY_VALUES)
            )
        sw_fw = fw_gdf[is_pedestrian | is_sidewalk_footway]
        n_pedestrian = int(is_pedestrian.sum())
        n_sidewalk_fw = int(is_sidewalk_footway.sum())
        print(f"  Sources — highway=pedestrian: {n_pedestrian} | "
              f"footway=sidewalk/link: {n_sidewalk_fw}")

    print(f"  Footway ways total: {total_fw} | "
          f"kept as sidewalk: {len(sw_fw)}")

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
    print(f"  Sidewalk-equivalent segments indexed: {len(footway_geoms)}")

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

        # ── Skip only when asymmetry is explicitly documented ─────────────
        sw = _safe_str(road.get("sidewalk"))
        sw_l = _safe_str(road.get("sidewalk:left"))
        sw_r = _safe_str(road.get("sidewalk:right"))
        sw_b = _safe_str(road.get("sidewalk:both"))
        if _should_skip_road(sw, sw_l, sw_r, sw_b):
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
          f"Skipped (documented asymmetry / no sidewalk): {n_skipped_documented}")
    print(f"  Both sides drawn: {n_both} | One side (gap): {n_gap} | "
          f"Neither side drawn: {n_none}")
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
        "footway_sidewalk_segments_indexed": len(footway_geoms),
        "footway_total_segments": total_fw,
    }
