from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.strtree import STRtree

from config import FOOT_ALLOWED, ROAD_TYPES_SIDEWALK_EXPECTED
from timing import step

_GAP_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

SIDEWALK_GAP_OFFSET_M = float(os.environ.get("SIDEWALK_GAP_OFFSET_M", 7))

SIDEWALK_GAP_SEARCH_M = float(os.environ.get("SIDEWALK_GAP_SEARCH_M", 7))

MAX_ANGLE_DIFF = float(os.environ.get("SIDEWALK_GAP_MAX_ANGLE", 35))

SIDEWALK_GAP_MIN_COVERAGE = float(os.environ.get("SIDEWALK_GAP_MIN_COVERAGE", 0.4))

_MIN_ROAD_LENGTH = 20.0

_MIN_CLIPPED_LENGTH = 3.0


def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
    return str(val).strip().lower()


def _line_bearing(geom) -> float | None:
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
    if footway_bearing is None:
        return False
    diff = abs(road_bearing - footway_bearing)
    if diff > 90:
        diff = 180 - diff
    return diff <= MAX_ANGLE_DIFF


def _iter_linestrings(geom):
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


_SIDEWALK_ABSENT = frozenset({"no", "none"})


def _side_values(sw: str, sw_left: str, sw_right: str, sw_both: str) -> tuple[str, str]:
    base_left = base_right = ""
    if sw in _SIDEWALK_ABSENT:
        base_left = base_right = "no"
    elif sw == "left":
        base_left, base_right = "yes", "no"
    elif sw == "right":
        base_left, base_right = "no", "yes"
    elif sw:
        base_left = base_right = sw
    left = sw_left or sw_both or base_left
    right = sw_right or sw_both or base_right
    return left, right


def _should_skip_road(sw: str, sw_left: str, sw_right: str, sw_both: str) -> bool:
    left, right = _side_values(sw, sw_left, sw_right, sw_both)
    return left in _SIDEWALK_ABSENT or right in _SIDEWALK_ABSENT


def _foot_cycleway_mask(gdf):
    for col in ("highway", "foot"):
        if col not in gdf.columns:
            gdf[col] = ""
    highway = gdf["highway"].apply(_safe_str)
    foot = gdf["foot"].apply(_safe_str)
    return (highway == "cycleway") & foot.isin(FOOT_ALLOWED)


def _load_foot_cycleways(cycleways_geojson_path: str | None) -> tuple[list, dict]:
    if not cycleways_geojson_path or not os.path.exists(cycleways_geojson_path):
        if cycleways_geojson_path:
            print(f"  Cycleways file not found, skipped: {cycleways_geojson_path}")
        return [], {"raw": 0, "kept": 0}
    print(f"  Reading raw cycleways from: {cycleways_geojson_path}")
    cw_gdf = gpd.read_file(cycleways_geojson_path)
    cw_gdf = cw_gdf[cw_gdf.geometry.geom_type == "LineString"].copy()
    n_raw = len(cw_gdf)
    if n_raw == 0:
        return [], {"raw": 0, "kept": 0}
    cw_gdf = cw_gdf.to_crs("EPSG:31370")
    cw_gdf = cw_gdf[_foot_cycleway_mask(cw_gdf)]
    n_kept = len(cw_gdf)
    print(f"  Cycleways with foot access kept: {n_kept} / {n_raw}")
    return list(cw_gdf.geometry), {"raw": n_raw, "kept": n_kept}


def _load_sidewalk_footways(footways_geojson_path: str) -> tuple[list, dict]:
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
    mask_traffic_island = (
        (fw_gdf["_highway"] == "footway") & (fw_gdf["_footway"] == "traffic_island")
    )
    mask_pedestrian = (fw_gdf["_highway"] == "pedestrian")
    keep_mask = (
        mask_sidewalk | mask_link | mask_crossing | mask_traffic_island
        | mask_pedestrian
    )

    n_sidewalk = int(mask_sidewalk.sum())
    n_link = int(mask_link.sum())
    n_crossing = int(mask_crossing.sum())
    n_traffic_island = int(mask_traffic_island.sum())
    n_pedestrian = int(mask_pedestrian.sum())
    n_kept = int(keep_mask.sum())
    n_dropped = n_raw - n_kept

    fw_gdf = fw_gdf[keep_mask]
    geoms = list(fw_gdf.geometry)

    print(f"  Footways kept: {n_kept} "
          f"(sidewalk: {n_sidewalk} | link: {n_link} | crossing: {n_crossing} "
          f"| traffic_island: {n_traffic_island} | pedestrian: {n_pedestrian}) "
          f"| dropped: {n_dropped} / {n_raw}")

    return geoms, {
        "raw": n_raw,
        "kept": n_kept,
        "kept_sidewalk": n_sidewalk,
        "kept_link": n_link,
        "kept_crossing": n_crossing,
        "kept_traffic_island": n_traffic_island,
        "kept_pedestrian": n_pedestrian,
        "dropped": n_dropped,
    }


