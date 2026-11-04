#!/usr/bin/env python3
from __future__ import annotations

import time

from config import (
    MAX_OD_DISTANCE_M,
    MAX_SNAP_DISTANCE_M,
    MAX_OD_PAIRS,
    MIN_OD_DISTANCE_M,
    OD_SAMPLE_INTERVAL_M,
    POINTS_PER_SIDE,
    TOP_RANK_PCT,
)
from analysis_boundary import load_analysis_boundary
from clean_osm import clean_osm
from build_graph import build_graph
from sample_od import sample_od_points
from simulation import simulate_flows
from export import (
    compute_graph_stats,
    compute_network_stats,
    export_routing_graph,
    save_stats,
    undirected_edge_groups,
)
from detect_graph_islands import detect_graph_islands
from sidewalk_gap import detect_sidewalk_gaps
from export_sidewalk_roads import export_sidewalk_roads
from detect_missing_crossings import detect_missing_crossings
from detect_footway_connectivity import detect_footway_connectivity_candidates
from detect_tactile_paving_issues import detect_tactile_paving_issues
from timing import step, print_summary

ANALYSIS_BOUNDARY_PATH = "analysis_boundary.poly"


def main() -> None:
    t0 = time.time()

    print(f"Config: MIN_DIST={MIN_OD_DISTANCE_M}m "
          f"MAX_DIST={MAX_OD_DISTANCE_M}m "
          f"MAX_PAIRS={MAX_OD_PAIRS} "
          f"TOP_PCT={TOP_RANK_PCT} "
          f"OD_INTERVAL={OD_SAMPLE_INTERVAL_M}m "
          f"(legacy POINTS_PER_SIDE={POINTS_PER_SIDE})")

    with step("clean_osm"):
        clean_osm("routing_raw.osm", "routing_clean.osm")

    with step("build_graph"):
        gb = build_graph("routing_clean.osm")

    with step("undirected_edge_groups"):
        edge_groups = undirected_edge_groups(
            gb.edges.tuples, gb.edges.geoms, gb.edges.lengths,
        )
    print(f"  Physical segments: {len(edge_groups)} "
          f"(directed edges: {gb.graph.ecount()})")

    graph_stats = compute_graph_stats(gb, edge_groups)

    with step("load_analysis_boundary"):
        boundary = load_analysis_boundary(ANALYSIS_BOUNDARY_PATH)

    with step("detect_graph_islands"):
        main_mask, island_stats = detect_graph_islands(
            gb.graph, edge_groups,
            gb.edges.tuples, gb.edges.geoms, gb.edges.lengths,
            gb.edges.highways, gb.edges.osm_ids,
            edge_levels=gb.edges.levels,
            elevator_vertices=gb.elevator_vertices,
            node_list=gb.node_list,
            boundary=boundary,
        )
    graph_stats["components"] = island_stats

    network_stats = compute_network_stats(
        edge_groups,
        gb.edges.highways, gb.edges.lengths,
        gb.edges.cycleway_nf, gb.edges.foot_tags,
    )

    with step("sample_od_points"):
        od_points, od_streets, od_sides, _ = sample_od_points("addresses.geojson")

    sim = simulate_flows(
        gb, edge_groups, main_mask,
        od_points, od_streets, od_sides,
        max_snap_m=MAX_SNAP_DISTANCE_M,
    )

    with step("detect_sidewalk_gaps"):
        sidewalk_gap_stats = detect_sidewalk_gaps(
            "sidewalk_roads_raw.geojson",
            "sidewalk_footways_raw.geojson",
            "cycleways_raw.geojson",
            boundary=boundary,
        )

    with step("export_sidewalk_roads"):
        sidewalk_road_stats = export_sidewalk_roads("sidewalk_roads_raw.geojson")

    with step("detect_missing_crossings"):
        missing_crossing_stats = detect_missing_crossings(
            "highways.geojson",
            "sidewalk_footways_raw.geojson",
            "sidewalk_roads_raw.geojson",
            boundary=boundary,
        )

    with step("detect_footway_connectivity_candidates"):
        footway_connectivity_stats = detect_footway_connectivity_candidates(
            "sidewalk_footways_raw.geojson",
            "sidewalk_roads_raw.geojson",
        )

    with step("detect_tactile_paving_issues"):
        tactile_paving_stats = detect_tactile_paving_issues(
            "highways.geojson",
            "sidewalk_footways_raw.geojson",
            "kerbs_raw.geojson",
            ("sidewalk_roads_raw.geojson", "service_roads_raw.geojson"),
            boundary=boundary,
        )

    save_stats(
        routed=sim.routing.routed,
        total_routed_distance=sim.routing.total_routed_distance,
        n_od_points=len(sim.od_points),
        n_od_pairs=len(sim.od_pairs),
        rejected_near=sim.rejected_near,
        rejected_far=sim.rejected_far,
        routing_time_s=sim.routing.routing_time_s,
        graph_stats=graph_stats,
        flow_stats=sim.flow_stats,
        sidewalk_gap_stats=sidewalk_gap_stats,
        sidewalk_road_stats=sidewalk_road_stats,
        missing_crossing_stats=missing_crossing_stats,
        footway_connectivity_stats=footway_connectivity_stats,
        tactile_paving_stats=tactile_paving_stats,
        network_stats=network_stats,
        od_sampling_stats=sim.od_sampling_stats,
    )

    with step("export_routing_graph"):
        export_routing_graph(
            gb.node_list, gb.nodes_gdf,
            gb.edges.tuples, gb.edges.weights, gb.edges.lengths,
            gb.edges.highways, gb.edges.geoms, gb.edges.cycleway_nf,
            gb.edges.foot_tags, edge_levels=gb.edges.levels,
        )

    print(f"\nTotal time: {time.time() - t0:.1f}s")

    print_summary()


if __name__ == "__main__":
    main()
