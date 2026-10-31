from __future__ import annotations

import json
import math
import os

import geopandas as gpd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from timing import step

_CROSSING_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}
_MIN_ROAD_LENGTH = 15.0


CROSSING_NODE_ROAD_SEARCH_M  = float(os.environ.get("CROSSING_NODE_ROAD_SEARCH_M",  20.0))
CROSSING_WAY_SEARCH_RADIUS_M = float(os.environ.get("CROSSING_WAY_SEARCH_RADIUS_M", 20.0))
CROSSING_NODE_CONNECTED_M    = float(os.environ.get("CROSSING_NODE_CONNECTED_M",     3.0))
CROSSING_SIDEWALK_OFFSET_M   = float(os.environ.get("CROSSING_SIDEWALK_OFFSET_M",    7.0))
CROSSING_SIDEWALK_SEARCH_M   = float(os.environ.get("CROSSING_SIDEWALK_SEARCH_M",   15.0))

CROSSING_SIDEWALK_MAX_ANGLE  = float(os.environ.get("CROSSING_SIDEWALK_MAX_ANGLE",  40.0))
CROSSING_WRONG_TAG_SNAP_M    = float(os.environ.get("CROSSING_WRONG_TAG_SNAP_M",     0.5))

_WRONG_FOOTWAY_VALUES = frozenset({"sidewalk"})

_MIN_CLIP_LEN = 3.0


def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


def _safe_int(val) -> int:
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return 0
        return int(val)
    except (TypeError, ValueError):
        return 0


def _road_geometry_at(
    road_geom, node_pt, step: float = 3.0
) -> tuple[tuple[float, float] | None, float | None]:
    d  = road_geom.project(node_pt)
    p1 = road_geom.interpolate(max(0.0, d - step))
    p2 = road_geom.interpolate(min(road_geom.length, d + step))
    dx, dy = p2.x - p1.x, p2.y - p1.y
    norm = math.hypot(dx, dy)
    if norm < 0.01:
        return None, None
    perp    = (-dy / norm, dx / norm)
    bearing = math.degrees(math.atan2(dy, dx)) % 180
    return perp, bearing


def _sidewalk_zones(
    node_pt: Point, perp: tuple[float, float]
) -> tuple:
    px, py = perp
    left  = Point(node_pt.x + px * CROSSING_SIDEWALK_OFFSET_M,
                  node_pt.y + py * CROSSING_SIDEWALK_OFFSET_M)
    right = Point(node_pt.x - px * CROSSING_SIDEWALK_OFFSET_M,
                  node_pt.y - py * CROSSING_SIDEWALK_OFFSET_M)
    return left.buffer(CROSSING_SIDEWALK_SEARCH_M), right.buffer(CROSSING_SIDEWALK_SEARCH_M)


def _iter_linestrings(geom):
    gt = geom.geom_type
    if gt == "LineString":
        yield geom
    elif gt in ("MultiLineString", "GeometryCollection"):
        for sub in geom.geoms:
            yield from _iter_linestrings(sub)


def _piece_bearing(piece) -> float | None:
    try:
        coords = list(piece.coords)
    except Exception:
        return None
    if len(coords) < 2:
        return None
    dx = coords[-1][0] - coords[0][0]
    dy = coords[-1][1] - coords[0][1]
    norm = math.hypot(dx, dy)
    if norm < 0.01:
        return None
    return math.degrees(math.atan2(dy, dx)) % 180


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b)
    return 180 - d if d > 90 else d


def _has_parallel_sidewalk(
    zone, road_bearing: float, tree: STRtree, geoms: list
) -> bool:
    for i in tree.query(zone):
        fw = geoms[i]
        if not fw.intersects(zone):
            continue
        try:
            clipped = fw.intersection(zone)
        except Exception:
            clipped = fw
        if clipped.is_empty:
            continue
        for piece in _iter_linestrings(clipped):
            if piece.length < _MIN_CLIP_LEN:
                continue
            bearing = _piece_bearing(piece)
            if bearing is None:
                continue
            if _angle_diff(road_bearing, bearing) <= CROSSING_SIDEWALK_MAX_ANGLE:
                return True
    return False


def _intersects_any(zone, tree: STRtree, geoms: list) -> bool:
    return any(geoms[i].intersects(zone) for i in tree.query(zone))


