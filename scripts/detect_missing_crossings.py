"""
Detect highway=crossing nodes that are missing a corresponding crossing way
or the ``footway=crossing`` tag.

Two categories are detected and stored in the ``type`` property of the
output GeoJSON:

``missing_way``
    No ``highway=footway`` or ``highway=pedestrian`` way passes within
    ``CROSSING_NODE_CONNECTED_M`` of the node.  The crossing is not
    mapped at all in the pedestrian network.  Shown in orange.

``missing_tag``
    A footway passes through the node (shared-node connectivity confirmed)
    but no ``footway=crossing`` sub-tag exists within
    ``CROSSING_WAY_SEARCH_RADIUS_M``.  The crossing exists geometrically
    but the tag is absent, preventing routers and renderers from
    recognising it.  Shown in yellow.

Both categories require ``footway=sidewalk`` ways to be drawn on **both**
sides of the road near the node — only locations where the pedestrian
infrastructure already exists are flagged.

Inputs
------
* ``highways.geojson``              — crossing nodes (Point, highway=crossing)
* ``sidewalk_footways_raw.geojson`` — raw osmium footway export
* ``sidewalk_roads_raw.geojson``    — raw osmium road export

Output
------
``missing_crossings.geojson`` — point layer with properties:
  ``name``   road name
  ``type``   ``"missing_way"`` or ``"missing_tag"``
  ``left``   True if footway=sidewalk found on left side
  ``right``  True if footway=sidewalk found on right side
"""

from __future__ import annotations

import json
import math
import os

import geopandas as gpd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from timing import step

_CROSSING_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}
_MIN_ROAD_LENGTH = 15.0

# ── Config ────────────────────────────────────────────────────────────────────

CROSSING_NODE_ROAD_SEARCH_M  = float(os.environ.get("CROSSING_NODE_ROAD_SEARCH_M",  20.0))
CROSSING_WAY_SEARCH_RADIUS_M = float(os.environ.get("CROSSING_WAY_SEARCH_RADIUS_M", 20.0))
CROSSING_NODE_CONNECTED_M    = float(os.environ.get("CROSSING_NODE_CONNECTED_M",     3.0))
CROSSING_SIDEWALK_OFFSET_M   = float(os.environ.get("CROSSING_SIDEWALK_OFFSET_M",    7.0))
CROSSING_SIDEWALK_SEARCH_M   = float(os.environ.get("CROSSING_SIDEWALK_SEARCH_M",   15.0))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


def _intersects_any(zone, tree: STRtree, geoms: list) -> bool:
    return any(geoms[i].intersects(zone) for i in tree.query(zone))


def _road_left_perp(road_geom, node_pt, step: float = 3.0) -> tuple[float, float] | None:
    d  = road_geom.project(node_pt)
    p1 = road_geom.interpolate(max(0.0, d - step))
    p2 = road_geom.interpolate(min(road_geom.length, d + step))
    dx, dy = p2.x - p1.x, p2.y - p1.y
    norm = math.hypot(dx, dy)
    if norm < 0.01:
        return None
    return (-dy / norm, dx / norm)


def _sidewalk_zones(node_pt: Point, perp: tuple[float, float]):
    px, py = perp
    left  = Point(node_pt.x + px * CROSSING_SIDEWALK_OFFSET_M,
                  node_pt.y + py * CROSSING_SIDEWALK_OFFSET_M)
    right = Point(node_pt.x - px * CROSSING_SIDEWALK_OFFSET_M,
                  node_pt.y - py * CROSSING_SIDEWALK_OFFSET_M)
    return left.buffer(CROSSING_SIDEWALK_SEARCH_M), right.buffer(CROSSING_SIDEWALK_SEARCH_M)


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_crossing_nodes(highways_path: str) -> gpd.GeoDataFrame:
    """Read highway=crossing point features via stdlib json.

    Avoids gpd.read_file issues with mixed-geometry FeatureCollections
    and the nested-FC structure produced by the jq slim step.
    """
    with open(highways_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    features = raw.get("features", [])
    if isinstance(features, dict):
        features = features.get("features", [])
    rows = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom  = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if geom.get("type") != "Point":
            continue
        if _safe_str(props.get("highway")) != "crossing":
            continue
        try:
            rows.append({"geometry": shape(geom)})
        except Exception:
            continue
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_crs("EPSG:31370")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs("EPSG:31370")


def _load_crossing_ways(footways_path: str) -> tuple[list, STRtree | None]:
    """Tier 1 — footway=crossing ways only."""
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "crossing")
    )
    geoms = list(gdf[mask].geometry)
    return geoms, (STRtree(geoms) if geoms else None)


