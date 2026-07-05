"""
Steps 2–3 — Build the routing graph from cleaned OSM data.

1. Load the cleaned OSM XML into an **OSMnx** graph (simplified,
   projected to Belgian Lambert 72 / EPSG:31370).
2. Convert to an **igraph** directed graph with weighted edges.
3. Build a per-street sidewalk index for the walkability score.

The resulting data structures are returned as a :class:`GraphBundle`
named-tuple so the caller can pass them to the routing step without
relying on module-level mutable state.
"""

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
)
from timing import step

warnings.filterwarnings("ignore", category=RuntimeWarning)


class GraphBundle(NamedTuple):
    """All data structures produced by the graph-building step."""
    graph: ig.Graph                  # directed igraph
    node_list: list                  # ordered OSM node ids
    nodes_gdf: gpd.GeoDataFrame      # projected node geometries
    edge_tuples: list                # [(src_idx, tgt_idx), …]
    edge_weights: list[float]
    edge_lengths: list[float]
    edge_highways: list[str]
    edge_geoms: list                 # Shapely geometries (projected)
    edge_cycleway_nf: list[bool]     # True if cycleway without foot access
    edge_foot_tags: list[str]        # normalised foot tag (e.g. "yes", "designated", "")
    edge_names: list[str]            # street name on each edge
    edge_sidewalks: list[str]        # sidewalk tag on each edge
    edge_sidewalk_left: list[str]    # sidewalk:left tag
    edge_sidewalk_right: list[str]   # sidewalk:right tag
    edge_sidewalk_both: list[str]    # sidewalk:both tag
    street_sidewalk_status: dict[str, str]   # street → both|partial|none|unknown


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

# Tag values meaning "a sidewalk exists on this side / these sides".
# ``separate`` means the sidewalk is mapped as its own way — the best
# practice in OSM — so it MUST count as a sidewalk being present.
# (Previously it fell through to "unknown" and was penalised, which
# punished the best-mapped streets.)
_SIDEWALK_POSITIVE = frozenset({"yes", "both", "separate"})


def _edge_sidewalk_status(
    sw: str, sw_left: str, sw_right: str, sw_both: str,
) -> str:
    """Classify one road edge's sidewalk situation from its four tags.

    Inputs are the (lowercased) values of ``sidewalk``,
    ``sidewalk:left``, ``sidewalk:right`` and ``sidewalk:both``.

    Returns one of:

    ``both``
        Sidewalk present on both sides — ``yes``/``both``/``separate``
        on ``sidewalk`` or ``sidewalk:both``, or positive values on
        both ``sidewalk:left`` and ``sidewalk:right``.
    ``partial``
        Sidewalk documented on exactly one side — ``sidewalk=left`` /
        ``right``, or a positive ``sidewalk:left`` xor ``:right``.
    ``none``
        Explicit absence on both sides.
    ``unknown``
        Nothing conclusive: no tags, or e.g. a lone
        ``sidewalk:left=no`` which says nothing about the right side.
    """
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


def _classify_sidewalk(statuses: list[str]) -> str:
    """Aggregate per-edge statuses into one per-street status.

    *statuses* are per-edge results of :func:`_edge_sidewalk_status`.
    Priority: ``both`` > ``partial`` > ``none`` > ``unknown``.

    The returned status ``"none"`` is an internal label meaning "no
    sidewalk on either side" — it is NOT an OSM tag value (which would
    be ``no``).
    """
    s = set(statuses)
    if "both" in s:
        return "both"
    if "partial" in s:
        return "partial"
    if "none" in s:
        return "none"
    return "unknown"


def _first_str(val) -> str:
    """Normalise a value that may be a list or NaN (osmnx quirks) to a string.

    After graph simplification, OSMnx can produce:
    - ``NaN`` for tags that existed on some but not all merged segments
    - lists like ``["yes", NaN]`` when merged segments had different values
    This function extracts the first meaningful string value.
    """
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


