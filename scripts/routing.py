"""
Steps 6–7 — Generate OD pairs and run shortest-path routing.

OD pair generation
------------------
Random pairs of snapped OD points are drawn, subject to distance
constraints:

* **Minimum distance** filters out trivially short trips (e.g. same
  block).
* **Maximum distance** avoids unrealistically long walking trips.

Both thresholds are straight-line (Euclidean in the projected CRS).

Routing
-------
Shortest paths are computed with **igraph** using Dijkstra's algorithm.
Pairs are grouped by source node so that a single shortest-path-tree
computation covers all destinations from the same origin — much faster
than running one Dijkstra per pair.

Two kinds of accumulation happen during routing:

1. **Flow accumulation** — every edge traversed increments a counter.
   This produces the "flow" layer shown on the map.
2. **Walkability accumulation** — only the first and last
   ``WALK_SCORE_RADIUS_M`` metres of each trip are measured, tracking
   how much of that distance is on pedestrian infrastructure vs. road.
   This feeds the per-street walkability score.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from typing import NamedTuple

import numpy as np

from config import (
    MAX_OD_DISTANCE_M,
    MAX_OD_PAIRS,
    MIN_OD_DISTANCE_M,
    PED_HIGHWAY_TYPES,
    WALK_SCORE_RADIUS_M,
)


class RoutingResult(NamedTuple):
    """All outputs produced by the routing step."""
    flow_arr: np.ndarray             # per-edge flow count
    street_ped_m: dict[str, float]   # ped metres per street (first/last km)
    street_cyc_nf_m: dict[str, float]  # cycleway-no-foot metres per street
    street_total_m: dict[str, float]   # total metres per street (first/last km)
    routed: int                      # number of successfully routed pairs
    total_routed_distance: float     # sum of all trip distances (metres)
    routing_time_s: float
    od_pairs_count: int
    rejected_near: int
    rejected_far: int


# ─────────────────────────────────────────────────────────────────────────────
# OD pair generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_od_pairs(
    od_points: list[tuple[float, float]],
    snapped: list[int],
    od_streets: list[str],
) -> tuple[list[tuple[int, int, str, str]], int, int]:
    """Generate random OD pairs with distance filtering.

    Returns
    -------
    od_pairs : list of (src_node, tgt_node, src_street, tgt_street)
    rejected_near : int
    rejected_far : int
    """
    print("Generating OD pairs...")
    random.seed(42)
    n_pts = len(od_points)
    od_xy = np.array(od_points)
    min_d2 = MIN_OD_DISTANCE_M ** 2
    max_d2 = MAX_OD_DISTANCE_M ** 2

    od_pairs: list[tuple[int, int, str, str]] = []
    seen: set[tuple[int, int]] = set()
    rejected_near = rejected_far = 0
    attempts = 0

    while len(od_pairs) < MAX_OD_PAIRS and attempts < MAX_OD_PAIRS * 20:
        i, j = random.randrange(n_pts), random.randrange(n_pts)
        attempts += 1
        if i == j:
            continue
        key = (min(i, j), max(i, j))
        if key in seen:
            continue
        dx = od_xy[i, 0] - od_xy[j, 0]
        dy = od_xy[i, 1] - od_xy[j, 1]
        d2 = dx * dx + dy * dy
        if d2 < min_d2:
            rejected_near += 1
            continue
        if d2 > max_d2:
            rejected_far += 1
            continue
        od_pairs.append((snapped[i], snapped[j], od_streets[i], od_streets[j]))
        seen.add(key)

    print(f"  OD pairs: {len(od_pairs)}")
    print(f"  Rejected — near: {rejected_near} | far: {rejected_far}")
    return od_pairs, rejected_near, rejected_far


# ─────────────────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────────────────

def _accumulate_capped(
    eids: list[int],
    cap_m: float,
    edge_lengths: list[float],
    edge_highways: list[str],
    cyc_nf_arr: np.ndarray,
) -> tuple[float, float, float]:
    """Walk along edges up to *cap_m* metres.

    Returns (ped_metres, cycleway_metres, total_metres).
    """
    ped = cyc = total = 0.0
    remaining = cap_m
    for eid in eids:
        if remaining <= 0:
            break
        full_len = edge_lengths[eid]
        used_len = min(full_len, remaining)
        total += used_len
        if cyc_nf_arr[eid]:
            cyc += used_len
        elif edge_highways[eid] in PED_HIGHWAY_TYPES or edge_highways[eid] == "cycleway":
            ped += used_len
        remaining -= full_len  # consume full edge even if capped
    return ped, cyc, total


def route_pairs(
    graph,
    od_pairs: list[tuple[int, int, str, str]],
    edge_lengths: list[float],
    edge_highways: list[str],
    edge_cycleway_nf: list[bool],
) -> RoutingResult:
    """Run Dijkstra routing for all OD pairs.

    Pairs are grouped by source to exploit igraph's multi-target
    shortest-path computation (one Dijkstra tree per source).
    """
    print("Routing pairs with igraph (grouped by source)...")
    t_route = time.time()

    flow_arr = np.zeros(graph.ecount(), dtype=np.int32)
    cyc_nf_arr = np.array(edge_cycleway_nf, dtype=bool)

    # Group pairs by source node
    pairs_by_src: dict[int, list[tuple[int, str, str]]] = defaultdict(list)
    for src, tgt, st_src, st_tgt in od_pairs:
        pairs_by_src[src].append((tgt, st_src, st_tgt))

    street_ped_m: dict[str, float] = defaultdict(float)
    street_cyc_nf_m: dict[str, float] = defaultdict(float)
    street_total_m: dict[str, float] = defaultdict(float)
    routed = 0
    total_routed_distance = 0.0
    n_sources = len(pairs_by_src)

    for done, (src, targets_info) in enumerate(pairs_by_src.items()):
        if done % 2000 == 0:
            elapsed = time.time() - t_route
            print(f"  Sources: {done}/{n_sources} | "
                  f"Pairs routed: {routed} | {elapsed:.0f}s")

        targets = [t for t, _, _ in targets_info]
        all_paths = graph.get_shortest_paths(
            src, to=targets, weights="weight", output="epath",
        )

        for (tgt, st_src, st_tgt), eids in zip(targets_info, all_paths):
            if not eids:
                continue
            routed += 1

            # Full trip: flow accumulation
            trip_dist = 0.0
            for eid in eids:
                flow_arr[eid] += 1
                trip_dist += edge_lengths[eid]
            total_routed_distance += trip_dist

            # Walkability: first WALK_SCORE_RADIUS_M for source street
            src_ped, src_cyc, src_total = _accumulate_capped(
                eids, WALK_SCORE_RADIUS_M,
                edge_lengths, edge_highways, cyc_nf_arr,
            )
            # … and last WALK_SCORE_RADIUS_M for target street
            tgt_ped, tgt_cyc, tgt_total = _accumulate_capped(
                list(reversed(eids)), WALK_SCORE_RADIUS_M,
                edge_lengths, edge_highways, cyc_nf_arr,
            )

            street_ped_m[st_src] += src_ped
            street_cyc_nf_m[st_src] += src_cyc
            street_total_m[st_src] += src_total

            street_ped_m[st_tgt] += tgt_ped
            street_cyc_nf_m[st_tgt] += tgt_cyc
            street_total_m[st_tgt] += tgt_total

    routing_time = time.time() - t_route
    avg_dist = total_routed_distance / routed if routed else 0
    print(f"  Routed {routed} pairs in {routing_time:.1f}s")
    print(f"  Average trip distance: {avg_dist:.0f}m")

    return RoutingResult(
        flow_arr=flow_arr,
        street_ped_m=dict(street_ped_m),
        street_cyc_nf_m=dict(street_cyc_nf_m),
        street_total_m=dict(street_total_m),
        routed=routed,
        total_routed_distance=total_routed_distance,
        routing_time_s=round(routing_time, 1),
        od_pairs_count=len(od_pairs),
        rejected_near=0,   # filled by caller
        rejected_far=0,
    )
