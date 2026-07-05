"""
Steps 8–9 — Export results to GeoJSON files and a client-side routing graph.

This module produces:

* **flow_edges.geojson** — every edge with its flow count and infra
  type (pedestrian / cycleway_foot_yes / cycleway_no_foot / road),
  plus ``highway`` tag for per-type styling in the frontend.
* **forced_segments.geojson** — high-flow edges on *road* surfaces,
  suggesting a missing pedestrian link.  Full properties kept for
  artifact/stats purposes but NOT included in PMTiles.
* **forced_cycleway.geojson** — high-flow edges on cycleways without
  explicit pedestrian permission.  Same artifact-only policy.
* **street_scores.geojson** — per-street walkability score (0–1) with
  a sidewalk penalty applied.
* **stats.json** — summary statistics for the run.
* **graph.json** — compact routing graph for client-side Dijkstra
  navigation in the browser.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point

from config import (
    FOOT_ALLOWED,
    MAX_OD_DISTANCE_M,
    MIN_FLOW_THRESHOLD,
    MIN_OD_DISTANCE_M,
    PED_HIGHWAY_TYPES,
    SIDEWALK_PENALTY_NONE,
    SIDEWALK_PENALTY_PARTIAL,
    SIDEWALK_PENALTY_UNKNOWN,
    TOP_RANK_PCT,
    WALK_SCORE_RADIUS_M,
)
from timing import step


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _save_gdf(rows, fallback, crs_in, filename) -> int:
    """Write a GeoDataFrame to GeoJSON, using *fallback* if rows is empty."""
    gdf = gpd.GeoDataFrame(
        rows if rows else [fallback], crs=crs_in,
    ).to_crs("EPSG:4326")
    gdf.to_file(filename, driver="GeoJSON")
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Flow edges + forced segments
# ─────────────────────────────────────────────────────────────────────────────

def export_flow_layers(
    flow_arr: np.ndarray,
    edge_highways: list[str],
    edge_geoms: list,
    edge_lengths: list[float],
    edge_cycleway_nf: list[bool],
    edge_foot_tags: list[str],
    n_edges: int,
) -> dict:
    """Write flow_edges, forced_segments, and forced_cycleway GeoJSONs.

    ``flow_edges`` now carries ``highway``, ``flow_pct``, and ``infra_type``
    so the frontend can apply per-highway-type line-width without separate
    forced layers in PMTiles.

    ``forced_segments`` and ``forced_cycleway`` are still written as full
    artifact outputs (with flow counts and length) but are no longer bundled
    into the PMTiles tile archive.

    Returns a dict of flow-layer statistics for stats.json.
    """
    print("Building flow GeoJSONs...")

    max_flow = int(flow_arr.max()) if flow_arr.max() > 0 else 1
    nonzero = flow_arr[flow_arr > 0]
    threshold = (
        float(np.percentile(nonzero, 100.0 - TOP_RANK_PCT))
        if len(nonzero) > 0 else 1.0
    )
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

    for eid in range(n_edges):
        flow = int(flow_arr[eid])
        if flow == 0 or edge_geoms[eid] is None:
            continue

        hw = edge_highways[eid]
        lm = float(edge_lengths[eid])
        cnf = bool(edge_cycleway_nf[eid])
        foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""
        foot_allowed = foot in FOOT_ALLOWED

        if hw == "cycleway":
            if foot_allowed or not cnf:
                infra_type = "cycleway_foot_yes"
            else:
                infra_type = "cycleway_no_foot"
            is_ped = False
        elif hw in PED_HIGHWAY_TYPES:
            infra_type = "pedestrian"
            is_ped = True
        else:
            infra_type = "road"
            is_ped = False

        flow_pct = round(flow / max_flow * 100, 2)

        flow_by_infra[infra_type] += flow
        edges_by_infra[infra_type] += 1
        length_by_infra[infra_type] += lm

        if flow >= threshold:
            forced_row = {
                "geometry": edge_geoms[eid],
                "highway": hw,
                "flow": flow,
                "flow_pct": flow_pct,
                "infra_type": infra_type,
                "length_m": round(lm, 1),
            }
            if infra_type == "cycleway_no_foot":
                rows_forced_cycleway.append(forced_row)
            elif not is_ped and infra_type != "cycleway_foot_yes":
                rows_forced_road.append(forced_row)

        if flow < MIN_FLOW_THRESHOLD:
            n_dropped_low_flow += 1
            continue

        rows_flow.append({
            "geometry": edge_geoms[eid],
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


# ─────────────────────────────────────────────────────────────────────────────
# Walkability scores
# ─────────────────────────────────────────────────────────────────────────────

def export_walkability_scores(
    street_ped_m: dict[str, float],
    street_cyc_nf_m: dict[str, float],
    street_total_m: dict[str, float],
    street_sidewalk_status: dict[str, str],
    addr_gdf: gpd.GeoDataFrame,
) -> dict:
    """Write street_scores.geojson with sidewalk-penalised walkability."""
    print("Computing walkability scores (first/last km + sidewalk penalty)...")

    addr_wgs = addr_gdf.to_crs("EPSG:4326")
    addr_wgs["_x"] = addr_wgs.geometry.x
    addr_wgs["_y"] = addr_wgs.geometry.y

    street_centroid_xy = (
        addr_wgs.groupby("addr:street")[["_x", "_y"]].mean()
    )
    centroids_x = street_centroid_xy["_x"].to_dict()
    centroids_y = street_centroid_xy["_y"].to_dict()

    pen_stats: dict[str, int] = defaultdict(int)
    rows: list[dict] = []
    scores: list[float] = []

    for street, total_m in street_total_m.items():
        if total_m < 1.0:
            continue

        ped_m = street_ped_m.get(street, 0.0)
        cyc_m = street_cyc_nf_m.get(street, 0.0)
        base_score = ped_m / total_m

        sw_status = street_sidewalk_status.get(street, "unknown")
        if sw_status == "both":
            penalty = 1.0
        elif sw_status == "partial":
            penalty = SIDEWALK_PENALTY_PARTIAL
        elif sw_status == "none":
            penalty = SIDEWALK_PENALTY_NONE
        elif street not in street_sidewalk_status:
            penalty = 1.0
        else:
            penalty = SIDEWALK_PENALTY_UNKNOWN

        score = round(min(base_score * penalty, 1.0), 3)
        pen_stats[sw_status] += 1

        if street not in centroids_x:
            continue
        centroid = Point(centroids_x[street], centroids_y[street])

        scores.append(score)

        rows.append({
            "geometry": centroid,
            "street": street,
            "walkability": score,
            "walkability_raw": round(base_score, 3),
            "sidewalk": sw_status,
            "ped_meters": round(ped_m, 0),
            "cycleway_meters": round(cyc_m, 0),
            "total_meters": round(total_m, 0),
        })

    fb = {
        "geometry": None, "street": "", "walkability": 0.0,
        "walkability_raw": 0.0, "sidewalk": "",
        "ped_meters": 0.0, "cycleway_meters": 0.0, "total_meters": 0.0,
    }
    n_sc = _save_gdf(rows, fb, "EPSG:4326", "street_scores.geojson")
    print(f"  Street scores: {n_sc}")
    print(f"  Sidewalk penalties applied — both: {pen_stats['both']} | "
          f"partial: {pen_stats['partial']} | none: {pen_stats['none']} | "
          f"unknown: {pen_stats['unknown']}")

    if scores:
        scores_arr = np.array(scores)
        hist, _ = np.histogram(scores_arr, bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0])
        score_buckets = {
            "0_20":   int(hist[0]),
            "20_40":  int(hist[1]),
            "40_60":  int(hist[2]),
            "60_80":  int(hist[3]),
            "80_100": int(hist[4]),
        }
    else:
        scores_arr = np.array([])
        score_buckets = {
            "0_20": 0, "20_40": 0, "40_60": 0, "60_80": 0, "80_100": 0,
        }

    return {
        "streets_scored": n_sc,
        "walkability_mean": round(float(scores_arr.mean()), 3) if len(scores_arr) > 0 else 0,
        "walkability_median": round(float(np.median(scores_arr)), 3) if len(scores_arr) > 0 else 0,
        "walkability_min": round(float(scores_arr.min()), 3) if len(scores_arr) > 0 else 0,
        "walkability_max": round(float(scores_arr.max()), 3) if len(scores_arr) > 0 else 0,
        "score_distribution": score_buckets,
        "sidewalk_penalties": dict(pen_stats),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────

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
    walkability_stats: dict | None = None,
    sidewalk_gap_stats: dict | None = None,
    sidewalk_road_stats: dict | None = None,
    missing_crossing_stats: dict | None = None,
    network_stats: dict | None = None,
    od_sampling_stats: dict | None = None,
) -> None:
    """Write stats.json with comprehensive run summary."""
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
            "walk_score_radius_m": WALK_SCORE_RADIUS_M,
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
    if walkability_stats:
        stats["walkability"] = walkability_stats
    if sidewalk_gap_stats:
        stats["sidewalk_gaps"] = sidewalk_gap_stats
    if sidewalk_road_stats:
        stats["sidewalk_roads"] = sidewalk_road_stats
    if missing_crossing_stats:
        stats["missing_crossings"] = missing_crossing_stats

    with open("stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print("  Stats saved to stats.json")


# ─────────────────────────────────────────────────────────────────────────────
# Network stats (base graph, before routing)
# ─────────────────────────────────────────────────────────────────────────────

def compute_network_stats(
    edge_highways: list[str],
    edge_lengths: list[float],
    edge_cycleway_nf: list[bool],
    edge_foot_tags: list[str],
) -> dict:
    """Compute base network statistics by highway type."""
    km_by_highway: dict[str, float] = defaultdict(float)
    km_by_category: dict[str, float] = defaultdict(float)
    count_by_highway: dict[str, int] = defaultdict(int)

    for eid in range(len(edge_highways)):
        hw = edge_highways[eid]
        lm = edge_lengths[eid]
        km_by_highway[hw] += lm / 1000
        count_by_highway[hw] += 1

        if hw == "cycleway":
            foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""
            if foot in FOOT_ALLOWED:
                km_by_category["cycleway_foot_yes"] += lm / 1000
            else:
                km_by_category["cycleway_no_foot"] += lm / 1000
        elif hw in PED_HIGHWAY_TYPES:
            km_by_category["pedestrian"] += lm / 1000
        else:
            km_by_category["road"] += lm / 1000

    total_km = sum(km_by_highway.values())

    return {
        "total_km": round(total_km, 2),
        "km_by_highway": {k: round(v, 2) for k, v in sorted(km_by_highway.items(), key=lambda x: -x[1])},
        "edges_by_highway": dict(sorted(count_by_highway.items(), key=lambda x: -x[1])),
        "km_by_category": {k: round(v, 2) for k, v in sorted(km_by_category.items(), key=lambda x: -x[1])},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Client-side routing graph
# ─────────────────────────────────────────────────────────────────────────────

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
    """Export a compact JSON graph for client-side Dijkstra navigation."""
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
