from __future__ import annotations

from collections import Counter

import geopandas as gpd

from config import ROAD_TYPES_SIDEWALK_EXPECTED

_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

_MIN_LENGTH = 15.0


def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        import math
        if math.isnan(val):
            return ""
    return str(val).strip().lower()


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


def export_sidewalk_roads(
    raw_geojson_path: str = "sidewalk_roads_raw.geojson",
) -> dict:
    print("Exporting sidewalk tag status on roads (QA layer)...")
    print(f"  Reading raw roads from: {raw_geojson_path}")

    gdf = gpd.read_file(raw_geojson_path)

    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy()

    gdf_proj = gdf.to_crs("EPSG:31370")

    gdf_proj = gdf_proj[gdf_proj["highway"].isin(_ROAD_TYPES)]
    gdf_proj = gdf_proj[gdf_proj.geometry.length >= _MIN_LENGTH]

    print(f"  Road ways after filtering: {len(gdf_proj)}")

    rows: list[dict] = []
    length_by_status: dict[str, float] = {}

    for _, row in gdf_proj.iterrows():
        sw = _safe_str(row.get("sidewalk"))
        sw_l = _safe_str(row.get("sidewalk:left"))
        sw_r = _safe_str(row.get("sidewalk:right"))
        sw_b = _safe_str(row.get("sidewalk:both"))

        status = _classify_edge_sidewalk(sw, sw_l, sw_r, sw_b)

        road_length = row.geometry.length
        length_by_status[status] = length_by_status.get(status, 0.0) + road_length

        rows.append({
            "geometry": row.geometry,
            "sw": status,
            "name": _safe_str(row.get("name")) or "",
        })

    fb = {"geometry": None, "sw": "", "name": ""}
    if rows:
        out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        out_gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    out_gdf.to_file("sidewalk_roads.geojson", driver="GeoJSON")

    print(f"  Road ways exported: {len(rows)}")

    counts = Counter(r["sw"] for r in rows)
    for st in ("separate", "yes", "documented", "partial", "unknown"):
        print(f"    {st}: {counts.get(st, 0)}")

    total_ways = len(rows)

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
    }
