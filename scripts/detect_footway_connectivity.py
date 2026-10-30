from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.geometry import Point
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from timing import step

_CROSSING_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}
_MIN_ROAD_LENGTH = 15.0


FOOTWAY_CONN_ENDPOINT_TOL_M = float(os.environ.get("FOOTWAY_CONN_ENDPOINT_TOL_M", 3.0))

FOOTWAY_CONN_TIP_MARGIN_M = float(os.environ.get("FOOTWAY_CONN_TIP_MARGIN_M", 2.0))

FOOTWAY_CONN_MAX_LEN_M = float(os.environ.get("FOOTWAY_CONN_MAX_LEN_M", 40.0))

_MIN_CAND_LEN_M = 1.0


def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


def _iter_points(geom):
    gt = geom.geom_type
    if geom.is_empty:
        return
    if gt == "Point":
        yield geom
    elif gt == "MultiPoint":
        yield from geom.geoms
    elif gt == "LineString":
        yield geom.interpolate(0.5, normalized=True)
    elif gt == "MultiLineString":
        for sub in geom.geoms:
            if not sub.is_empty:
                yield sub.interpolate(0.5, normalized=True)
    elif gt == "GeometryCollection":
        for sub in geom.geoms:
            yield from _iter_points(sub)


def _road_perp_at(road_geom, pt: Point, step_m: float = 3.0):
    d = road_geom.project(pt)
    p1 = road_geom.interpolate(max(0.0, d - step_m))
    p2 = road_geom.interpolate(min(road_geom.length, d + step_m))
    dx, dy = p2.x - p1.x, p2.y - p1.y
    norm = math.hypot(dx, dy)
    if norm < 0.01:
        return None
    return (-dy / norm, dx / norm)


def _side(perp, origin: Point, pt: Point) -> float:
    return (pt.x - origin.x) * perp[0] + (pt.y - origin.y) * perp[1]


def _touches_sidewalk(pt: Point, tree: STRtree, geoms: list) -> bool:
    zone = pt.buffer(FOOTWAY_CONN_ENDPOINT_TOL_M)
    return any(geoms[i].intersects(zone) for i in tree.query(zone))


_ALREADY_CLASSIFIED = frozenset({"crossing", "sidewalk", "traffic_island"})


def _load_footway_candidates(footways_path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway", "location"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (~gdf["footway"].apply(_safe_str).isin(_ALREADY_CLASSIFIED)) &
        (gdf["location"].apply(_safe_str) != "underground")
    )
    return gdf[mask].reset_index(drop=True)


def _load_sidewalk_ways(footways_path: str) -> tuple[list, STRtree | None]:
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway", "location"):
        if col not in gdf.columns:
            gdf[col] = ""
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "sidewalk") &
        (gdf["location"].apply(_safe_str) != "underground")
    )
    geoms = list(gdf[mask].geometry)
    return geoms, (STRtree(geoms) if geoms else None)


