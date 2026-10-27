from __future__ import annotations

import time
from collections import defaultdict
from typing import NamedTuple

import numpy as np
import shapely
from shapely import STRtree

from config import (
    MAX_OD_DISTANCE_M,
    MAX_OD_PAIRS,
    MIN_OD_DISTANCE_M,
)
from timing import record

_OD_RANDOM_SEED = 42
_OD_QUERY_CHUNK = 2000


class RoutingResult(NamedTuple):
    flow_arr: np.ndarray
    routed: int
    total_routed_distance: float
    routing_time_s: float
    od_pairs_count: int
    rejected_near: int
    rejected_far: int


def _enumerate_valid_pairs(
    od_xy: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    n = len(od_xy)
    min_d2 = MIN_OD_DISTANCE_M ** 2

    pts = shapely.points(od_xy)
    tree = STRtree(pts)

    kept_i: list[np.ndarray] = []
    kept_j: list[np.ndarray] = []
    n_within_max = 0
    n_near = 0

    for start in range(0, n, _OD_QUERY_CHUNK):
        chunk = pts[start:start + _OD_QUERY_CHUNK]
        qi, qj = tree.query(chunk, predicate="dwithin", distance=MAX_OD_DISTANCE_M)
        qi = qi + start
        mask = qi < qj
        qi, qj = qi[mask], qj[mask]
        n_within_max += len(qi)

        d = od_xy[qi] - od_xy[qj]
        d2 = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]
        keep = d2 >= min_d2
        n_near += int((~keep).sum())

        kept_i.append(qi[keep].astype(np.int32))
        kept_j.append(qj[keep].astype(np.int32))

    pair_i = np.concatenate(kept_i) if kept_i else np.empty(0, dtype=np.int32)
    pair_j = np.concatenate(kept_j) if kept_j else np.empty(0, dtype=np.int32)
    n_far = n * (n - 1) // 2 - n_within_max
    return pair_i, pair_j, n_near, n_far


def generate_od_pairs(
    od_points: list[tuple[float, float]],
    snapped: list[int],
) -> tuple[list[tuple[int, int]], int, int]:
    print("Generating OD pairs (exhaustive enumeration + random sample)...")
    n_pts = len(od_points)
    if n_pts < 2:
        print("  Not enough OD points.")
        return [], 0, 0

    od_xy = np.asarray(od_points, dtype=np.float64)
    pair_i, pair_j, rejected_near, rejected_far = _enumerate_valid_pairs(od_xy)

    snapped_arr = np.asarray(snapped, dtype=np.int64)
    same_node = snapped_arr[pair_i] == snapped_arr[pair_j]
    n_same_node = int(same_node.sum())
    pair_i, pair_j = pair_i[~same_node], pair_j[~same_node]
    n_valid = len(pair_i)

    rng = np.random.default_rng(_OD_RANDOM_SEED)
    if n_valid > MAX_OD_PAIRS:
        sel = rng.choice(n_valid, size=MAX_OD_PAIRS, replace=False)
        pair_i, pair_j = pair_i[sel], pair_j[sel]

    flip = rng.random(len(pair_i)) < 0.5
    src_idx = np.where(flip, pair_j, pair_i)
    tgt_idx = np.where(flip, pair_i, pair_j)

    od_pairs = [
        (int(snapped_arr[a]), int(snapped_arr[b]))
        for a, b in zip(src_idx.tolist(), tgt_idx.tolist())
    ]

    print(f"  Valid pairs available ({MIN_OD_DISTANCE_M:.0f}–{MAX_OD_DISTANCE_M:.0f} m): {n_valid}")
    print(f"  Excluded — same snapped node: {n_same_node}")
    print(f"  OD pairs sampled: {len(od_pairs)} (cap {MAX_OD_PAIRS})")
    print(f"  Out of range — near: {rejected_near} | far: {rejected_far}")
    return od_pairs, rejected_near, rejected_far


def route_pairs(
    graph,
    od_pairs: list[tuple[int, int]],
    edge_lengths: list[float],
) -> RoutingResult:
    print("Routing pairs with igraph (grouped by source)...")
    t_route = time.time()

    n_edges = graph.ecount()
    flow_arr = np.zeros(n_edges, dtype=np.int32)
    chunk_traversed_eids: list[int] = []

    pairs_by_src: dict[int, list[int]] = defaultdict(list)
    for src, tgt in od_pairs:
        pairs_by_src[src].append(tgt)

    routed = 0
    n_sources = len(pairs_by_src)

    t_dijkstra = 0.0
    t_accum = 0.0
    t_bincount = 0.0

    for done, (src, targets) in enumerate(pairs_by_src.items()):
        if done % 2000 == 0:
            elapsed = time.time() - t_route
            print(f"  Sources: {done}/{n_sources} | "
                  f"Pairs routed: {routed} | {elapsed:.0f}s")

        _td0 = time.time()
        all_paths = graph.get_shortest_paths(
            src, to=targets, weights="weight", output="epath",
        )
        t_dijkstra += time.time() - _td0

        _ta0 = time.time()
        for eids in all_paths:
            if not eids:
                continue
            routed += 1
            chunk_traversed_eids.extend(eids)
        t_accum += time.time() - _ta0

        if len(chunk_traversed_eids) > 1000000:
            _tb0 = time.time()
            flow_arr += np.bincount(chunk_traversed_eids, minlength=n_edges).astype(np.int32)
            t_bincount += time.time() - _tb0
            chunk_traversed_eids = []

    if chunk_traversed_eids:
        _tb0 = time.time()
        flow_arr += np.bincount(chunk_traversed_eids, minlength=n_edges).astype(np.int32)
        t_bincount += time.time() - _tb0

    edge_lengths_arr = np.array(edge_lengths, dtype=np.float64)
    total_routed_distance = float(np.dot(flow_arr, edge_lengths_arr))

    routing_time = time.time() - t_route

    record("dijkstra get_shortest_paths", t_dijkstra)
    record("flow accumulation", t_accum)
    record("np.bincount flushes", t_bincount)
    avg_dist = total_routed_distance / routed if routed else 0
    print(f"  Routed {routed} pairs in {routing_time:.1f}s")
    print(f"  Average trip distance: {avg_dist:.0f}m")

    return RoutingResult(
        flow_arr=flow_arr,
        routed=routed,
        total_routed_distance=total_routed_distance,
        routing_time_s=round(routing_time, 1),
        od_pairs_count=len(od_pairs),
        rejected_near=0,
        rejected_far=0,
    )
