from __future__ import annotations

import json
import os
from collections import defaultdict

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer

from config import (
    FOOT_ALLOWED,
    MAX_OD_DISTANCE_M,
    MIN_FLOW_THRESHOLD,
    MIN_OD_DISTANCE_M,
    PED_HIGHWAY_TYPES,
    TOP_RANK_PCT,
)
from timing import step


def _save_gdf(rows, fallback, crs_in, filename) -> int:
    gdf = gpd.GeoDataFrame(
        rows if rows else [fallback], crs=crs_in,
    ).to_crs("EPSG:4326")
    gdf.to_file(filename, driver="GeoJSON")
    return len(rows)


def undirected_edge_groups(
    edge_tuples: list[tuple[int, int]],
    edge_geoms: list,
    edge_lengths: list[float],
) -> list[list[int]]:
    n = len(edge_tuples)
    valid = np.zeros(n, dtype=bool)
    geoms = np.empty(n, dtype=object)
    for eid, geom in enumerate(edge_geoms):
        if geom is not None and not geom.is_empty:
            valid[eid] = True
            geoms[eid] = geom

    mid_x = np.full(n, np.nan)
    mid_y = np.full(n, np.nan)
    if valid.any():
        mids = shapely.line_interpolate_point(
            geoms[valid], 0.5, normalized=True,
        )
        mid_x[valid] = shapely.get_x(mids)
        mid_y[valid] = shapely.get_y(mids)

    groups: dict[tuple, list[int]] = {}
    for eid, (u, v) in enumerate(edge_tuples):
        if valid[eid]:
            key = (
                min(u, v), max(u, v),
                round(float(edge_lengths[eid]), 1),
                round(float(mid_x[eid]), 1),
                round(float(mid_y[eid]), 1),
            )
        else:
            key = (
                min(u, v), max(u, v),
                round(float(edge_lengths[eid]), 1),
                None, None,
            )
        groups.setdefault(key, []).append(eid)
    return list(groups.values())


def _infra_type(hw: str, cycleway_nf: bool, foot: str) -> str:
    if hw == "cycleway":
        if foot in FOOT_ALLOWED or not cycleway_nf:
            return "cycleway_foot_yes"
        return "cycleway_no_foot"
    if hw in PED_HIGHWAY_TYPES:
        return "pedestrian"
    return "road"


def export_flow_layers(
    flow_arr: np.ndarray,
    edge_groups: list[list[int]],
    edge_highways: list[str],
    edge_geoms: list,
    edge_lengths: list[float],
    edge_cycleway_nf: list[bool],
    edge_foot_tags: list[str],
) -> dict:
    print("Building flow GeoJSONs (directions merged)...")

    group_flows = np.array(
        [int(flow_arr[eids].sum()) for eids in edge_groups], dtype=np.int64,
    )
    max_flow = int(group_flows.max()) if len(group_flows) and group_flows.max() > 0 else 1
    nonzero = group_flows[group_flows > 0]
    threshold = (
        float(np.percentile(nonzero, 100.0 - TOP_RANK_PCT))
        if len(nonzero) > 0 else 1.0
    )
    print(f"  Physical segments: {len(edge_groups)} "
          f"(directed edges: {len(flow_arr)})")
    print(f"  Flow threshold (top {TOP_RANK_PCT}%): {threshold:.0f} trips")

    rows_flow = []
    rows_forced_road = []
    rows_forced_cycleway = []

    fb_flow = {
        "geometry": None, "flow_pct": 0.0, "infra_type": "", "highway": "",
    }
    fb_forced = {
        "geometry": None, "highway": "", "flow": 0,
        "flow_pct": 0.0, "infra_type": "", "length_m": 0.0,
    }
    n_dropped_low_flow = 0

    flow_by_infra: dict[str, int] = defaultdict(int)
    edges_by_infra: dict[str, int] = defaultdict(int)
    length_by_infra: dict[str, float] = defaultdict(float)

    for gi, eids in enumerate(edge_groups):
        flow = int(group_flows[gi])
        if flow == 0:
            continue
        eid = eids[0]
        geom = edge_geoms[eid]
        if geom is None:
            continue

        hw = edge_highways[eid]
        lm = float(edge_lengths[eid])
        foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""
        infra_type = _infra_type(hw, bool(edge_cycleway_nf[eid]), foot)

        flow_pct = round(flow / max_flow * 100, 2)

        flow_by_infra[infra_type] += flow
        edges_by_infra[infra_type] += 1
        length_by_infra[infra_type] += lm

        if flow >= threshold:
            forced_row = {
                "geometry": geom,
                "highway": hw,
                "flow": flow,
                "flow_pct": flow_pct,
                "infra_type": infra_type,
                "length_m": round(lm, 1),
            }
            if infra_type == "cycleway_no_foot":
                rows_forced_cycleway.append(forced_row)
            elif infra_type == "road":
                rows_forced_road.append(forced_row)

        if flow < MIN_FLOW_THRESHOLD:
            n_dropped_low_flow += 1
            continue

        rows_flow.append({
            "geometry": geom,
            "flow_pct": flow_pct,
            "infra_type": infra_type,
            "highway": hw,
        })

    n_fr = _save_gdf(rows_forced_road, fb_forced, "EPSG:31370", "forced_segments.geojson")
    n_fc = _save_gdf(rows_forced_cycleway, fb_forced, "EPSG:31370", "forced_cycleway.geojson")
    n_fl = _save_gdf(rows_flow, fb_flow, "EPSG:31370", "flow_edges.geojson")
    print(f"  Forced road: {n_fr} | Forced cycleway: {n_fc} | Flow edges: {n_fl}")
    print(f"  Dropped (flow < {MIN_FLOW_THRESHOLD}): {n_dropped_low_flow}")

    forced_road_length_m = sum(r["length_m"] for r in rows_forced_road)
    forced_cycleway_length_m = sum(r["length_m"] for r in rows_forced_cycleway)

    return {
        "forced_road_segments": n_fr,
        "forced_cycleway_segments": n_fc,
        "flow_edges_exported": n_fl,
        "flow_edges_dropped_low": n_dropped_low_flow,
        "flow_threshold_trips": round(threshold, 0),
        "max_flow_trips": max_flow,
        "forced_road_length_m": round(forced_road_length_m, 0),
        "forced_cycleway_length_m": round(forced_cycleway_length_m, 0),
        "flow_by_infra": dict(flow_by_infra),
        "edges_with_flow_by_infra": dict(edges_by_infra),
        "length_with_flow_by_infra_m": {
            k: round(v, 0) for k, v in length_by_infra.items()
        },
    }


