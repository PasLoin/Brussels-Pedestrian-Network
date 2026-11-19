from __future__ import annotations

import json
from collections import Counter

import geopandas as gpd
from pyproj import Transformer

from config import EDIT_CANDIDATE_HIGHWAYS, ROAD_TYPES_SIDEWALK_EXPECTED
from sidewalk_tags import CATEGORY_SEPARATE, stats_category

_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

_MIN_LENGTH = 15.0

EDIT_CANDIDATES_FILE = "edit_candidates.json"
_TO_WGS84 = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)


def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        import math
        if math.isnan(val):
            return ""
    return str(val).strip().lower()


def _safe_int(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _classify_edge_sidewalk(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> str:
    if sw_both:
        if sw_both == "separate":
            return "separate"
        if sw_both in ("yes", "both"):
            return "yes"
        return "documented"

    if sw_left and sw_right:
        if sw_left == "separate" and sw_right == "separate":
            return "separate"
        if sw_left == "separate" or sw_right == "separate":
            return "documented"
        return "documented"

    if sw:
        if sw == "separate":
            return "separate"
        if sw in ("both", "yes"):
            return "yes"
        if sw in ("left", "right"):
            return "partial"
        return "documented"

    if sw_left or sw_right:
        return "partial"

    return "unknown"


def write_edit_candidates(rows: list[dict], path: str = EDIT_CANDIDATES_FILE) -> int:
    ways = []
    for row in rows:
        if row["sw"] != "unknown" or row["highway"] not in EDIT_CANDIDATE_HIGHWAYS or row["osm_id"] <= 0:
            continue
        mid = row["geometry"].interpolate(0.5, normalized=True)
        lon, lat = _TO_WGS84.transform(mid.x, mid.y)
        ways.append([row["osm_id"], round(lon, 6), round(lat, 6)])
    ways.sort()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ways": ways}, f, separators=(",", ":"))
    return len(ways)


def export_sidewalk_roads(
    raw_geojson_path: str = "sidewalk_roads_raw.geojson",
) -> dict:
    print("Exporting sidewalk tag status on roads (QA layer)...")
    print(f"  Reading raw roads from: {raw_geojson_path}")

    gdf = gpd.read_file(raw_geojson_path)

    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy()

    gdf_proj = gdf.to_crs("EPSG:31370")

    gdf_proj = gdf_proj[gdf_proj["highway"].isin(_ROAD_TYPES)]

    print(f"  Road ways after filtering: {len(gdf_proj)}")

    rows: list[dict] = []
    length_by_status: dict[str, float] = {}
    n_separate_all_sides = 0
    separate_all_sides_m = 0.0
    street_documented: dict[str, bool] = {}

    for _, row in gdf_proj.iterrows():
        sw = _safe_str(row.get("sidewalk"))
        sw_l = _safe_str(row.get("sidewalk:left"))
        sw_r = _safe_str(row.get("sidewalk:right"))
        sw_b = _safe_str(row.get("sidewalk:both"))

        status = _classify_edge_sidewalk(sw, sw_l, sw_r, sw_b)

        road_length = row.geometry.length
        short = road_length < _MIN_LENGTH
        name = _safe_str(row.get("name")) or ""
        rows.append({
            "geometry": row.geometry,
            "sw": status,
            "name": name,
            "osm_id": _safe_int(row.get("@id")),
            "highway": _safe_str(row.get("highway")),
            "length_m": round(road_length, 1),
            "short": short,
        })
        if short:
            continue

        length_by_status[status] = length_by_status.get(status, 0.0) + road_length

        category = stats_category(sw, sw_l, sw_r, sw_b)
        if category == CATEGORY_SEPARATE:
            n_separate_all_sides += 1
            separate_all_sides_m += road_length

        if name:
            street_documented[name] = street_documented.get(name, False) or category is not None

    fb = {"geometry": None, "sw": "", "name": "", "osm_id": 0, "highway": "", "length_m": 0.0, "short": False}
    if rows:
        out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        out_gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    out_gdf.to_file("sidewalk_roads.geojson", driver="GeoJSON")

    counted = [r for r in rows if not r["short"]]
    print(f"  Road ways exported: {len(rows)} ({len(rows) - len(counted)} under {_MIN_LENGTH:g} m, left out of the stats)")
    print(f"  Edit candidates indexed: {write_edit_candidates(rows)}")

    counts = Counter(r["sw"] for r in counted)
    for st in ("separate", "yes", "documented", "partial", "unknown"):
        print(f"    {st}: {counts.get(st, 0)}")
    print(f"  All existing sidewalks mapped separately: {n_separate_all_sides}")
    print(f"  Named streets: {len(street_documented)} "
          f"(with ≥1 sidewalk tag: {sum(street_documented.values())})")

    total_ways = len(counted)

    return {
        "total_road_ways": total_ways,
        "by_status": {
            st: counts.get(st, 0) for st in ("separate", "yes", "documented", "partial", "unknown")
        },
        "pct_by_status": {
            st: round(counts.get(st, 0) / total_ways * 100, 1) if total_ways > 0 else 0
            for st in ("separate", "yes", "documented", "partial", "unknown")
        },
        "km_by_status": {
            st: round(length_by_status.get(st, 0) / 1000, 2)
            for st in ("separate", "yes", "documented", "partial", "unknown")
        },
        "separate_all_sides": {
            "count": n_separate_all_sides,
            "pct": round(n_separate_all_sides / total_ways * 100, 1) if total_ways > 0 else 0,
            "km": round(separate_all_sides_m / 1000, 2),
        },
        "streets_total": len(street_documented),
        "streets_with_sidewalk_tags": sum(street_documented.values()),
    }
