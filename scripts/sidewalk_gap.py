"""
Detect sidewalk gaps — roads with a footway on one side but not the other.

For each road segment, the geometry is offset left and right to create
search zones.  If a footway intersects one side but not the other, the
road is flagged as a sidewalk gap — a strong signal that the footway
on the missing side either doesn't exist or hasn't been mapped yet.

This analysis is purely geometric.  It does not rely on ``sidewalk=*``
tags on the road; it checks whether a **separate footway way** has
been drawn in OSM on each side.
"""

from __future__ import annotations

import os

import geopandas as gpd
from shapely.strtree import STRtree

from config import PED_HIGHWAY_TYPES, ROAD_TYPES_SIDEWALK_EXPECTED

# How far from the road centerline to look for footways (metres).
SIDEWALK_GAP_OFFSET_M = float(os.environ.get("SIDEWALK_GAP_OFFSET_M", 12))

# Buffer radius around the offset line (metres).  The search band
# extends from (offset - search) to (offset + search) metres from
# the road centerline.
SIDEWALK_GAP_SEARCH_M = float(os.environ.get("SIDEWALK_GAP_SEARCH_M", 8))

# Skip road segments shorter than this (metres) — too short to
# meaningfully detect a gap.
_MIN_ROAD_LENGTH = 20.0


def detect_sidewalk_gaps(
    edge_tuples: list[tuple[int, int]],
    edge_highways: list[str],
    edge_geoms: list,
    edge_names: list[str],
) -> None:
    """Detect roads with a footway on one side only.

    Writes ``sidewalk_gaps.geojson`` with one feature per gap segment.
    """
    print("Detecting sidewalk gaps (footway on one side only)...")
    print(f"  Offset: {SIDEWALK_GAP_OFFSET_M}m | "
          f"Search radius: {SIDEWALK_GAP_SEARCH_M}m")

    # ── Collect footway geometries ────────────────────────────────────────
    footway_geoms: list = []
    for eid in range(len(edge_tuples)):
        hw = edge_highways[eid]
        geom = edge_geoms[eid]
        if hw in PED_HIGHWAY_TYPES and geom is not None and not geom.is_empty:
            footway_geoms.append(geom)

    footway_tree = STRtree(footway_geoms)
    print(f"  Footway segments indexed: {len(footway_geoms)}")

    # ── Check each road segment ───────────────────────────────────────────
    rows: list[dict] = []
    n_roads = 0
    n_both = 0
    n_none = 0
    n_gap = 0

    for eid in range(len(edge_tuples)):
        hw = edge_highways[eid]
        if hw not in ROAD_TYPES_SIDEWALK_EXPECTED:
            continue
        geom = edge_geoms[eid]
        if geom is None or geom.is_empty or geom.length < _MIN_ROAD_LENGTH:
            continue

        n_roads += 1

        # Offset left and right to create search zones
        try:
            left_line = geom.offset_curve(SIDEWALK_GAP_OFFSET_M)
            right_line = geom.offset_curve(-SIDEWALK_GAP_OFFSET_M)
        except Exception:
            continue

        if left_line.is_empty or right_line.is_empty:
            continue

        left_zone = left_line.buffer(SIDEWALK_GAP_SEARCH_M)
        right_zone = right_line.buffer(SIDEWALK_GAP_SEARCH_M)

        # Query footway index
        left_candidates = footway_tree.query(left_zone)
        right_candidates = footway_tree.query(right_zone)

        has_left = any(
            footway_geoms[i].intersects(left_zone) for i in left_candidates
        )
        has_right = any(
            footway_geoms[i].intersects(right_zone) for i in right_candidates
        )

        if has_left and has_right:
            n_both += 1
        elif not has_left and not has_right:
            n_none += 1
        else:
            # One side only → gap detected
            n_gap += 1
            rows.append({
                "geometry": geom,
                "name": edge_names[eid] if eid < len(edge_names) else "",
            })

    # ── Save output ───────────────────────────────────────────────────────
    fb = {"geometry": None, "name": ""}
    if rows:
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame([fb], crs="EPSG:4326")
    gdf.to_file("sidewalk_gaps.geojson", driver="GeoJSON")

    print(f"  Roads analysed: {n_roads}")
    print(f"  Both sides: {n_both} | One side (gap): {n_gap} | "
          f"Neither side: {n_none}")
    print(f"  Sidewalk gaps exported: {len(rows)}")
