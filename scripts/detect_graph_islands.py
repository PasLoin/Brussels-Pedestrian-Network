from __future__ import annotations

import json
import os
from collections import defaultdict

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import MultiLineString, shape

from config import ISLAND_PLATFORM_TOLERANCE_M, ISLAND_UNJOINED_GAP_M

_MAX_WAY_IDS = 50

_EMPTY_ROW = {
    "geometry": None,
    "island_id": 0,
    "type": "",
    "gap_m": -1.0,
    "length_m": 0.0,
    "n_segments": 0,
    "n_ways": 0,
    "highways": "",
    "way_ids": "",
    "bbox_w": 0.0,
    "bbox_s": 0.0,
    "bbox_e": 0.0,
    "bbox_n": 0.0,
}


def _write_output(rows: list[dict], path: str) -> None:
    if rows:
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        bounds = gdf.geometry.bounds
        gdf["bbox_w"] = bounds["minx"].round(6)
        gdf["bbox_s"] = bounds["miny"].round(6)
        gdf["bbox_e"] = bounds["maxx"].round(6)
        gdf["bbox_n"] = bounds["maxy"].round(6)
    else:
        gdf = gpd.GeoDataFrame([_EMPTY_ROW], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")


def _load_platforms(path: str) -> list:
    if not os.path.exists(path):
        print(f"  ⚠ {path} not found — platform exclusion disabled")
        return []
    with open(path) as f:
        data = json.load(f)
    features = data.get("features", [])
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:31370", always_xy=True)
    geoms = []
    for feat in features:
        geom_json = feat.get("geometry")
        if not geom_json:
            continue
        try:
            geom = shape(geom_json)
        except (ValueError, TypeError, AttributeError):
            continue
        if geom.is_empty:
            continue
        geoms.append(shapely.transform(
            geom, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1])),
        ))
    return geoms


def main_component_mask(graph) -> tuple[np.ndarray, np.ndarray, int]:
    comps = graph.connected_components(mode="weak")
    membership = np.asarray(comps.membership, dtype=np.int64)
    sizes = np.asarray(comps.sizes(), dtype=np.int64)
    main = int(np.argmax(sizes)) if len(sizes) else 0
    return membership == main, membership, main


def detect_graph_islands(
    graph,
    edge_groups: list[list[int]],
    edge_tuples: list[tuple[int, int]],
    edge_geoms: list,
    edge_lengths: list[float],
    edge_highways: list[str],
    edge_osm_ids: list[tuple[int, ...]],
    output_path: str = "graph_islands.geojson",
    platforms_path: str = "platforms_raw.geojson",
) -> tuple[np.ndarray, dict]:
    print("Detecting graph islands (components disconnected from the main network)...")

    main_mask, membership, main = main_component_mask(graph)
    n_vertices = len(membership)
    n_main_vertices = int(main_mask.sum())

    degree = np.zeros(n_vertices, dtype=np.int64)
    for u, v in edge_tuples:
        degree[u] += 1
        degree[v] += 1
    n_isolated_vertices = int((degree == 0).sum())

    main_geoms: list = []
    island_lines: dict[int, list] = defaultdict(list)
    island_length: dict[int, float] = defaultdict(float)
    island_highways: dict[int, set] = defaultdict(set)
    island_ways: dict[int, list] = defaultdict(list)

    for eids in edge_groups:
        eid = eids[0]
        geom = edge_geoms[eid]
        comp = int(membership[edge_tuples[eid][0]])
        if comp == main:
            if geom is not None and not geom.is_empty:
                main_geoms.append(geom)
            continue
        if geom is not None and not geom.is_empty:
            island_lines[comp].append(geom)
        island_length[comp] += float(edge_lengths[eid])
        island_highways[comp].add(edge_highways[eid])
        for way_id in edge_osm_ids[eid] if eid < len(edge_osm_ids) else ():
            if way_id not in island_ways[comp]:
                island_ways[comp].append(way_id)

    main_tree = STRtree(main_geoms) if main_geoms else None
    platform_geoms = _load_platforms(platforms_path)
    platform_tree = STRtree(platform_geoms) if platform_geoms else None
    n_platform_linked = 0
    platform_linked_length_m = 0.0

    comps_sorted = sorted(island_lines, key=lambda c: -island_length[c])
    rows: list[dict] = []
    n_unjoined = 0
    total_length_m = 0.0
    unjoined_length_m = 0.0

    island_id = 0
    for comp in comps_sorted:
        geom = MultiLineString(island_lines[comp])
        if platform_tree is not None and len(platform_tree.query(
            geom, predicate="dwithin", distance=ISLAND_PLATFORM_TOLERANCE_M,
        )):
            n_platform_linked += 1
            platform_linked_length_m += island_length[comp]
            continue
        island_id += 1
        gap_m = -1.0
        if main_tree is not None:
            _, dists = main_tree.query_nearest(geom, return_distance=True)
            if len(dists):
                gap_m = round(float(dists[0]), 1)

        is_unjoined = 0.0 <= gap_m <= ISLAND_UNJOINED_GAP_M
        length_m = island_length[comp]
        total_length_m += length_m
        if is_unjoined:
            n_unjoined += 1
            unjoined_length_m += length_m

        ways = island_ways[comp]
        rows.append({
            "geometry": geom,
            "island_id": island_id,
            "type": "unjoined" if is_unjoined else "isolated",
            "gap_m": gap_m,
            "length_m": round(length_m, 1),
            "n_segments": len(island_lines[comp]),
            "n_ways": len(ways),
            "highways": ", ".join(sorted(island_highways[comp])),
            "way_ids": ",".join(str(w) for w in ways[:_MAX_WAY_IDS]),
        })

    _write_output(rows, output_path)

    n_islands = len(rows)
    n_connected_vertices = n_vertices - n_isolated_vertices
    main_share_pct = (
        round(n_main_vertices / n_connected_vertices * 100, 2)
        if n_connected_vertices else 0
    )
    print(f"  Vertices: {n_vertices} | main network: {n_main_vertices} "
          f"({main_share_pct:.1f} % of vertices with edges) | "
          f"isolated vertices (no edge): {n_isolated_vertices}")
    print(f"  Linked to a public_transport=platform (not flagged): "
          f"{n_platform_linked} ({platform_linked_length_m / 1000:.1f} km), "
          f"platforms loaded: {len(platform_geoms)}")
    print(f"  Islands: {n_islands} ({total_length_m / 1000:.1f} km) | "
          f"unjoined (gap ≤ {ISLAND_UNJOINED_GAP_M} m): {n_unjoined} | "
          f"isolated: {n_islands - n_unjoined}")

    stats = {
        "main_component_vertices": n_main_vertices,
        "main_component_share_pct": main_share_pct,
        "isolated_vertices": n_isolated_vertices,
        "islands": n_islands,
        "islands_unjoined": n_unjoined,
        "islands_isolated": n_islands - n_unjoined,
        "islands_length_km": round(total_length_m / 1000, 2),
        "islands_unjoined_length_km": round(unjoined_length_m / 1000, 2),
        "unjoined_gap_m": ISLAND_UNJOINED_GAP_M,
        "platform_linked_components": n_platform_linked,
        "platform_linked_length_km": round(platform_linked_length_m / 1000, 2),
        "platform_tolerance_m": ISLAND_PLATFORM_TOLERANCE_M,
    }
    return main_mask, stats
