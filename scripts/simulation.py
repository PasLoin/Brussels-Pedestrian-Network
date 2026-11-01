from __future__ import annotations

from typing import NamedTuple

from build_graph import GraphBundle, is_ground_level
from export import export_flow_layers
from routing import RoutingResult, generate_od_pairs, route_pairs
from sample_od import snap_to_graph
from timing import step


class SimulationResult(NamedTuple):
    od_points: list
    od_pairs: list
    rejected_near: int
    rejected_far: int
    routing: RoutingResult
    od_sampling_stats: dict
    flow_stats: dict


def drop_unsnapped(
    snapped: list[int], *columns: list,
) -> tuple[list[int], ...]:
    keep = [i for i, s in enumerate(snapped) if s >= 0]
    return tuple([col[i] for i in keep] for col in (snapped, *columns))


def simulate_flows(
    gb: GraphBundle,
    edge_groups: list[list[int]],
    main_mask,
    od_points: list[tuple[float, float]],
    od_streets: list[str],
    od_sides: list[str],
    max_snap_m: float | None,
) -> SimulationResult:
    with step("snap_to_graph"):
        snapped, snap_stats = snap_to_graph(
            od_points, gb.node_list, gb.nodes_gdf,
            gb.edge_tuples, gb.edge_geoms,
            vertex_mask=main_mask,
            max_snap_m=max_snap_m,
            edge_snappable=[is_ground_level(lv) for lv in gb.edge_levels],
        )

    snapped, od_points, od_streets, od_sides = drop_unsnapped(
        snapped, od_points, od_streets, od_sides,
    )

    od_sampling_stats = {
        **snap_stats,
        "streets_sampled": len(set(od_streets)),
        "points_even": sum(1 for s in od_sides if s == "even"),
        "points_odd": sum(1 for s in od_sides if s == "odd"),
    }

    with step("generate_od_pairs"):
        od_pairs, rejected_near, rejected_far = generate_od_pairs(od_points, snapped)

    with step("route_pairs"):
        routing = route_pairs(gb.graph, od_pairs, gb.edge_lengths)

    with step("export_flow_layers"):
        flow_stats = export_flow_layers(
            routing.flow_arr,
            edge_groups,
            gb.edge_highways, gb.edge_geoms,
            gb.edge_lengths, gb.edge_cycleway_nf,
            gb.edge_foot_tags,
        )

    return SimulationResult(
        od_points=od_points,
        od_pairs=od_pairs,
        rejected_near=rejected_near,
        rejected_far=rejected_far,
        routing=routing,
        od_sampling_stats=od_sampling_stats,
        flow_stats=flow_stats,
    )
