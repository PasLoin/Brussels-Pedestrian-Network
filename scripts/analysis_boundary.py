from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import Polygon


def parse_poly(text: str):
    outers: list[Polygon] = []
    holes: list[Polygon] = []
    ring: list[tuple[float, float]] | None = None
    is_hole = False
    for raw in text.splitlines()[1:]:
        line = raw.strip()
        if not line:
            continue
        if line == "END":
            if ring is not None and len(ring) >= 3:
                (holes if is_hole else outers).append(Polygon(ring).buffer(0))
            ring = None
            continue
        if ring is None:
            ring = []
            is_hole = line.startswith("!")
            continue
        x, y = line.split()[:2]
        ring.append((float(x), float(y)))
    if not outers:
        raise ValueError("no outer ring found in .poly file")
    area = shapely.union_all(outers)
    if holes:
        area = area.difference(shapely.union_all(holes))
    return area


def load_analysis_boundary(path: str | None, crs: str = "EPSG:31370"):
    if not path or not os.path.exists(path):
        print(f"  Analysis boundary not found ({path}), QA layers are not restricted")
        return None
    with open(path, encoding="utf-8") as fh:
        area = parse_poly(fh.read())
    area = gpd.GeoSeries([area], crs="EPSG:4326").to_crs(crs).iloc[0]
    shapely.prepare(area)
    print(f"  Analysis boundary: {path} ({area.area / 1e6:.1f} km²)")
    return area


def _geoms(geoms) -> np.ndarray:
    return np.asarray(getattr(geoms, "values", geoms), dtype=object)


def inside(geoms, area) -> np.ndarray:
    arr = _geoms(geoms)
    if area is None:
        return np.ones(len(arr), dtype=bool)
    return shapely.covers(area, arr).astype(bool)


def touches_area(geoms, area) -> np.ndarray:
    arr = _geoms(geoms)
    if area is None:
        return np.ones(len(arr), dtype=bool)
    return shapely.intersects(area, arr).astype(bool)


def clip_lines(gdf: gpd.GeoDataFrame, area) -> gpd.GeoDataFrame:
    if area is None:
        return gdf
    gdf = gdf[touches_area(gdf.geometry, area)].copy()
    if gdf.empty:
        return gdf
    clipped = shapely.intersection(_geoms(gdf.geometry), area)
    multi = shapely.get_type_id(clipped) == 5
    clipped[multi] = shapely.line_merge(clipped[multi])
    gdf = gdf.set_geometry(gpd.GeoSeries(clipped, index=gdf.index, crs=gdf.crs))
    gdf = gdf.explode(index_parts=False)
    return gdf[gdf.geometry.geom_type == "LineString"]