def _load_crossing_nodes(highways_path: str) -> gpd.GeoDataFrame:
    with open(highways_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    features = raw.get("features", [])
    if isinstance(features, dict):
        features = features.get("features", [])
    rows = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom  = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if geom.get("type") != "Point":
            continue
        if _safe_str(props.get("highway")) != "crossing":
            continue
        try:
            osm_id = int(props.get("@id") or 0)
        except (TypeError, ValueError):
            osm_id = 0
        try:
            rows.append({
                "geometry": shape(geom),
                "continuous": _safe_str(props.get("crossing:continuous")) == "yes",
                "osm_id": osm_id,
            })
        except Exception:
            continue
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_crs("EPSG:31370")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs("EPSG:31370")


def _load_crossing_ways(footways_path: str) -> tuple[list, STRtree | None]:
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


def _load_footway_ways(footways_path: str) -> tuple[list, STRtree | None]:
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    if "highway" not in gdf.columns:
        gdf["highway"] = ""
    mask = gdf["highway"].apply(_safe_str) == "footway"
    geoms = list(gdf[mask].geometry)
    return geoms, (STRtree(geoms) if geoms else None)


def _load_pedestrian_ways(footways_path: str) -> tuple[list, STRtree | None]:
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    if "highway" not in gdf.columns:
        gdf["highway"] = ""
    mask = gdf["highway"].apply(_safe_str) == "pedestrian"
    geoms = list(gdf[mask].geometry)
    return geoms, (STRtree(geoms) if geoms else None)


def _load_sidewalk_ways(footways_path: str) -> tuple[list, STRtree | None]:
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "sidewalk")
    )
    geoms = list(gdf[mask].geometry)
    print(f"  footway=sidewalk ways: {len(geoms)}")
    return geoms, (STRtree(geoms) if geoms else None)


def _load_wrong_tag_ways(footways_path: str) -> tuple[list, list, list, STRtree | None]:
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway", "location"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str).isin(_WRONG_FOOTWAY_VALUES)) &
        (gdf["location"].apply(_safe_str) != "underground")
    )
    sub = gdf[mask]
    geoms = list(sub.geometry)
    ids = [_safe_int(v) for v in sub["@id"]]
    values = [_safe_str(v) for v in sub["footway"]]
    return geoms, ids, values, (STRtree(geoms) if geoms else None)


def _find_wrong_tag_way(
    node_pt: Point, tree: STRtree | None, geoms: list, ids: list, values: list
) -> tuple[int, str] | None:
    if tree is None:
        return None
    zone = node_pt.buffer(CROSSING_WRONG_TAG_SNAP_M)
    hits = [i for i in tree.query(zone)
            if geoms[i].distance(node_pt) <= CROSSING_WRONG_TAG_SNAP_M]
    if not hits:
        return None
    best = min(hits, key=lambda i: geoms[i].distance(node_pt))
    return ids[best], values[best]


