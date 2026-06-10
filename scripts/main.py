#!/usr/bin/env python3
"""
Brussels Pedestrian Network — routing pipeline.

Orchestrates the full pipeline:

1. **clean_osm** — Sanitise the OSM XML (split ways at blocked barriers,
   remove dangling references).
2. **build_graph** — Load the cleaned data into an OSMnx graph, project
   to Belgian Lambert 72, then convert to a weighted igraph.
3. **sample_od** — Sample origin-destination points from OSM address
   nodes and snap them to the nearest graph vertices.
4. **routing** — Generate random OD pairs with distance constraints and
   compute shortest paths.  Accumulate per-edge flow counts and
   per-street walkability metrics.
5. **export** — Write GeoJSON layers (flow, forced segments, walkability
   scores) and a compact JSON graph for client-side navigation.

All tunable parameters are read from environment variables — see
``config.py`` for the full list and their defaults.

Each major step is wrapped in :func:`timing.step` so the bottleneck is
visible in a single line at the end of the run.

Usage (from the repository root)::

    python3 scripts/main.py
"""

from __future__ import annotations

import time

from config import (
    MAX_OD_DISTANCE_M,
    MAX_OD_PAIRS,
    MIN_OD_DISTANCE_M,
    OD_SAMPLE_INTERVAL_M,
    POINTS_PER_SIDE,
    SIDEWALK_PENALTY_NONE,
    SIDEWALK_PENALTY_PARTIAL,
    SIDEWALK_PENALTY_UNKNOWN,
    TOP_RANK_PCT,
    WALK_SCORE_RADIUS_M,
)
from clean_osm import clean_osm
from build_graph import build_graph
from sample_od import sample_od_points, snap_to_graph
from routing import generate_od_pairs, route_pairs
from export import (
    compute_network_stats,
    export_flow_layers,
    export_routing_graph,
    export_walkability_scores,
    save_stats,
)
from sidewalk_gap import detect_sidewalk_gaps
from export_sidewalk_roads import export_sidewalk_roads
from timing import step, print_summary


