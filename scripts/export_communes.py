from __future__ import annotations

import json
import sys

import geopandas as gpd
import shapely

from analysis_boundary import load_analysis_boundary

METRIC_CRS = "EPSG:31370"
SIMPLIFY_M = 5.0
DECIMALS = 6


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()


def _round_coords(geom):
    return shapely.set_precision(geom, 10 ** -DECIMALS)


def municipalities(src_path: str, boundary_path: str | None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(src_path)
    if gdf.empty:
        return gdf
    for col in ("boundary", "admin_level", "name", "name:fr", "name:nl"):
        if col not in gdf.columns:
            gdf[col] = None
    keep = (gdf["boundary"].map(_text) == "administrative") & (gdf["admin_level"].map(_text) == "8")
    gdf = gdf[keep & gdf.geometry.notna()]
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if gdf.empty:
        return gdf
    gdf = gdf.set_crs("EPSG:4326", allow_override=True).to_crs(METRIC_CRS)
    area = load_analysis_boundary(boundary_path, crs=METRIC_CRS)
    if area is not None:
        points = shapely.point_on_surface(gdf.geometry.values)
        gdf = gdf[shapely.covers(area, points)]
    gdf = gdf.set_geometry(gdf.geometry.simplify(SIMPLIFY_M, preserve_topology=True))
    return gdf.to_crs("EPSG:4326")


def export_communes(src_path: str, boundary_path: str | None, out_path: str) -> int:
    gdf = municipalities(src_path, boundary_path)
    features = []
    for _, row in gdf.sort_values("name").iterrows() if not gdf.empty else []:
        geom = _round_coords(row.geometry)
        features.append({
            "type": "Feature",
            "properties": {
                "name": _text(row["name"]),
                "name_fr": _text(row["name:fr"]),
                "name_nl": _text(row["name:nl"]),
            },
            "geometry": shapely.geometry.mapping(geom),
        })
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"  Municipalities exported: {len(features)} -> {out_path}")
    return len(features)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: export_communes.py <admin_areas.geojson> <boundary.poly> <communes.geojson>")
    export_communes(sys.argv[1], sys.argv[2], sys.argv[3])
