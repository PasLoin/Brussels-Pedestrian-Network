"""
Steps 4–5 — Sample origin-destination points from address data.

The pipeline needs realistic trip endpoints.  Rather than placing
origins and destinations at random locations, we sample them from
**OSM address nodes** (``addr:housenumber``).  This produces trips that
start and end at actual building entrances, giving the flow simulation
a more realistic pattern.

Sampling strategy
-----------------
For each street (``addr:street``), addresses are split into even and
odd house numbers (approximating the two sides of the street).  Within
each side, ``POINTS_PER_SIDE`` evenly-spaced addresses are picked so
that both ends and the middle of the street are represented.

After sampling, each point is snapped to the nearest graph node using
a Shapely STRtree spatial index.
"""

from __future__ import annotations

import re

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from config import POINTS_PER_SIDE


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_house_number(hn) -> int | None:
    """Return the leading integer from a house-number string, or None."""
    m = re.match(r"(\d+)", str(hn))
    return int(m.group(1)) if m else None


def _pick_indices(n: int, k: int) -> list[int]:
    """Return *k* evenly-spaced indices into a sequence of length *n*.

    If *n* < *k*, returns a single index at the midpoint.
    """
    if n == 0:
        return []
    if n < k:
        return [n // 2]
    return [int(n * (i + 1) / (k + 1)) for i in range(k)]


# ─────────────────────────────────────────────────────────────────────────────
# Public
# ─────────────────────────────────────────────────────────────────────────────

def sample_od_points(
    addresses_path: str = "addresses.geojson",
) -> tuple[list[tuple[float, float]], list[str], list[str]]:
    """Sample OD points from address data.

    Returns
    -------
    od_points : list of (x, y)
        Coordinates in EPSG:31370.
    od_streets : list of str
        Street name for each point.
    od_sides : list of str
        ``"even"`` or ``"odd"`` for each point.
    """
    print(f"Sampling OD points ({POINTS_PER_SIDE} per side, even/odd split)...")

    addr = gpd.read_file(addresses_path).to_crs("EPSG:31370")
    addr["_num"] = addr.get("addr:housenumber", "").apply(_extract_house_number)
    addr = addr.dropna(subset=["_num"])
    addr["_num"] = addr["_num"].astype(int)

    if "addr:street" not in addr.columns:
        addr["addr:street"] = ""
    addr = addr[addr["addr:street"].notna()]
    addr = addr[addr["addr:street"].astype(str).str.strip() != ""]

    od_points: list[tuple[float, float]] = []
    od_streets: list[str] = []
    od_sides: list[str] = []
    streets_both = streets_one = 0

    for street, grp in addr.groupby("addr:street"):
        sides_sampled = 0
        for side_name, side_grp in [
            ("even", grp[grp["_num"] % 2 == 0]),
            ("odd", grp[grp["_num"] % 2 == 1]),
        ]:
            sorted_side = side_grp.sort_values("_num")
            idxs = _pick_indices(len(sorted_side), POINTS_PER_SIDE)
            if not idxs:
                continue
            for i in idxs:
                row = sorted_side.iloc[i]
                od_points.append((row.geometry.x, row.geometry.y))
                od_streets.append(str(street))
                od_sides.append(side_name)
            sides_sampled += 1

        if sides_sampled == 2:
            streets_both += 1
        elif sides_sampled == 1:
            streets_one += 1

    print(f"  OD points: {len(od_points)}")
    print(f"  Streets both sides: {streets_both} | one side: {streets_one}")
    return od_points, od_streets, od_sides


def snap_to_graph(
    od_points: list[tuple[float, float]],
    node_list: list,
    nodes_gdf: gpd.GeoDataFrame,
) -> list[int]:
    """Snap each OD point to the nearest graph node (by index).

    Uses a Shapely STRtree for efficient nearest-neighbour lookup.
    """
    print("Snapping OD points to graph nodes...")
    node_xy = np.array([
        [nodes_gdf.loc[n, "x"], nodes_gdf.loc[n, "y"]]
        for n in node_list
    ])
    tree = STRtree([Point(x, y) for x, y in node_xy])
    snapped = [int(tree.nearest(Point(x, y))) for x, y in od_points]
    return snapped
