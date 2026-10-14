from __future__ import annotations

import warnings
from collections import defaultdict
from typing import NamedTuple

import geopandas as gpd
import igraph as ig
import numpy as np
import osmnx as ox

from config import (
    ACCESS_EXCLUDED,
    CYCLEWAY_FOOT_ALLOWED_COST,
    CYCLEWAY_NO_FOOT_COST,
    EDGE_COST,
    EDGE_COST_DEFAULT,
    FOOT_ALLOWED,
    FOOT_FORBIDDEN,
    PED_HIGHWAY_TYPES,
    ROAD_TYPES_SIDEWALK_EXPECTED,
    SIDEWALK_PENALTY_NONE,
    SIDEWALK_PENALTY_PARTIAL,
    SIDEWALK_PENALTY_UNKNOWN,
)
from timing import step

warnings.filterwarnings("ignore", category=RuntimeWarning)


class SidewalkInfo(NamedTuple):
    status: str
    penalty: float
    doc_share: float


class GraphBundle(NamedTuple):
    graph: ig.Graph
    node_list: list
    nodes_gdf: gpd.GeoDataFrame
    edge_tuples: list
    edge_weights: list[float]
    edge_lengths: list[float]
    edge_highways: list[str]
    edge_geoms: list
    edge_cycleway_nf: list[bool]
    edge_foot_tags: list[str]
    edge_names: list[str]
    edge_sidewalks: list[str]
    edge_sidewalk_left: list[str]
    edge_sidewalk_right: list[str]
    edge_sidewalk_both: list[str]
    edge_surfaces: list[str]
    edge_lits: list[str]
    street_sidewalk_status: dict[str, SidewalkInfo]
    edge_osm_ids: list[tuple[int, ...]] = []


_SIDEWALK_POSITIVE = frozenset({"yes", "both", "separate"})