def save_stats(
    routed: int,
    total_routed_distance: float,
    n_od_points: int,
    n_od_pairs: int,
    rejected_near: int,
    rejected_far: int,
    routing_time_s: float,
    *,
    graph_stats: dict | None = None,
    flow_stats: dict | None = None,
    sidewalk_gap_stats: dict | None = None,
    sidewalk_road_stats: dict | None = None,
    missing_crossing_stats: dict | None = None,
    footway_connectivity_stats: dict | None = None,
    tactile_paving_stats: dict | None = None,
    network_stats: dict | None = None,
    od_sampling_stats: dict | None = None,
) -> None:
    avg_dist = total_routed_distance / routed if routed > 0 else 0
    stats: dict = {
        "routing": {
            "routed_trips": routed,
            "avg_distance_m": round(avg_dist, 1),
            "total_distance_km": round(total_routed_distance / 1000, 1),
            "routing_time_s": routing_time_s,
        },
        "od_sampling": {
            "od_points": n_od_points,
            "od_pairs_generated": n_od_pairs,
            "rejected_near": rejected_near,
            "rejected_far": rejected_far,
            "min_dist_m": MIN_OD_DISTANCE_M,
            "max_dist_m": MAX_OD_DISTANCE_M,
        },
        "routed_trips": routed,
        "avg_distance_m": round(avg_dist, 1),
    }

    if od_sampling_stats:
        stats["od_sampling"].update(od_sampling_stats)
    if graph_stats:
        stats["graph"] = graph_stats
    if network_stats:
        stats["network"] = network_stats
    if flow_stats:
        stats["flow"] = flow_stats
    if sidewalk_gap_stats:
        stats["sidewalk_gaps"] = sidewalk_gap_stats
    if sidewalk_road_stats:
        stats["sidewalk_roads"] = sidewalk_road_stats
    if missing_crossing_stats:
        stats["missing_crossings"] = missing_crossing_stats
    if footway_connectivity_stats:
        stats["footway_connectivity_candidates"] = footway_connectivity_stats
    if tactile_paving_stats:
        stats["tactile_paving_issues"] = tactile_paving_stats

    with open("stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print("  Stats saved to stats.json")


def compute_network_stats(
    edge_groups: list[list[int]],
    edge_highways: list[str],
    edge_lengths: list[float],
    edge_cycleway_nf: list[bool],
    edge_foot_tags: list[str],
) -> dict:
    km_by_highway: dict[str, float] = defaultdict(float)
    km_by_category: dict[str, float] = defaultdict(float)
    count_by_highway: dict[str, int] = defaultdict(int)

    for eids in edge_groups:
        eid = eids[0]
        hw = edge_highways[eid]
        km = edge_lengths[eid] / 1000
        km_by_highway[hw] += km
        count_by_highway[hw] += 1
        foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""
        km_by_category[_infra_type(hw, bool(edge_cycleway_nf[eid]), foot)] += km

    total_km = sum(km_by_highway.values())

    return {
        "total_km": round(total_km, 2),
        "km_by_highway": {k: round(v, 2) for k, v in sorted(km_by_highway.items(), key=lambda x: -x[1])},
        "edges_by_highway": dict(sorted(count_by_highway.items(), key=lambda x: -x[1])),
        "km_by_category": {k: round(v, 2) for k, v in sorted(km_by_category.items(), key=lambda x: -x[1])},
    }


def export_routing_graph(
    node_list: list,
    nodes_gdf: gpd.GeoDataFrame,
    edge_tuples: list[tuple[int, int]],
    edge_weights: list[float],
    edge_lengths: list[float],
    edge_highways: list[str],
    edge_geoms: list,
    edge_cycleway_nf: list[bool],
    edge_foot_tags: list[str],
) -> None:
    print("Exporting routing graph for client-side navigation...")
    transformer = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)

    with step("node coords transform"):
        node_xs = nodes_gdf.loc[node_list, "x"].to_numpy(dtype=np.float64)
        node_ys = nodes_gdf.loc[node_list, "y"].to_numpy(dtype=np.float64)
        node_lngs, node_lats = transformer.transform(node_xs, node_ys)
        node_lats = np.round(node_lats, 6)
        node_lngs = np.round(node_lngs, 6)
        node_coords: list[list[float]] = [
            [float(lat), float(lng)] for lat, lng in zip(node_lats, node_lngs)
        ]

    hw_strs = [
        h if isinstance(h, str) else "unclassified" for h in edge_highways
    ]
    hw_types = sorted(set(hw_strs))
    hw_to_idx = {h: i for i, h in enumerate(hw_types)}

    cyc_nf = np.array(edge_cycleway_nf, dtype=bool)

    with step("edge vertices flatten"):
        all_xs: list[float] = []
        all_ys: list[float] = []
        edge_slices: list[tuple[int, int] | None] = []
        for geom in edge_geoms:
            if geom is not None and not geom.is_empty:
                start = len(all_xs)
                for gx, gy in geom.coords:
                    all_xs.append(gx)
                    all_ys.append(gy)
                edge_slices.append((start, len(all_xs)))
            else:
                edge_slices.append(None)

    with step("edge vertices transform"):
        if all_xs:
            all_xs_arr = np.asarray(all_xs, dtype=np.float64)
            all_ys_arr = np.asarray(all_ys, dtype=np.float64)
            all_lngs, all_lats = transformer.transform(all_xs_arr, all_ys_arr)
            all_lats = np.round(all_lats, 6)
            all_lngs = np.round(all_lngs, 6)
        else:
            all_lats = np.array([])
            all_lngs = np.array([])

    with step("edge dict build loop"):
        edges: list = []
        for eid in range(len(edge_tuples)):
            src_i, tgt_i = edge_tuples[eid]
            w = round(edge_weights[eid], 1)
            lm = round(edge_lengths[eid], 1)
            hw = hw_strs[eid]
            hw_i = hw_to_idx.get(hw, 0)
            cnf = bool(cyc_nf[eid])
            foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""

            if hw == "cycleway":
                sc = 2 if (cnf and foot not in FOOT_ALLOWED) else 3
            elif hw in PED_HIGHWAY_TYPES:
                sc = 0
            else:
                sc = 1

            slc = edge_slices[eid]
            if slc is not None:
                start, end = slc
                coords = [
                    [float(all_lats[i]), float(all_lngs[i])]
                    for i in range(start, end)
                ]
            else:
                coords = [node_coords[src_i], node_coords[tgt_i]]

            edges.append([src_i, tgt_i, w, lm, hw_i, sc, coords])

    with step("json.dump graph.json"):
        graph_data = {"hw": hw_types, "n": node_coords, "e": edges}
        with open("graph.json", "w") as f:
            json.dump(graph_data, f, separators=(",", ":"))

    sz_mb = os.path.getsize("graph.json") / (1024 * 1024)
    print(f"  Graph exported: {len(node_coords)} nodes, {len(edges)} edges")
    print(f"  graph.json size: {sz_mb:.1f} MB")
