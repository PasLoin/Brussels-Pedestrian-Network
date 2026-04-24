"""
Steps 8–9 — Export results to GeoJSON files and a client-side routing graph.

This module produces:

* **flow_edges.geojson** — every edge with its flow count and infra
  type (pedestrian / cycleway_foot_yes / cycleway_no_foot / road).
* **forced_segments.geojson** — high-flow edges on *road* surfaces,
  suggesting a missing pedestrian link.
* **forced_cycleway.geojson** — high-flow edges on cycleways without
  explicit pedestrian permission (``foot=yes`` edges are excluded).
* **street_scores.geojson** — per-street walkability score (0–1) with
  a sidewalk penalty applied.
* **stats.json** — summary statistics for the run.
* **graph.json** — compact routing graph for client-side Dijkstra
  navigation in the browser.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

import geopandas as gpd
import numpy as np
from pyproj import Transformer

from config import (
    FOOT_ALLOWED,
    MAX_OD_DISTANCE_M,
    MIN_OD_DISTANCE_M,
    PED_HIGHWAY_TYPES,
    SIDEWALK_PENALTY_NONE,
    SIDEWALK_PENALTY_PARTIAL,
    SIDEWALK_PENALTY_UNKNOWN,
    TOP_RANK_PCT,
    WALK_SCORE_RADIUS_M,
)


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
) -> None:
    """Write flow_edges, forced_segments, and forced_cycleway GeoJSONs.

    Infrastructure types (``infra_type`` property):

    * ``pedestrian`` — dedicated pedestrian infrastructure (footway, path…).
    * ``cycleway_foot_yes`` — cycleway with explicit ``foot=yes|designated|permissive``.
      These are walkable by definition, so they are **excluded** from forced_cycleway.
    * ``cycleway_no_foot`` — cycleway without explicit foot permission.
    * ``road`` — motor-vehicle road.
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
    fb = {
        "geometry": None, "highway": "", "flow": 0,
        "flow_pct": 0.0, "infra_type": "", "length_m": 0.0,
    }

    for eid in range(n_edges):
        flow = int(flow_arr[eid])
        if flow == 0 or edge_geoms[eid] is None:
            continue

        hw = edge_highways[eid]
        lm = float(edge_lengths[eid])
        cnf = bool(edge_cycleway_nf[eid])
        foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""
        foot_allowed = foot in FOOT_ALLOWED

        # ── Infrastructure classification ────────────────────────────────
        # Cycleways get their own category depending on foot permission.
        # This is defensive: even if cycleway_nf was wrongly set (e.g. OSMnx
        # lost the foot tag during simplification), we re-check here.
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

        row = {
            "geometry": edge_geoms[eid],
            "highway": hw,
            "flow": flow,
            "flow_pct": round(flow / max_flow * 100, 2),
            "infra_type": infra_type,
            "length_m": round(lm, 1),
        }
        rows_flow.append(row)

        # ── Forced classification ─────────────────────────────────────────
        # Only high-flow edges on truly non-pedestrian infra are flagged.
        # cycleway_foot_yes is explicitly excluded (issue #6).
        if flow >= threshold:
            if infra_type == "cycleway_no_foot":
                rows_forced_cycleway.append(row)
            elif not is_ped and infra_type != "cycleway_foot_yes":
                rows_forced_road.append(row)

    n_fr = _save_gdf(rows_forced_road, fb, "EPSG:31370", "forced_segments.geojson")
    n_fc = _save_gdf(rows_forced_cycleway, fb, "EPSG:31370", "forced_cycleway.geojson")
    n_fl = _save_gdf(rows_flow, fb, "EPSG:31370", "flow_edges.geojson")
    print(f"  Forced road: {n_fr} | Forced cycleway: {n_fc} | Flow edges: {n_fl}")


# ─────────────────────────────────────────────────────────────────────────────
# Walkability scores
# ─────────────────────────────────────────────────────────────────────────────