def main() -> None:
    t0 = time.time()

    # Log active configuration
    print(f"Config: MIN_DIST={MIN_OD_DISTANCE_M}m "
          f"MAX_DIST={MAX_OD_DISTANCE_M}m "
          f"MAX_PAIRS={MAX_OD_PAIRS} "
          f"TOP_PCT={TOP_RANK_PCT} "
          f"OD_INTERVAL={OD_SAMPLE_INTERVAL_M}m "
          f"(legacy POINTS_PER_SIDE={POINTS_PER_SIDE})")
    print(f"Walkability: radius={WALK_SCORE_RADIUS_M}m "
          f"penalties: none={SIDEWALK_PENALTY_NONE} "
          f"partial={SIDEWALK_PENALTY_PARTIAL} "
          f"unknown={SIDEWALK_PENALTY_UNKNOWN}")

    # ── Step 1: Clean OSM XML ─────────────────────────────────────────────
    with step("clean_osm"):
        clean_osm("routing_raw.osm", "routing_clean.osm")

    # ── Step 2–3: Build graph ─────────────────────────────────────────────
    with step("build_graph"):
        gb = build_graph("routing_clean.osm")

    # Collect graph-level stats (fast, no timer)
    graph_stats = {
        "nodes": gb.graph.vcount(),
        "edges": gb.graph.ecount(),
        "cycleways_foot_yes": sum(
            1 for h, c in zip(gb.edge_highways, gb.edge_cycleway_nf)
            if h == "cycleway" and not c
        ),
        "cycleways_no_foot": sum(
            1 for h, c in zip(gb.edge_highways, gb.edge_cycleway_nf)
            if h == "cycleway" and c
        ),
        "streets_with_sidewalk_tags": len(gb.street_sidewalk_status),
    }

    # Compute base network stats (fast, no timer)
    network_stats = compute_network_stats(
        gb.edge_highways, gb.edge_lengths,
        gb.edge_cycleway_nf, gb.edge_foot_tags,
    )

    # ── Step 4: Sample OD points ──────────────────────────────────────────
    with step("sample_od_points"):
        od_points, od_streets, od_sides = sample_od_points("addresses.geojson")

    # ── Step 5: Snap OD points to graph ───────────────────────────────────
    with step("snap_to_graph"):
        snapped = snap_to_graph(
            od_points, gb.node_list, gb.nodes_gdf,
            gb.edge_tuples, gb.edge_geoms,
        )

    # Collect OD sampling stats
    n_streets_both = len(set(
        s for s, side in zip(od_streets, od_sides)
    ))
    od_sampling_stats = {
        "streets_sampled": n_streets_both,
        "points_even": sum(1 for s in od_sides if s == "even"),
        "points_odd": sum(1 for s in od_sides if s == "odd"),
    }

    # ── Step 6: Generate OD pairs ─────────────────────────────────────────
    with step("generate_od_pairs"):
        od_pairs, rejected_near, rejected_far = generate_od_pairs(
            od_points, snapped, od_streets,
        )

    # ── Step 7: Route ─────────────────────────────────────────────────────
    with step("route_pairs"):
        result = route_pairs(
            gb.graph, od_pairs,
            gb.edge_lengths, gb.edge_highways, gb.edge_cycleway_nf,
        )

    # ── Step 8a: Export flow layers ───────────────────────────────────────
    with step("export_flow_layers"):
        flow_stats = export_flow_layers(
            result.flow_arr,
            gb.edge_highways, gb.edge_geoms,
            gb.edge_lengths, gb.edge_cycleway_nf,
            gb.edge_foot_tags,
            gb.graph.ecount(),
        )

    # ── Step 8b: Walkability scores ───────────────────────────────────────
    with step("export_walkability_scores"):
        walkability_stats = export_walkability_scores(
            result.street_ped_m, result.street_cyc_nf_m, result.street_total_m,
            gb.street_sidewalk_status,
        )

    # ── Step 8c: Sidewalk gap detection ───────────────────────────────────
    with step("detect_sidewalk_gaps"):
        sidewalk_gap_stats = detect_sidewalk_gaps(
            "sidewalk_roads_raw.geojson",
            "sidewalk_footways_raw.geojson",
        )

    # ── Step 8d: Sidewalk tag status on roads ─────────────────────────────
    with step("export_sidewalk_roads"):
        sidewalk_road_stats = export_sidewalk_roads("sidewalk_roads_raw.geojson")

    # ── Save stats (fast, no timer) ───────────────────────────────────────
    save_stats(
        routed=result.routed,
        total_routed_distance=result.total_routed_distance,
        n_od_points=len(od_points),
        n_od_pairs=len(od_pairs),
        rejected_near=rejected_near,
        rejected_far=rejected_far,
        routing_time_s=result.routing_time_s,
        graph_stats=graph_stats,
        flow_stats=flow_stats,
        walkability_stats=walkability_stats,
        sidewalk_gap_stats=sidewalk_gap_stats,
        sidewalk_road_stats=sidewalk_road_stats,
        network_stats=network_stats,
        od_sampling_stats=od_sampling_stats,
    )

    # ── Step 9: Client-side routing graph ─────────────────────────────────
    with step("export_routing_graph"):
        export_routing_graph(
            gb.node_list, gb.nodes_gdf,
            gb.edge_tuples, gb.edge_weights, gb.edge_lengths,
            gb.edge_highways, gb.edge_geoms, gb.edge_cycleway_nf,
            gb.edge_foot_tags,
        )

    print(f"\nTotal time: {time.time() - t0:.1f}s")

    # ── Final breakdown ───────────────────────────────────────────────────
    print_summary()


if __name__ == "__main__":
    main()
