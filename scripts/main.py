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
    undirected_edge_groups,
)
from detect_graph_islands import detect_graph_islands
from sidewalk_gap import detect_sidewalk_gaps
from export_sidewalk_roads import export_sidewalk_roads
from detect_missing_crossings import detect_missing_crossings
from detect_footway_connectivity import detect_footway_connectivity_candidates
from detect_tactile_paving_issues import detect_tactile_paving_issues
from timing import step, print_summary


def main() -> None:
    t0 = time.time()

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

    with step("clean_osm"):
        clean_osm("routing_raw.osm", "routing_clean.osm")

    with step("build_graph"):
        gb = build_graph("routing_clean.osm")

    with step("undirected_edge_groups"):
        edge_groups = undirected_edge_groups(
            gb.edge_tuples, gb.edge_geoms, gb.edge_lengths,
        )
    print(f"  Physical segments: {len(edge_groups)} "
          f"(directed edges: {gb.graph.ecount()})")

    graph_stats = {
        "nodes": gb.graph.vcount(),
        "edges": len(edge_groups),
        "directed_edges": gb.graph.ecount(),
        "cycleways_foot_yes": sum(
            1 for eids in edge_groups
            if gb.edge_highways[eids[0]] == "cycleway"
            and not gb.edge_cycleway_nf[eids[0]]
        ),
        "cycleways_no_foot": sum(
            1 for eids in edge_groups
            if gb.edge_highways[eids[0]] == "cycleway"
            and gb.edge_cycleway_nf[eids[0]]
        ),
        "streets_with_sidewalk_tags": sum(
            1 for info in gb.street_sidewalk_status.values()
            if info.doc_share > 0
        ),
    }

    with step("detect_graph_islands"):
        main_mask, island_stats = detect_graph_islands(
            gb.graph, edge_groups,
            gb.edge_tuples, gb.edge_geoms, gb.edge_lengths,
            gb.edge_highways, gb.edge_osm_ids,
            edge_levels=gb.edge_levels,
            elevator_vertices=gb.elevator_vertices,
            node_list=gb.node_list,
        )
    graph_stats["components"] = island_stats

    network_stats = compute_network_stats(
        edge_groups,
        gb.edge_highways, gb.edge_lengths,
        gb.edge_cycleway_nf, gb.edge_foot_tags,
    )

    with step("sample_od_points"):
        od_points, od_streets, od_sides, addr_gdf = sample_od_points("addresses.geojson")

    with step("snap_to_graph"):
        snapped, snap_stats = snap_to_graph(
            od_points, gb.node_list, gb.nodes_gdf,
            gb.edge_tuples, gb.edge_geoms,
            vertex_mask=main_mask,
            max_snap_m=MAX_SNAP_DISTANCE_M,
        )

    keep = [i for i, s in enumerate(snapped) if s >= 0]
    if len(keep) < len(snapped):
        od_points = [od_points[i] for i in keep]
        od_streets = [od_streets[i] for i in keep]
        od_sides = [od_sides[i] for i in keep]
        snapped = [snapped[i] for i in keep]

    od_sampling_stats = {
        **snap_stats,
        "streets_sampled": len(set(od_streets)),
        "points_even": sum(1 for s in od_sides if s == "even"),
        "points_odd": sum(1 for s in od_sides if s == "odd"),
    }

    with step("generate_od_pairs"):
        od_pairs, rejected_near, rejected_far = generate_od_pairs(
            od_points, snapped, od_streets,
        )

    with step("route_pairs"):
        result = route_pairs(
            gb.graph, od_pairs,
            gb.edge_lengths, gb.edge_highways, gb.edge_cycleway_nf,
        )

    with step("export_flow_layers"):
        flow_stats = export_flow_layers(
            result.flow_arr,
            edge_groups,
            gb.edge_highways, gb.edge_geoms,
            gb.edge_lengths, gb.edge_cycleway_nf,
            gb.edge_foot_tags,
        )

    with step("export_walkability_scores"):
        walkability_stats = export_walkability_scores(
            result.street_ped_m, result.street_cyc_nf_m, result.street_total_m,
            gb.street_sidewalk_status,
            addr_gdf,
            gb.edge_tuples, gb.edge_geoms, gb.edge_highways,
            gb.edge_surfaces, gb.edge_lits,
        )

    with step("detect_sidewalk_gaps"):
        sidewalk_gap_stats = detect_sidewalk_gaps(
            "sidewalk_roads_raw.geojson",
            "sidewalk_footways_raw.geojson",
            "cycleways_raw.geojson",
        )

    with step("export_sidewalk_roads"):
        sidewalk_road_stats = export_sidewalk_roads("sidewalk_roads_raw.geojson")

    with step("detect_missing_crossings"):
        missing_crossing_stats = detect_missing_crossings(
            "highways.geojson",
            "sidewalk_footways_raw.geojson",
            "sidewalk_roads_raw.geojson",
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
        )

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
        missing_crossing_stats=missing_crossing_stats,
        footway_connectivity_stats=footway_connectivity_stats,
        tactile_paving_stats=tactile_paving_stats,
        network_stats=network_stats,
        od_sampling_stats=od_sampling_stats,
    )

    with step("export_routing_graph"):
        export_routing_graph(
            gb.node_list, gb.nodes_gdf,
            gb.edge_tuples, gb.edge_weights, gb.edge_lengths,
            gb.edge_highways, gb.edge_geoms, gb.edge_cycleway_nf,
            gb.edge_foot_tags,
        )

    print(f"\nTotal time: {time.time() - t0:.1f}s")

    print_summary()


if __name__ == "__main__":
    main()
