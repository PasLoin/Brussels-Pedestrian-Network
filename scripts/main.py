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
    export_flow_layers,
    export_routing_graph,
    export_walkability_scores,
    save_stats,
)
from sidewalk_gap import detect_sidewalk_gaps
from export_sidewalk_roads import export_sidewalk_roads


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
    clean_osm("routing_raw.osm", "routing_clean.osm")

    # ── Step 2–3: Build graph ─────────────────────────────────────────────
    gb = build_graph("routing_clean.osm")

    # ── Step 4–5: Sample & snap OD points ─────────────────────────────────
    od_points, od_streets, od_sides = sample_od_points("addresses.geojson")
    snapped = snap_to_graph(
        od_points, gb.node_list, gb.nodes_gdf,
        gb.edge_tuples, gb.edge_geoms,
    )

    # ── Step 6–7: Generate OD pairs & route ───────────────────────────────
    od_pairs, rejected_near, rejected_far = generate_od_pairs(
        od_points, snapped, od_streets,
    )
    result = route_pairs(
        gb.graph, od_pairs,
        gb.edge_lengths, gb.edge_highways, gb.edge_cycleway_nf,
    )

    # ── Step 7b: Save stats ───────────────────────────────────────────────
    save_stats(
        routed=result.routed,
        total_routed_distance=result.total_routed_distance,
        n_od_points=len(od_points),
        n_od_pairs=len(od_pairs),
        rejected_near=rejected_near,
        rejected_far=rejected_far,
        routing_time_s=result.routing_time_s,
    )

    # ── Step 8: Export GeoJSON layers ─────────────────────────────────────
    export_flow_layers(
        result.flow_arr,
        gb.edge_highways, gb.edge_geoms,
        gb.edge_lengths, gb.edge_cycleway_nf,
        gb.edge_foot_tags,
        gb.graph.ecount(),
    )

    export_walkability_scores(
        result.street_ped_m, result.street_cyc_nf_m, result.street_total_m,
        gb.street_sidewalk_status,
    )

    # ── Step 8b: Detect sidewalk gaps ─────────────────────────────────────
    detect_sidewalk_gaps(
        gb.edge_tuples, gb.edge_highways,
        gb.edge_geoms, gb.edge_names,
        gb.edge_sidewalks, gb.edge_sidewalk_left, gb.edge_sidewalk_right,
        gb.edge_sidewalk_both,
    )

    # ── Step 8c: Export sidewalk tag status on roads ──────────────────────
    export_sidewalk_roads(
        gb.edge_tuples, gb.edge_highways,
        gb.edge_geoms, gb.edge_names,
        gb.edge_sidewalks, gb.edge_sidewalk_left, gb.edge_sidewalk_right,
        gb.edge_sidewalk_both,
    )

    # ── Step 9: Export client-side routing graph ──────────────────────────
    export_routing_graph(
        gb.node_list, gb.nodes_gdf,
        gb.edge_tuples, gb.edge_weights, gb.edge_lengths,
        gb.edge_highways, gb.edge_geoms, gb.edge_cycleway_nf,
        gb.edge_foot_tags,
    )

    print(f"Total time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