def _load_roads(roads_path: str) -> tuple[gpd.GeoDataFrame, list, STRtree | None]:
    gdf = gpd.read_file(roads_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    gdf = gdf[gdf["highway"].isin(_CROSSING_ROAD_TYPES)]
    gdf = gdf[gdf.geometry.length >= _MIN_ROAD_LENGTH]
    gdf = gdf.reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, (STRtree(geoms) if geoms else None)


def _write_empty_output() -> None:
    gpd.GeoDataFrame(
        [{"geometry": None, "name": "", "length_m": 0.0, "osm_id": 0}],
        crs="EPSG:4326",
    ).to_file("footway_crossing_candidates.geojson", driver="GeoJSON")


def detect_footway_connectivity_candidates(
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    roads_geojson_path:    str = "sidewalk_roads_raw.geojson",
) -> dict:
    print("Detecting footway/sidewalk connectivity crossing candidates...")
    print(
        f"  Endpoint tolerance: {FOOTWAY_CONN_ENDPOINT_TOL_M} m | "
        f"Tip margin: {FOOTWAY_CONN_TIP_MARGIN_M} m | "
        f"Max length: {FOOTWAY_CONN_MAX_LEN_M} m"
    )

    with step("load footway candidates"):
        cand_gdf = _load_footway_candidates(footways_geojson_path)
    print(f"  Candidate footways (highway=footway, not already crossing/"
          f"sidewalk/traffic_island): {len(cand_gdf)}")

    with step("load sidewalks"):
        sw_geoms, sw_tree = _load_sidewalk_ways(footways_geojson_path)
    print(f"  footway=sidewalk ways: {len(sw_geoms)}")

    with step("load eligible roads"):
        roads_gdf, road_geoms, road_tree = _load_roads(roads_geojson_path)
    print(f"  Eligible road segments: {len(roads_gdf)}")

    if cand_gdf.empty or sw_tree is None or road_tree is None:
        print("  Nothing to analyse, skipping.")
        _write_empty_output()
        return {"candidates_scanned": int(len(cand_gdf)), "flagged": 0}

    has_name_col = "name" in roads_gdf.columns

    rows: list[dict] = []
    n_too_short_or_long = 0
    n_no_road_cross      = 0
    n_same_side          = 0
    n_no_sidewalk_both   = 0
    n_flagged            = 0

    with step("candidate analysis loop"):
        for _, cand in cand_gdf.iterrows():
            geom = cand.geometry
            length = geom.length

            if length < _MIN_CAND_LEN_M or length > FOOTWAY_CONN_MAX_LEN_M:
                n_too_short_or_long += 1
                continue

            p_start = Point(geom.coords[0])
            p_end   = Point(geom.coords[-1])

            best_ri, best_cross_pt, best_mid_dist = None, None, None
            for ri in road_tree.query(geom):
                road_geom = road_geoms[ri]
                if not geom.intersects(road_geom):
                    continue
                inter = geom.intersection(road_geom)
                for cross_pt in _iter_points(inter):
                    d = geom.project(cross_pt)
                    if d < FOOTWAY_CONN_TIP_MARGIN_M or d > length - FOOTWAY_CONN_TIP_MARGIN_M:
                        continue
                    mid_dist = abs(d - length / 2.0)
                    if best_mid_dist is None or mid_dist < best_mid_dist:
                        best_mid_dist, best_ri, best_cross_pt = mid_dist, ri, cross_pt

            if best_ri is None:
                n_no_road_cross += 1
                continue

            road_geom = road_geoms[best_ri]
            perp = _road_perp_at(road_geom, best_cross_pt)
            if perp is None:
                n_no_road_cross += 1
                continue
            side_start = _side(perp, best_cross_pt, p_start)
            side_end   = _side(perp, best_cross_pt, p_end)
            if side_start == 0 or side_end == 0 or (side_start > 0) == (side_end > 0):
                n_same_side += 1
                continue

            if not (_touches_sidewalk(p_start, sw_tree, sw_geoms) and
                    _touches_sidewalk(p_end, sw_tree, sw_geoms)):
                n_no_sidewalk_both += 1
                continue

            n_flagged += 1
            road_name = _safe_str(roads_gdf.iloc[best_ri]["name"]) if has_name_col else ""
            try:
                osm_id = int(cand.get("@id") or 0)
            except (TypeError, ValueError):
                osm_id = 0

            rows.append({
                "geometry": geom,
                "name": road_name,
                "length_m": round(length, 1),
                "osm_id": osm_id,
            })

    with step("write footway_crossing_candidates.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = gpd.GeoDataFrame(
                [{"geometry": None, "name": "", "length_m": 0.0, "osm_id": 0}],
                crs="EPSG:4326",
            )
        out_gdf.to_file("footway_crossing_candidates.geojson", driver="GeoJSON")

    n_total = len(cand_gdf)
    print(f"  Candidates scanned:                      {n_total}")
    print(f"  Skipped, length out of range:           {n_too_short_or_long}")
    print(f"  Skipped, no mid-way road crossing:      {n_no_road_cross}")
    print(f"  Skipped, sidewalks on same side:        {n_same_side}")
    print(f"  Skipped, no sidewalk on both ends:      {n_no_sidewalk_both}")
    print(f"  Flagged as crossing candidates:          {n_flagged}")

    return {
        "candidates_scanned":       n_total,
        "length_out_of_range":      n_too_short_or_long,
        "no_midway_road_crossing":  n_no_road_cross,
        "sidewalks_same_side":      n_same_side,
        "no_sidewalk_both_ends":    n_no_sidewalk_both,
        "flagged":                  n_flagged,
    }