def _unanimous_str(val) -> str:
    """Return a tag value only if ALL merged segments agree.

    Unlike ``_first_str`` which picks the first non-empty value,
    this function returns "" when:
    - some segments have the tag and others don't (mixed NaN),
    - segments disagree on the value.

    This prevents a tag present on one OSM way from "bleeding" onto
    adjacent ways that were merged during OSMnx graph simplification.

    Use this for tags where per-segment accuracy matters (e.g. sidewalk
    tags), NOT for tags where "first wins" is acceptable (e.g. street
    name, foot access).
    """
    if val is None:
        return ""
    if isinstance(val, float) and np.isnan(val):
        return ""
    if isinstance(val, list):
        values: list[str] = []
        for item in val:
            if item is None or (isinstance(item, float) and np.isnan(item)):
                # At least one segment has no value → not unanimous
                return ""
            s = str(item).strip()
            values.append(s)
        if not values:
            return ""
        # Check all non-empty values are identical
        non_empty = [v for v in values if v]
        if not non_empty:
            return ""
        if len(non_empty) < len(values):
            # Some segments had empty string, others had a value → not unanimous
            return ""
        if len(set(non_empty)) != 1:
            # Segments disagree on the value
            return ""
        return non_empty[0]
    return str(val).strip() if val else ""


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_graph(osm_path: str = "routing_clean.osm") -> GraphBundle:
    """Build the full routing graph and return a :class:`GraphBundle`."""

    # ── 2. Load with OSMnx ────────────────────────────────────────────────
    print("Building osmnx graph (simplified)...")

    # Ensure foot/sidewalk tags survive import + simplification.
    # OSMnx only keeps tags listed in useful_tags_way; foot may be
    # missing in some versions → add it explicitly.
    _extra_tags = {"foot", "route", "sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both", "segregated"}
    if hasattr(ox, "settings"):
        existing = set(getattr(ox.settings, "useful_tags_way", []))
        if not _extra_tags.issubset(existing):
            ox.settings.useful_tags_way = list(existing | _extra_tags)
            print(f"  Added {_extra_tags - existing} to useful_tags_way")

    with step("ox.graph_from_xml"):
        # bidirectional=True: ``oneway=yes`` applies to vehicles, not
        # pedestrians.  Without it, OSMnx omits the reverse edge on
        # one-way streets and the router cannot walk "against" traffic,
        # biasing flows toward two-way streets.  (The rare
        # ``oneway:foot=yes`` cases — e.g. some hiking paths — are
        # knowingly ignored.)
        G = ox.graph_from_xml(
            osm_path, retain_all=True, simplify=True, bidirectional=True,
        )
    with step("ox.project_graph (→ EPSG:31370)"):
        G_proj = ox.project_graph(G, to_crs="EPSG:31370")
    with step("ox.graph_to_gdfs"):
        nodes_gdf, edges_gdf = ox.graph_to_gdfs(G_proj)
    print(f"  Nodes: {len(nodes_gdf)}, Edges: {len(edges_gdf)}")

    # ── 3a. Convert to igraph ─────────────────────────────────────────────
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

    skipped_foot = skipped_access = skipped_ferry = 0

    # ── Suspected bottleneck: iterrows over ~10⁵ edges with per-row Python work.
    with step("edges_gdf.iterrows → arrays"):
        for (u, v, _k), row in edges_gdf.iterrows():
            route_tag = _first_str(row.get("route", "")).lower()
            hw = _first_str(row.get("highway", "unclassified")) or "unclassified"
            foot_tag = _first_str(row.get("foot", "")).lower()
            access_tag = _first_str(row.get("access", "")).lower()

            # ── Access filtering ──────────────────────────────────────────
            if route_tag == "ferry":
                skipped_ferry += 1
                continue
            if foot_tag in FOOT_FORBIDDEN:
                skipped_foot += 1
                continue
            if access_tag in ACCESS_EXCLUDED:
                skipped_access += 1
                continue

            # ── Cost calculation ──────────────────────────────────────────
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

            # ── Sidewalk tags: use _unanimous_str to avoid tag bleeding ───
            edge_sidewalks.append(_unanimous_str(row.get("sidewalk", "")).lower())
            edge_sidewalk_left.append(_unanimous_str(row.get("sidewalk:left", "")).lower())
            edge_sidewalk_right.append(_unanimous_str(row.get("sidewalk:right", "")).lower())
            edge_sidewalk_both.append(_unanimous_str(row.get("sidewalk:both", "")).lower())

    print(f"  Edges skipped — ferry: {skipped_ferry}, foot=no: {skipped_foot}, "
          f"access=no/private: {skipped_access}")

    # Debug: cycleway classification stats
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

    # ── 3b. Sidewalk index ────────────────────────────────────────────────
    with step("sidewalk index"):
        street_statuses: dict[str, list[str]] = defaultdict(list)
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
            # "unknown" edges (no conclusive tag) are not recorded, so a
            # street with zero documented edges stays OUT of the index —
            # same behaviour as before (no penalty applied downstream).
            if status != "unknown":
                street_statuses[name].append(status)

        street_sidewalk_status = {
            name: _classify_sidewalk(st) for name, st in street_statuses.items()
        }

    counts = defaultdict(int)
    for v in street_sidewalk_status.values():
        counts[v] += 1
    print(f"  Sidewalk status — both: {counts['both']} | "
          f"partial: {counts['partial']} | none: {counts['none']} | "
          f"unknown (no tag): {counts['unknown']}")
    print(f"  Streets with road edges: {len(street_sidewalk_status)}")

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
        street_sidewalk_status=street_sidewalk_status,
    )