def _load_roads(roads_path: str) -> tuple[gpd.GeoDataFrame, list, STRtree]:
    gdf = gpd.read_file(roads_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    gdf = gdf[gdf["highway"].isin(_CROSSING_ROAD_TYPES)]
    gdf = gdf[gdf.geometry.length >= _MIN_ROAD_LENGTH]
    gdf = gdf.reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, STRtree(geoms)


def _load_excluded_roads(
    paths_and_types: list[tuple[str, str]],
) -> tuple[list, STRtree | None]:
    all_geoms: list = []
    for path, hw_tag in paths_and_types:
        try:
            gdf = gpd.read_file(path)
        except Exception as e:
            print(f"  {path} not available: {e}")
            continue
        gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
        if "highway" not in gdf.columns:
            continue
        gdf = gdf[gdf["highway"].apply(_safe_str) == hw_tag]
        gdf = gdf[gdf.geometry.length >= 3.0]
        n = len(gdf)
        all_geoms.extend(list(gdf.geometry))
        print(f"    {hw_tag}: {n}")
    if not all_geoms:
        return [], None
    return all_geoms, STRtree(all_geoms)


def detect_missing_crossings(
    highways_geojson_path:      str = "highways.geojson",
    footways_geojson_path:      str = "sidewalk_footways_raw.geojson",
    roads_geojson_path:         str = "sidewalk_roads_raw.geojson",
    service_roads_geojson_path: str = "service_roads_raw.geojson",
    cycleways_geojson_path:     str = "cycleways_raw.geojson",
    tracks_geojson_path:        str = "tracks_raw.geojson",
) -> dict:
    print("Detecting missing crossing ways / tags...")
    print(
        f"  Tier-1 (footway=crossing): {CROSSING_WAY_SEARCH_RADIUS_M} m | "
        f"Tier-2 (any footway / shared node): {CROSSING_NODE_CONNECTED_M} m | "
        f"Sidewalk offset {CROSSING_SIDEWALK_OFFSET_M} m "
        f"+ radius {CROSSING_SIDEWALK_SEARCH_M} m "
        f"+ max angle {CROSSING_SIDEWALK_MAX_ANGLE}°"
    )

    with step("load crossing nodes"):
        crossing_nodes = _load_crossing_nodes(highways_geojson_path)
    print(f"  highway=crossing nodes: {len(crossing_nodes)}")

    if crossing_nodes.empty:
        print("  No crossing nodes, skipping.")
        _write_empty_output()
        return {"crossing_nodes_found": 0, "missing_crossings_detected": 0}

    with step("load footway=crossing ways (tier 1)"):
        cw_geoms, cw_tree = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways: {len(cw_geoms)}")

    with step("load all footways (tier 2)"):
        fw_geoms, fw_tree = _load_footway_ways(footways_geojson_path)
        ped_geoms, ped_tree = _load_pedestrian_ways(footways_geojson_path)
    print(f"  highway=footway ways: {len(fw_geoms)} | "
          f"highway=pedestrian ways: {len(ped_geoms)}")

    with step("load footway=sidewalk ways"):
        sw_geoms, sw_tree = _load_sidewalk_ways(footways_geojson_path)

    with step("load wrongly tagged crossing ways"):
        wt_geoms, wt_ids, wt_values, wt_tree = _load_wrong_tag_ways(footways_geojson_path)
    print(f"  wrong-tag candidate ways: {len(wt_geoms)}")

    with step("load eligible roads"):
        roads_gdf, road_geoms, road_tree = _load_roads(roads_geojson_path)
    print(f"  Eligible road segments: {len(roads_gdf)}")

    with step("load excluded ways (service / cycleway / track)"):
        excl_geoms, excl_tree = _load_excluded_roads([
            (service_roads_geojson_path, "service"),
            (cycleways_geojson_path,     "cycleway"),
            (tracks_geojson_path,        "track"),
        ])
    print(f"  Excluded way segments total: {len(excl_geoms)}")

    if sw_tree is None:
        print("  No footway=sidewalk ways, skipping.")
        _write_empty_output()
        return {"crossing_nodes_found": len(crossing_nodes),
                "missing_crossings_detected": 0}

    rows: list[dict] = []
    n_no_road     = 0
    n_excluded    = 0
    n_continuous  = 0
    n_fully_ok    = 0
    n_pedestrian_only = 0
    n_no_sw       = 0
    n_missing_way = 0
    n_missing_tag = 0
    n_wrong_tag   = 0

    with step("crossing node analysis loop"):
        for _, node_row in crossing_nodes.iterrows():
            node_pt = node_row.geometry

            road_cands = road_tree.query(node_pt.buffer(CROSSING_NODE_ROAD_SEARCH_M))
            if not len(road_cands):
                n_no_road += 1
                continue

            best_idx = min(road_cands,
                           key=lambda i: road_geoms[i].distance(node_pt))
            road_geom = road_geoms[best_idx]
            best_dist = road_geom.distance(node_pt)

            if excl_tree is not None:
                excl_zone = node_pt.buffer(CROSSING_NODE_ROAD_SEARCH_M)
                on_excluded = False
                for ei in excl_tree.query(excl_zone):
                    if excl_geoms[ei].distance(node_pt) <= best_dist:
                        on_excluded = True
                        break
                if on_excluded:
                    n_excluded += 1
                    continue

            continuous = bool(node_row.get("continuous"))
            wrong = None
            if not continuous and best_dist <= CROSSING_WRONG_TAG_SNAP_M:
                wrong = _find_wrong_tag_way(node_pt, wt_tree, wt_geoms, wt_ids, wt_values)
            if wrong is not None:
                n_wrong_tag += 1
                rows.append(_flag_row(
                    node_pt, node_row, road_geom, roads_gdf, best_idx,
                    "wrong_tag", sw_tree, sw_geoms, cw_tree, cw_geoms,
                    wrong_way_id=wrong[0], wrong_value=wrong[1],
                ))
                continue

            tier1 = (
                cw_tree is not None and
                _intersects_any(node_pt.buffer(CROSSING_WAY_SEARCH_RADIUS_M),
                                cw_tree, cw_geoms)
            )
            if tier1:
                n_fully_ok += 1
                continue

            connected_footway = (
                fw_tree is not None and
                _intersects_any(node_pt.buffer(CROSSING_NODE_CONNECTED_M),
                                fw_tree, fw_geoms)
            )
            connected_pedestrian = (
                ped_tree is not None and
                _intersects_any(node_pt.buffer(CROSSING_NODE_CONNECTED_M),
                                ped_tree, ped_geoms)
            )
            tier2 = connected_footway or connected_pedestrian
            crossing_type = "missing_tag" if tier2 else "missing_way"

            if crossing_type == "missing_tag" and not connected_footway:
                n_pedestrian_only += 1
                continue

            if crossing_type == "missing_tag" and bool(node_row.get("continuous")):
                n_continuous += 1
                continue

            perp, road_bearing = _road_geometry_at(road_geom, node_pt)
            if perp is None:
                n_no_road += 1
                continue

            left_zone, right_zone = _sidewalk_zones(node_pt, perp)
            has_left  = _has_parallel_sidewalk(left_zone,  road_bearing, sw_tree, sw_geoms)
            has_right = _has_parallel_sidewalk(right_zone, road_bearing, sw_tree, sw_geoms)

            if not (has_left and has_right):
                n_no_sw += 1
                continue

            if crossing_type == "missing_way":
                n_missing_way += 1
            else:
                n_missing_tag += 1

            rows.append(_flag_row(
                node_pt, node_row, road_geom, roads_gdf, best_idx,
                crossing_type, sw_tree, sw_geoms, cw_tree, cw_geoms,
                has_left=has_left, has_right=has_right,
            ))

    with step("write missing_crossings.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = gpd.GeoDataFrame(
                [_empty_row()],
                crs="EPSG:4326",
            )
        out_gdf.to_file("missing_crossings.geojson", driver="GeoJSON")

    n_total = len(crossing_nodes)
    print(f"  Nodes analysed:                          {n_total}")
    print(f"  Skipped, no eligible road:              {n_no_road}")
    print(f"  Skipped, on service / cycleway / track: {n_excluded}")
    print(f"  Skipped, crossing:continuous=yes:       {n_continuous}")
    print(f"  Skipped, crossing fully mapped (t1):    {n_fully_ok}")
    print(f"  Skipped, connected only to pedestrian:  {n_pedestrian_only}")
    print(f"  Skipped, no parallel sidewalk (both):   {n_no_sw}")
    print(f"  Missing crossing WAY detected:           {n_missing_way}")
    print(f"  Missing footway=crossing TAG detected:   {n_missing_tag}")
    print(f"  Wrong footway=* TAG on crossing way:     {n_wrong_tag}")

    return {
        "crossing_nodes_found":        n_total,
        "no_eligible_road":            n_no_road,
        "on_excluded_way":             n_excluded,
        "crossing_continuous":         n_continuous,
        "crossing_fully_mapped":       n_fully_ok,
        "connected_pedestrian_only":   n_pedestrian_only,
        "sidewalk_missing_or_skewed":  n_no_sw,
        "missing_crossing_way":        n_missing_way,
        "missing_crossing_tag":        n_missing_tag,
        "wrong_crossing_tag":          n_wrong_tag,
        "missing_crossings_detected":  n_missing_way + n_missing_tag + n_wrong_tag,
    }


def _flag_row(
    node_pt, node_row, road_geom, roads_gdf, best_idx, crossing_type,
    sw_tree, sw_geoms, cw_tree, cw_geoms,
    has_left: bool | None = None, has_right: bool | None = None,
    wrong_way_id: int = 0, wrong_value: str = "",
) -> dict:
    if has_left is None or has_right is None:
        has_left = has_right = False
        perp, road_bearing = _road_geometry_at(road_geom, node_pt)
        if perp is not None and sw_tree is not None:
            left_zone, right_zone = _sidewalk_zones(node_pt, perp)
            has_left  = _has_parallel_sidewalk(left_zone,  road_bearing, sw_tree, sw_geoms)
            has_right = _has_parallel_sidewalk(right_zone, road_bearing, sw_tree, sw_geoms)

    road_name = ""
    if "name" in roads_gdf.columns:
        road_name = _safe_str(roads_gdf.iloc[best_idx]["name"])

    nearest_tag_m = -1.0
    if cw_tree is not None and len(cw_geoms):
        ni = cw_tree.nearest(node_pt)
        nearest_tag_m = round(float(cw_geoms[ni].distance(node_pt)), 1)

    return {
        "geometry": node_pt,
        "name":  road_name,
        "type":  crossing_type,
        "left":  bool(has_left),
        "right": bool(has_right),
        "osm_id": int(node_row.get("osm_id") or 0),
        "nearest_tag_m": nearest_tag_m,
        "detect_radius": int(CROSSING_WAY_SEARCH_RADIUS_M),
        "way_osm_id": int(wrong_way_id or 0),
        "footway_value": wrong_value,
    }


def _empty_row() -> dict:
    return {"geometry": None, "name": "", "type": "", "left": False,
            "right": False, "osm_id": 0, "nearest_tag_m": -1.0,
            "detect_radius": int(CROSSING_WAY_SEARCH_RADIUS_M),
            "way_osm_id": 0, "footway_value": ""}


def _write_empty_output() -> None:
    gpd.GeoDataFrame(
        [_empty_row()],
        crs="EPSG:4326",
    ).to_file("missing_crossings.geojson", driver="GeoJSON")
