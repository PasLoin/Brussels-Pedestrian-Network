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
import shapely
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point

from config import (
    FOOT_ALLOWED,
    LIT_PENALTY_MAX,
    MAX_OD_DISTANCE_M,
    MIN_FLOW_THRESHOLD,
    MIN_OD_DISTANCE_M,
    PED_HIGHWAY_TYPES,
    PED_INFRA_RADIUS_M,
    SURFACE_PENALTY_MAX,
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

def _attr_quality_penalty(surface_share: float, lit_share: float) -> float:
    """Multiplier < 1 when nearby pedestrian infra lacks surface/lit tags.

    Linear in the untagged share of each attribute; with the default
    config, fully untagged surroundings cost ×(1−0.15)×(1−0.10) ≈ 0.765.
    Fully documented surroundings cost nothing.
    """
    return (
        (1.0 - SURFACE_PENALTY_MAX * (1.0 - surface_share))
        * (1.0 - LIT_PENALTY_MAX * (1.0 - lit_share))
    )


class _PedInfraIndex:
    """Spatial index of the mapped pedestrian infrastructure.

    Deduplicates the bidirectional edge pairs (each physical way appears
    once) and answers, for a point: how many metres of pedestrian infra
    lie within PED_INFRA_RADIUS_M, and which share of that length
    carries a ``surface=*`` / ``lit=*`` tag.
    """

    def __init__(self, edge_tuples, edge_geoms, edge_highways,
                 edge_surfaces, edge_lits):
        geoms, surf, lit = [], [], []
        seen: set[tuple] = set()
        for i, hw in enumerate(edge_highways):
            if hw not in PED_HIGHWAY_TYPES:
                continue
            u, v = edge_tuples[i]
            geom = edge_geoms[i]
            key = (min(u, v), max(u, v), round(geom.length, 1))
            if key in seen:
                continue  # reverse direction of an already-seen edge
            seen.add(key)
            geoms.append(geom)
            surf.append(bool(edge_surfaces[i]))
            lit.append(bool(edge_lits[i]))
        self._geoms = np.array(geoms, dtype=object)
        self._surf = np.array(surf, dtype=bool)
        self._lit = np.array(lit, dtype=bool)
        self._tree = STRtree(geoms) if geoms else None

    def local_stats(self, x: float, y: float) -> tuple[float, float, float]:
        """→ (infra metres, surface-tagged share, lit-tagged share)."""
        if self._tree is None:
            return 0.0, 0.0, 0.0
        disc = Point(x, y).buffer(PED_INFRA_RADIUS_M)
        idx = self._tree.query(disc)
        if len(idx) == 0:
            return 0.0, 0.0, 0.0
        clipped = shapely.intersection(self._geoms[idx], disc)
        lengths = shapely.length(clipped)
        total = float(lengths.sum())
        if total <= 0:
            return 0.0, 0.0, 0.0
        surf_m = float(lengths[self._surf[idx]].sum())
        lit_m = float(lengths[self._lit[idx]].sum())
        return total, surf_m / total, lit_m / total


def export_walkability_scores(
    street_ped_m: dict[str, float],
    street_cyc_nf_m: dict[str, float],
    street_total_m: dict[str, float],
    street_sidewalk_status: dict,  # street → build_graph.SidewalkInfo
    addr_gdf: gpd.GeoDataFrame,
    edge_tuples: list,
    edge_geoms: list,
    edge_highways: list[str],
    edge_surfaces: list[str],
    edge_lits: list[str],
) -> dict:
    """Write street_scores.geojson: length-weighted sidewalk penalty ×
    surface/lit tag-completeness penalty on the routed base score."""
    print("Computing walkability scores (first/last km + sidewalk "
          "+ surface/lit penalties)...")

    addr_wgs = addr_gdf.to_crs("EPSG:4326")
    addr_wgs["_x"] = addr_wgs.geometry.x
    addr_wgs["_y"] = addr_wgs.geometry.y

    street_centroid_xy = (
        addr_wgs.groupby("addr:street")[["_x", "_y"]].mean()
    )
    centroids_x = street_centroid_xy["_x"].to_dict()
    centroids_y = street_centroid_xy["_y"].to_dict()

    # Projected centroids (metres) for the local-infra radius queries.
    addr_prj = addr_gdf.copy()
    addr_prj["_px"] = addr_prj.geometry.x
    addr_prj["_py"] = addr_prj.geometry.y
    street_centroid_prj = (
        addr_prj.groupby("addr:street")[["_px", "_py"]].mean()
    )
    centroids_px = street_centroid_prj["_px"].to_dict()
    centroids_py = street_centroid_prj["_py"].to_dict()

    with step(f"ped-infra index (radius {PED_INFRA_RADIUS_M:.0f} m)"):
        infra = _PedInfraIndex(
            edge_tuples, edge_geoms, edge_highways, edge_surfaces, edge_lits,
        )

    pen_stats: dict[str, int] = defaultdict(int)
    rows: list[dict] = []
    scores: list[float] = []

    for street, total_m in street_total_m.items():
        if total_m < 1.0:
            continue

        ped_m = street_ped_m.get(street, 0.0)
        cyc_m = street_cyc_nf_m.get(street, 0.0)
        base_score = ped_m / total_m

        info = street_sidewalk_status.get(street)
        if info is None:
            # No road edges under this name (fully pedestrian street,
            # footpaths, …): no sidewalk expected → no penalty.
            sw_status = "not_required"
            penalty = 1.0
            doc_pct = None
        else:
            # Length-weighted penalty: undocumented or bad segments drag
            # the score down proportionally to their length, so a single
            # tagged segment can no longer grant the whole street a
            # penalty-free "both".
            sw_status = info.status
            penalty = info.penalty
            doc_pct = int(round(info.doc_share * 100))

        if street not in centroids_x:
            continue
        centroid = Point(centroids_x[street], centroids_y[street])

        # ── Local mapped pedestrian infra + tag completeness ──────────
        infra_m, surface_share, lit_share = infra.local_stats(
            centroids_px[street], centroids_py[street],
        )
        attr_penalty = _attr_quality_penalty(surface_share, lit_share)

        score = round(min(base_score * penalty * attr_penalty, 1.0), 3)
        pen_stats[sw_status] += 1

        scores.append(score)

        rows.append({
            "geometry": centroid,
            "street": street,
            "walkability": score,
            "walkability_raw": round(base_score, 3),
            "sidewalk": sw_status,
            "sidewalk_doc_pct": -1 if doc_pct is None else doc_pct,
            # Mapped pedestrian infrastructure within PED_INFRA_RADIUS_M
            # of the street — a human-scale figure, unlike the
            # trip-accumulated ped_meters below.
            "ped_infra_m": round(infra_m, 0),
            "infra_radius": int(PED_INFRA_RADIUS_M),
            "surface_pct": int(round(surface_share * 100)),
            "lit_pct": int(round(lit_share * 100)),
            # Trip-accumulated meters (score internals, kept for debug).
            "ped_meters": round(ped_m, 0),
            "cycleway_meters": round(cyc_m, 0),
            "total_meters": round(total_m, 0),
        })

    fb = {
        "geometry": None, "street": "", "walkability": 0.0,
        "walkability_raw": 0.0, "sidewalk": "", "sidewalk_doc_pct": -1,
        "ped_infra_m": 0.0, "infra_radius": int(PED_INFRA_RADIUS_M),
        "surface_pct": 0, "lit_pct": 0,
        "ped_meters": 0.0, "cycleway_meters": 0.0, "total_meters": 0.0,
    }
    n_sc = _save_gdf(rows, fb, "EPSG:4326", "street_scores.geojson")
    print(f"  Street scores: {n_sc}")
    print(f"  Sidewalk penalties applied — both: {pen_stats['both']} | "
          f"partial: {pen_stats['partial']} | none: {pen_stats['none']} | "
          f"unknown: {pen_stats['unknown']} | not required: {pen_stats['not_required']}")

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