def detect_sidewalk_gaps(
    roads_geojson_path: str,
    footways_geojson_path: str,
    cycleways_geojson_path: str | None = None,
) -> dict:
    print("Detecting sidewalk gaps (footway on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m | "
          f"Max angle: {MAX_ANGLE_DIFF}° | "
          f"Min coverage: {SIDEWALK_GAP_MIN_COVERAGE:.0%}")

    with step("load + filter footways"):
        footway_geoms, footway_filter_stats = _load_sidewalk_footways(
            footways_geojson_path,
        )
        cycleway_geoms, cycleway_filter_stats = _load_foot_cycleways(
            cycleways_geojson_path,
        )
        footway_geoms = footway_geoms + cycleway_geoms
        footway_filter_stats["kept_cycleway_foot"] = cycleway_filter_stats["kept"]
        footway_tree = STRtree(footway_geoms) if footway_geoms else None
    print(f"  Footway segments indexed: {len(footway_geoms)} "
          f"(incl. {len(cycleway_geoms)} cycleways with foot access)")

    with step("load + filter roads"):
        print(f"  Reading raw roads from: {roads_geojson_path}")
        roads_gdf = gpd.read_file(roads_geojson_path)
        roads_gdf = roads_gdf[roads_gdf.geometry.geom_type == "LineString"].copy()
        roads_gdf = roads_gdf.to_crs("EPSG:31370")
        roads_gdf = roads_gdf[roads_gdf["highway"].isin(_GAP_ROAD_TYPES)]
        roads_gdf = roads_gdf[roads_gdf.geometry.length >= _MIN_ROAD_LENGTH]
    print(f"  Road ways after filtering: {len(roads_gdf)}")

    rows: list[dict] = []
    candidate_rows: list[dict] = []
    n_roads = 0
    n_both = 0
    n_none = 0
    n_gap = 0
    n_skipped_no_sidewalk = 0
    n_separate_candidates = 0
    gap_length_m = 0.0
    both_length_m = 0.0
    none_length_m = 0.0
    separate_candidate_length_m = 0.0

    with step("main road analysis loop"):
        for _, road in roads_gdf.iterrows():
            geom = road.geometry

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

            try:
                left_line = geom.offset_curve(SIDEWALK_GAP_OFFSET_M)
                right_line = geom.offset_curve(-SIDEWALK_GAP_OFFSET_M)
            except Exception:
                continue

            if left_line.is_empty or right_line.is_empty:
                continue

            left_zone = left_line.buffer(SIDEWALK_GAP_SEARCH_M)
            right_zone = right_line.buffer(SIDEWALK_GAP_SEARCH_M)

            if footway_tree is None:
                left_candidates: list[int] = []
                right_candidates: list[int] = []
            else:
                left_candidates = footway_tree.query(left_zone)
                right_candidates = footway_tree.query(right_zone)

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
                if not sw and not sw_l and not sw_r and not sw_b:
                    n_separate_candidates += 1
                    separate_candidate_length_m += road_length
                    candidate_rows.append({
                        "geometry": geom,
                        "name": _safe_str(road.get("name")) or "",
                    })
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

    with step("write sidewalk_gaps.geojson"):
        fb = {"geometry": None, "name": ""}
        if rows:
            gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
        gdf.to_file("sidewalk_gaps.geojson", driver="GeoJSON")

    with step("write sidewalk_separate_candidates.geojson"):
        fb_cand = {"geometry": None, "name": ""}
        if candidate_rows:
            candidates_gdf = gpd.GeoDataFrame(
                candidate_rows, crs="EPSG:31370",
            ).to_crs("EPSG:4326")
        else:
            candidates_gdf = gpd.GeoDataFrame([fb_cand], crs="EPSG:4326")
        candidates_gdf.to_file(
            "sidewalk_separate_candidates.geojson", driver="GeoJSON",
        )

    print(f"  Roads analysed: {n_roads} | "
          f"Skipped (sidewalk=no on a side): {n_skipped_no_sidewalk}")
    print(f"  Both sides: {n_both} | One side (gap): {n_gap} | "
          f"Neither side: {n_none}")
    print(f"  Sidewalk gaps exported: {len(rows)}")
    print(f"  sidewalk:both=separate candidates (no tag, both sides covered): "
          f"{n_separate_candidates}")

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
        "separate_candidates": n_separate_candidates,
        "separate_candidates_length_km": round(
            separate_candidate_length_m / 1000, 2,
        ),
    }