def export_walkability_scores(
    street_ped_m: dict[str, float],
    street_cyc_nf_m: dict[str, float],
    street_total_m: dict[str, float],
    street_sidewalk_status: dict[str, str],
    addresses_path: str = "addresses.geojson",
) -> None:
    """Write street_scores.geojson with sidewalk-penalised walkability."""
    print("Computing walkability scores (first/last km + sidewalk penalty)...")

    addr_wgs = gpd.read_file(addresses_path).to_crs("EPSG:4326")
    # Convert polygon geometries (building outlines) to centroids
    addr_wgs["geometry"] = addr_wgs.geometry.apply(
        lambda g: g.centroid if g.geom_type != "Point" else g
    )
    pen_stats: dict[str, int] = defaultdict(int)
    rows: list[dict] = []

    for street, total_m in street_total_m.items():
        if total_m < 1.0:
            continue

        ped_m = street_ped_m.get(street, 0.0)
        cyc_m = street_cyc_nf_m.get(street, 0.0)
        base_score = ped_m / total_m

        # Determine sidewalk penalty
        sw_status = street_sidewalk_status.get(street, "unknown")
        if sw_status == "both":
            penalty = 1.0
        elif sw_status == "partial":
            penalty = SIDEWALK_PENALTY_PARTIAL
        elif sw_status == "none":
            penalty = SIDEWALK_PENALTY_NONE
        elif street not in street_sidewalk_status:
            # Street has no road edges → probably all pedestrian infra
            penalty = 1.0
        else:
            penalty = SIDEWALK_PENALTY_UNKNOWN

        score = round(min(base_score * penalty, 1.0), 3)
        pen_stats[sw_status] += 1

        pts = addr_wgs[addr_wgs["addr:street"] == street].geometry
        if pts.empty:
            continue
        centroid = pts.union_all().centroid

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
) -> None:
    """Write stats.json with run summary."""
    avg_dist = total_routed_distance / routed if routed > 0 else 0
    stats = {
        "routed_trips": routed,
        "avg_distance_m": round(avg_dist, 1),
        "od_points": n_od_points,
        "od_pairs_generated": n_od_pairs,
        "rejected_near": rejected_near,
        "rejected_far": rejected_far,
        "routing_time_s": routing_time_s,
        "min_dist_m": MIN_OD_DISTANCE_M,
        "max_dist_m": MAX_OD_DISTANCE_M,
        "walk_score_radius_m": WALK_SCORE_RADIUS_M,
    }
    with open("stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print("  Stats saved to stats.json")


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
    """Export a compact JSON graph for client-side Dijkstra navigation.

    Format::

        {
          "hw": ["cycleway", "footway", …],   # highway type lookup
          "n": [[lat, lng], …],                # node coords (WGS84)
          "e": [[src, tgt, weight, len, hwIdx, infraType, [[lat,lng],…]], …]
        }

    ``infraType``: 0 = pedestrian, 1 = road, 2 = cycleway_no_foot,
    3 = cycleway_foot_yes.
    """
    print("Exporting routing graph for client-side navigation...")
    transformer = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)

    # Node coordinates in WGS84
    node_coords: list[list[float]] = []
    for nid in node_list:
        x = float(nodes_gdf.loc[nid, "x"])
        y = float(nodes_gdf.loc[nid, "y"])
        lng, lat = transformer.transform(x, y)
        node_coords.append([round(lat, 6), round(lng, 6)])

    # Highway type lookup table
    hw_strs = [
        h if isinstance(h, str) else "unclassified" for h in edge_highways
    ]
    hw_types = sorted(set(hw_strs))
    hw_to_idx = {h: i for i, h in enumerate(hw_types)}

    cyc_nf = np.array(edge_cycleway_nf, dtype=bool)

    edges: list = []
    for eid in range(len(edge_tuples)):
        src_i, tgt_i = edge_tuples[eid]
        w = round(edge_weights[eid], 1)
        lm = round(edge_lengths[eid], 1)
        hw = hw_strs[eid]
        hw_i = hw_to_idx.get(hw, 0)
        cnf = bool(cyc_nf[eid])
        foot = edge_foot_tags[eid] if eid < len(edge_foot_tags) else ""

        # Infra type: 0=ped, 1=road, 2=cycleway_no_foot, 3=cycleway_foot_yes
        if hw == "cycleway":
            sc = 2 if (cnf and foot not in FOOT_ALLOWED) else 3
        elif hw in PED_HIGHWAY_TYPES:
            sc = 0
        else:
            sc = 1

        geom = edge_geoms[eid]
        if geom is not None and not geom.is_empty:
            coords = [
                [round(glat, 6), round(glng, 6)]
                for gx, gy in geom.coords
                for glng, glat in [transformer.transform(gx, gy)]
            ]
        else:
            coords = [node_coords[src_i], node_coords[tgt_i]]

        edges.append([src_i, tgt_i, w, lm, hw_i, sc, coords])

    graph_data = {"hw": hw_types, "n": node_coords, "e": edges}
    with open("graph.json", "w") as f:
        json.dump(graph_data, f, separators=(",", ":"))

    sz_mb = os.path.getsize("graph.json") / (1024 * 1024)
    print(f"  Graph exported: {len(node_coords)} nodes, {len(edges)} edges")
    print(f"  graph.json size: {sz_mb:.1f} MB")