def _edge_sidewalk_status(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> str:
    if sw == "no" or sw_both == "no" or (sw_left == "no" and sw_right == "no"):
        return "none"
    if sw in _SIDEWALK_POSITIVE or sw_both in _SIDEWALK_POSITIVE:
        return "both"
    left_ok = sw_left in _SIDEWALK_POSITIVE or sw == "left"
    right_ok = sw_right in _SIDEWALK_POSITIVE or sw == "right"
    if left_ok and right_ok:
        return "both"
    if left_ok or right_ok:
        return "partial"
    return "unknown"


_STATUS_PENALTY = {
    "both": 1.0,
    "partial": SIDEWALK_PENALTY_PARTIAL,
    "none": SIDEWALK_PENALTY_NONE,
    "unknown": SIDEWALK_PENALTY_UNKNOWN,
}

_STATUS_PESSIMISM = {"both": 0, "partial": 1, "none": 2, "unknown": 3}


def _aggregate_sidewalk(length_by_status: dict[str, float]) -> SidewalkInfo:
    total = sum(length_by_status.values())
    if total <= 0:
        return SidewalkInfo("unknown", SIDEWALK_PENALTY_UNKNOWN, 0.0)

    status = max(
        length_by_status.items(),
        key=lambda kv: (kv[1], _STATUS_PESSIMISM.get(kv[0], 3)),
    )[0]

    penalty = sum(
        length * _STATUS_PENALTY.get(st, SIDEWALK_PENALTY_UNKNOWN)
        for st, length in length_by_status.items()
    ) / total

    documented = total - length_by_status.get("unknown", 0.0)
    return SidewalkInfo(status, round(penalty, 3), round(documented / total, 3))


def _first_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and np.isnan(val):
        return ""
    if isinstance(val, list):
        for item in val:
            if item is None:
                continue
            if isinstance(item, float) and np.isnan(item):
                continue
            s = str(item).strip()
            if s:
                return s
        return ""
    return str(val).strip() if val else ""


def _osm_way_ids(val) -> tuple[int, ...]:
    values = val if isinstance(val, list) else [val]
    out: list[int] = []
    for item in values:
        try:
            way_id = int(item)
        except (TypeError, ValueError):
            continue
        if way_id > 0 and way_id not in out:
            out.append(way_id)
    return tuple(out)


def _unanimous_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and np.isnan(val):
        return ""
    if isinstance(val, list):
        values: list[str] = []
        for item in val:
            if item is None or (isinstance(item, float) and np.isnan(item)):
                return ""
            s = str(item).strip()
            values.append(s)
        if not values:
            return ""
        non_empty = [v for v in values if v]
        if not non_empty:
            return ""
        if len(non_empty) < len(values):
            return ""
        if len(set(non_empty)) != 1:
            return ""
        return non_empty[0]
    return str(val).strip() if val else ""


def build_graph(osm_path: str = "routing_clean.osm") -> GraphBundle:

    print("Building osmnx graph (simplified)...")

    _extra_tags = {"foot", "route", "sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both", "segregated", "surface", "lit"}
    if hasattr(ox, "settings"):
        existing = set(getattr(ox.settings, "useful_tags_way", []))
        if not _extra_tags.issubset(existing):
            ox.settings.useful_tags_way = list(existing | _extra_tags)
            print(f"  Added {_extra_tags - existing} to useful_tags_way")

    _ATTRS_NO_MERGE = [
        "name", "highway", "access", "foot",
        "sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both",
    ]

    with step("ox.graph_from_xml"):
        G = ox.graph_from_xml(
            osm_path, retain_all=True, simplify=False, bidirectional=True,
        )
    with step("ox.simplify_graph (edge_attrs_differ)"):
        try:
            G = ox.simplification.simplify_graph(
                G, edge_attrs_differ=_ATTRS_NO_MERGE,
            )
        except TypeError:
            print("  WARNING: osmnx.simplify_graph lacks edge_attrs_differ; "
                  "falling back to plain simplification")
            G = ox.simplification.simplify_graph(G)
    with step("ox.project_graph (→ EPSG:31370)"):
        G_proj = ox.project_graph(G, to_crs="EPSG:31370")
    with step("ox.graph_to_gdfs"):
        nodes_gdf, edges_gdf = ox.graph_to_gdfs(G_proj)
    print(f"  Nodes: {len(nodes_gdf)}, Edges: {len(edges_gdf)}")

    print("Converting to igraph...")
    node_list = list(nodes_gdf.index)
    node_map = {nid: i for i, nid in enumerate(node_list)}

    edge_tuples: list[tuple[int, int]] = []
    edge_weights: list[float] = []
    edge_lengths: list[float] = []
    edge_highways: list[str] = []
    edge_geoms: list = []
    edge_cycleway_nf: list[bool] = []
    edge_foot_tags: list[str] = []
    edge_names: list[str] = []
    edge_sidewalks: list[str] = []
    edge_sidewalk_left: list[str] = []
    edge_sidewalk_right: list[str] = []
    edge_sidewalk_both: list[str] = []
    edge_surfaces: list[str] = []
    edge_lits: list[str] = []
    edge_osm_ids: list[tuple[int, ...]] = []

    skipped_foot = skipped_access = skipped_ferry = 0
    skipped_no_highway = skipped_bridleway = 0

    with step("edges_gdf.iterrows → arrays"):
        for (u, v, _k), row in edges_gdf.iterrows():
            route_tag = _first_str(row.get("route", "")).lower()
            hw = _first_str(row.get("highway", ""))
            foot_tag = _first_str(row.get("foot", "")).lower()
            access_tag = _first_str(row.get("access", "")).lower()

            if route_tag == "ferry":
                skipped_ferry += 1
                continue
            if not hw:
                skipped_no_highway += 1
                continue
            if foot_tag in FOOT_FORBIDDEN:
                skipped_foot += 1
                continue
            if access_tag in ACCESS_EXCLUDED and foot_tag not in FOOT_ALLOWED:
                skipped_access += 1
                continue
            if hw == "bridleway" and foot_tag not in FOOT_ALLOWED:
                skipped_bridleway += 1
                continue

            base_cost = EDGE_COST.get(hw, EDGE_COST_DEFAULT)
            is_cycleway_no_foot = False
            if hw == "cycleway":
                if foot_tag in FOOT_ALLOWED:
                    base_cost = CYCLEWAY_FOOT_ALLOWED_COST
                else:
                    base_cost = CYCLEWAY_NO_FOOT_COST
                    is_cycleway_no_foot = True

            length = float(row.get("length", 1.0))

            edge_tuples.append((node_map[u], node_map[v]))
            edge_weights.append(length * base_cost)
            edge_lengths.append(length)
            edge_highways.append(hw)
            edge_geoms.append(row.geometry)
            edge_cycleway_nf.append(is_cycleway_no_foot)
            edge_foot_tags.append(foot_tag)
            edge_names.append(_first_str(row.get("name", "")))

            edge_sidewalks.append(_unanimous_str(row.get("sidewalk", "")).lower())
            edge_sidewalk_left.append(_unanimous_str(row.get("sidewalk:left", "")).lower())
            edge_sidewalk_right.append(_unanimous_str(row.get("sidewalk:right", "")).lower())
            edge_sidewalk_both.append(_unanimous_str(row.get("sidewalk:both", "")).lower())

            edge_surfaces.append(_unanimous_str(row.get("surface", "")).lower())
            edge_lits.append(_unanimous_str(row.get("lit", "")).lower())
            edge_osm_ids.append(_osm_way_ids(row.get("osmid")))

    print(f"  Edges skipped — ferry: {skipped_ferry}, foot=no: {skipped_foot}, "
          f"access=no/private: {skipped_access}, no highway tag: {skipped_no_highway}, "
          f"bridleway without foot=yes: {skipped_bridleway}")

    n_cyc_foot = sum(1 for h, c in zip(edge_highways, edge_cycleway_nf) if h == "cycleway" and not c)
    n_cyc_nf   = sum(1 for h, c in zip(edge_highways, edge_cycleway_nf) if h == "cycleway" and c)
    print(f"  Cycleways — foot=yes: {n_cyc_foot} | no foot: {n_cyc_nf}")

    with step("ig.Graph assembly"):
        g = ig.Graph(directed=True, n=len(node_list))
        g.vs["osmid"] = node_list
        g.add_edges(edge_tuples)
        g.es["weight"] = edge_weights
        g.es["length"] = edge_lengths
        g.es["highway"] = edge_highways
        g.es["geometry"] = edge_geoms
        g.es["cycleway_nf"] = edge_cycleway_nf
    print(f"  igraph: {g.vcount()} vertices, {g.ecount()} edges")

    with step("sidewalk index"):
        street_lengths: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for eid in range(len(edge_names)):
            name = edge_names[eid]
            hw = edge_highways[eid]
            if not name or hw not in ROAD_TYPES_SIDEWALK_EXPECTED:
                continue
            status = _edge_sidewalk_status(
                edge_sidewalks[eid],
                edge_sidewalk_left[eid],
                edge_sidewalk_right[eid],
                edge_sidewalk_both[eid],
            )
            street_lengths[name][status] += edge_lengths[eid]

        street_sidewalk_status = {
            name: _aggregate_sidewalk(lengths)
            for name, lengths in street_lengths.items()
        }

    counts = defaultdict(int)
    for info in street_sidewalk_status.values():
        counts[info.status] += 1
    n_documented = sum(
        1 for info in street_sidewalk_status.values() if info.doc_share > 0
    )
    print(f"  Sidewalk status (dominant) — both: {counts['both']} | "
          f"partial: {counts['partial']} | none: {counts['none']} | "
          f"unknown: {counts['unknown']}")
    print(f"  Streets with road edges: {len(street_sidewalk_status)} "
          f"(with ≥1 sidewalk tag: {n_documented})")

    return GraphBundle(
        graph=g,
        node_list=node_list,
        nodes_gdf=nodes_gdf,
        edge_tuples=edge_tuples,
        edge_weights=edge_weights,
        edge_lengths=edge_lengths,
        edge_highways=edge_highways,
        edge_geoms=edge_geoms,
        edge_cycleway_nf=edge_cycleway_nf,
        edge_foot_tags=edge_foot_tags,
        edge_names=edge_names,
        edge_sidewalks=edge_sidewalks,
        edge_sidewalk_left=edge_sidewalk_left,
        edge_sidewalk_right=edge_sidewalk_right,
        edge_sidewalk_both=edge_sidewalk_both,
        edge_surfaces=edge_surfaces,
        edge_lits=edge_lits,
        street_sidewalk_status=street_sidewalk_status,
        edge_osm_ids=edge_osm_ids,
    )