def _load_all_footways(footways_path: str) -> tuple[list, STRtree | None]:
    """Tier 2 — ALL highway=footway/pedestrian (shared-node check)."""
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    if "highway" not in gdf.columns:
        gdf["highway"] = ""
    mask = gdf["highway"].apply(_safe_str).isin(["footway", "pedestrian"])
    geoms = list(gdf[mask].geometry)
    return geoms, (STRtree(geoms) if geoms else None)


def _load_sidewalk_ways(footways_path: str) -> tuple[list, STRtree | None]:
    """footway=sidewalk only — strict filter to avoid false positives."""
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "sidewalk")
    )
    geoms = list(gdf[mask].geometry)
    print(f"  footway=sidewalk ways: {len(geoms)}")
    return geoms, (STRtree(geoms) if geoms else None)


def _load_roads(roads_path: str) -> tuple[gpd.GeoDataFrame, list, STRtree]:
    gdf = gpd.read_file(roads_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    gdf = gdf[gdf["highway"].isin(_CROSSING_ROAD_TYPES)]
    gdf = gdf[gdf.geometry.length >= _MIN_ROAD_LENGTH]
    gdf = gdf.reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, STRtree(geoms)


# ── Main ──────────────────────────────────────────────────────────────────────

def detect_missing_crossings(
    highways_geojson_path: str = "highways.geojson",
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    roads_geojson_path:    str = "sidewalk_roads_raw.geojson",
) -> dict:
    """Detect crossing nodes with missing way or missing footway=crossing tag.

    Returns a statistics dict for stats.json.
    """
    print("Detecting missing crossing ways / tags...")
    print(
        f"  Tier-1 (footway=crossing): {CROSSING_WAY_SEARCH_RADIUS_M} m | "
        f"Tier-2 (any footway / shared node): {CROSSING_NODE_CONNECTED_M} m | "
        f"Sidewalk offset {CROSSING_SIDEWALK_OFFSET_M} m "
        f"+ radius {CROSSING_SIDEWALK_SEARCH_M} m"
    )

    with step("load crossing nodes"):
        crossing_nodes = _load_crossing_nodes(highways_geojson_path)
    print(f"  highway=crossing nodes: {len(crossing_nodes)}")

    if crossing_nodes.empty:
        print("  No crossing nodes — skipping.")
        _write_empty_output()
        return {"crossing_nodes_found": 0, "missing_crossings_detected": 0}

    with step("load footway=crossing ways (tier 1)"):
        cw_geoms, cw_tree = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways: {len(cw_geoms)}")

    with step("load all footways (tier 2)"):
        all_fw_geoms, all_fw_tree = _load_all_footways(footways_geojson_path)
    print(f"  All footway/pedestrian ways: {len(all_fw_geoms)}")

    with step("load footway=sidewalk ways"):
        sw_geoms, sw_tree = _load_sidewalk_ways(footways_geojson_path)

    with step("load eligible roads"):
        roads_gdf, road_geoms, road_tree = _load_roads(roads_geojson_path)
    print(f"  Eligible road segments: {len(roads_gdf)}")

    if sw_tree is None:
        print("  No footway=sidewalk ways — skipping.")
        _write_empty_output()
        return {"crossing_nodes_found": len(crossing_nodes),
                "missing_crossings_detected": 0}

    rows: list[dict] = []
    n_no_road = 0
    n_fully_ok = 0   # tier 1 matched → completely fine, skip
    n_no_sw   = 0
    n_missing_way = 0
    n_missing_tag = 0

    with step("crossing node analysis loop"):
        for _, node_row in crossing_nodes.iterrows():
            node_pt = node_row.geometry

            # 1. Find nearest eligible road ────────────────────────────────
            road_cands = road_tree.query(node_pt.buffer(CROSSING_NODE_ROAD_SEARCH_M))
            if not len(road_cands):
                n_no_road += 1
                continue

            best_idx = min(road_cands,
                           key=lambda i: road_geoms[i].distance(node_pt))
            road_geom = road_geoms[best_idx]

            # 2. Tier-1 check: footway=crossing way nearby ─────────────────
            #    If found → crossing is properly tagged → skip entirely.
            tier1 = False
            if cw_tree is not None:
                if _intersects_any(node_pt.buffer(CROSSING_WAY_SEARCH_RADIUS_M),
                                   cw_tree, cw_geoms):
                    tier1 = True

            if tier1:
                n_fully_ok += 1
                continue

            # 3. Tier-2 check: any footway passing through this node ────────
            #    Shared node → distance ≈ 0.  Crossing exists geometrically
            #    but may lack the footway=crossing tag.
            tier2 = False
            if all_fw_tree is not None:
                if _intersects_any(node_pt.buffer(CROSSING_NODE_CONNECTED_M),
                                   all_fw_tree, all_fw_geoms):
                    tier2 = True

            # Determine issue type
            # tier1=False, tier2=True  → crossing way present but tag missing
            # tier1=False, tier2=False → crossing way absent altogether
            crossing_type = "missing_tag" if tier2 else "missing_way"

            # 4. Require footway=sidewalk on both sides ─────────────────────
            perp = _road_left_perp(road_geom, node_pt)
            if perp is None:
                n_no_road += 1
                continue

            left_zone, right_zone = _sidewalk_zones(node_pt, perp)
            has_left  = _intersects_any(left_zone,  sw_tree, sw_geoms)
            has_right = _intersects_any(right_zone, sw_tree, sw_geoms)

            if not (has_left and has_right):
                n_no_sw += 1
                continue

            # 5. Flag ──────────────────────────────────────────────────────
            road_name = ""
            if "name" in roads_gdf.columns:
                road_name = _safe_str(roads_gdf.iloc[best_idx]["name"])

            if crossing_type == "missing_way":
                n_missing_way += 1
            else:
                n_missing_tag += 1

            rows.append({
                "geometry": node_pt,
                "name":  road_name,
                "type":  crossing_type,
                "left":  has_left,
                "right": has_right,
            })

    with step("write missing_crossings.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = gpd.GeoDataFrame(
                [{"geometry": None, "name": "", "type": "",
                  "left": False, "right": False}],
                crs="EPSG:4326",
            )
        out_gdf.to_file("missing_crossings.geojson", driver="GeoJSON")

    n_total = len(crossing_nodes)
    print(f"  Nodes analysed:                        {n_total}")
    print(f"  Skipped — no eligible road:            {n_no_road}")
    print(f"  Skipped — crossing fully mapped (t1):  {n_fully_ok}")
    print(f"  Skipped — sidewalk missing on a side:  {n_no_sw}")
    print(f"  Missing crossing WAY detected:         {n_missing_way}")
    print(f"  Missing footway=crossing TAG detected: {n_missing_tag}")

    return {
        "crossing_nodes_found":        n_total,
        "no_eligible_road":            n_no_road,
        "crossing_fully_mapped":       n_fully_ok,
        "sidewalk_missing_on_a_side":  n_no_sw,
        "missing_crossing_way":        n_missing_way,
        "missing_crossing_tag":        n_missing_tag,
        "missing_crossings_detected":  n_missing_way + n_missing_tag,
    }


def _write_empty_output() -> None:
    gpd.GeoDataFrame(
        [{"geometry": None, "name": "", "type": "", "left": False, "right": False}],
        crs="EPSG:4326",
    ).to_file("missing_crossings.geojson", driver="GeoJSON")
