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
odd house numbers (approximating the two sides of the street).

Each side is sampled independently using a geographic interval:
addresses are projected onto the street's principal axis, then one
point is picked per spatial bin of ``OD_SAMPLE_INTERVAL_M`` metres.
This scales naturally with street length: a 200 m street gets ~2 points
per side, a 1.5 km avenue gets ~15.

Each side is sampled independently, so a bin with 5 houses on one side
and 0 on the other produces a point only on the populated side.

Snapping strategy
-----------------
Each OD point is snapped to the nearest **edge** (point-to-segment
distance) rather than the nearest node.  This correctly handles streets
where a footway is mapped on one side only.

When the nearest-edge result is ambiguous (several edges within a small
tolerance), the function falls back to global nearest-node snapping.
"""

from __future__ import annotations

import re

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from config import OD_SAMPLE_INTERVAL_M, POINTS_PER_SIDE

# Maximum ratio between runner-up and best edge distance to consider
# the result ambiguous.
_AMBIGUITY_RATIO = 1.05

# Edges shorter than this (metres) are considered degenerate.
_MIN_EDGE_LENGTH = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_house_number(hn) -> int | None:
    """Return the leading integer from a house-number string, or None."""
    m = re.match(r"(\d+)", str(hn))
    return int(m.group(1)) if m else None


def _pick_indices(n: int, k: int) -> list[int]:
    """Return *k* evenly-spaced indices into a sequence of length *n*.

    Legacy helper, used only when ``OD_SAMPLE_INTERVAL_M == 0``.
    """
    if n == 0:
        return []
    if n < k:
        return [n // 2]
    return [int(n * (i + 1) / (k + 1)) for i in range(k)]


def _principal_axis(coords: np.ndarray) -> np.ndarray:
    """Return the unit vector along the principal axis of a point cloud.

    Uses the first eigenvector of the 2D covariance matrix.  If all
    points are identical (zero variance), returns ``[1, 0]``.
    """
    if len(coords) < 2:
        return np.array([1.0, 0.0])
    centered = coords - coords.mean(axis=0)
    cov = np.cov(centered.T)
    # cov can be scalar if only 1D variation
    if cov.ndim < 2:
        return np.array([1.0, 0.0])
    eigvals, eigvecs = np.linalg.eigh(cov)
    # eigh returns in ascending order; last eigvec = largest variance
    axis = eigvecs[:, -1]
    norm = np.linalg.norm(axis)
    return axis / norm if norm > 0 else np.array([1.0, 0.0])


def _sample_side_geographic(
    side_grp: gpd.GeoDataFrame,
    axis: np.ndarray,
    origin: np.ndarray,
    interval_m: float,
    proj_min: float,
    proj_max: float,
) -> list[int]:
    """Pick one address per spatial bin for a single side of the street.

    Parameters
    ----------
    side_grp : GeoDataFrame
        Addresses on one side (even or odd), with geometry in EPSG:31370.
    axis : ndarray
        Unit vector along the street's principal axis.
    origin : ndarray
        Reference point (centroid of all addresses on the street).
    interval_m : float
        Bin width in metres along the axis.
    proj_min, proj_max : float
        Projection bounds of the *entire* street (both sides combined)
        so that bins are aligned across sides.

    Returns
    -------
    list of positional indices into *side_grp*.
    """
    if side_grp.empty or interval_m <= 0:
        return []

    coords = np.array([(g.x, g.y) for g in side_grp.geometry])
    projections = (coords - origin) @ axis

    # Build bins covering the full street extent
    n_bins = max(1, int(np.ceil((proj_max - proj_min) / interval_m)))
    bin_edges = np.linspace(proj_min, proj_max, n_bins + 1)

    selected: list[int] = []
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        bin_center = (lo + hi) / 2

        # Find addresses in this bin
        if i < n_bins - 1:
            mask = (projections >= lo) & (projections < hi)
        else:
            # Last bin includes right edge
            mask = (projections >= lo) & (projections <= hi)

        if not mask.any():
            continue

        # Pick the address closest to bin center
        candidates = np.where(mask)[0]
        dists = np.abs(projections[candidates] - bin_center)
        best = candidates[np.argmin(dists)]
        selected.append(int(best))

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# Public — sampling
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
    use_geographic = OD_SAMPLE_INTERVAL_M > 0
    if use_geographic:
        print(f"Sampling OD points (geographic, interval={OD_SAMPLE_INTERVAL_M}m)...")
    else:
        print(f"Sampling OD points (legacy, {POINTS_PER_SIDE} per side)...")

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
        if use_geographic:
            # ── Geographic sampling ───────────────────────────────────────
            all_coords = np.array([(g.x, g.y) for g in grp.geometry])
            origin = all_coords.mean(axis=0)
            axis = _principal_axis(all_coords)

            # Project all addresses to get global min/max
            all_proj = (all_coords - origin) @ axis
            proj_min = float(all_proj.min())
            proj_max = float(all_proj.max())

            sides_sampled = 0
            for side_name, side_grp in [
                ("even", grp[grp["_num"] % 2 == 0]),
                ("odd", grp[grp["_num"] % 2 == 1]),
            ]:
                if side_grp.empty:
                    continue
                selected = _sample_side_geographic(
                    side_grp, axis, origin,
                    OD_SAMPLE_INTERVAL_M, proj_min, proj_max,
                )
                if not selected:
                    continue
                for i in selected:
                    row = side_grp.iloc[i]
                    od_points.append((row.geometry.x, row.geometry.y))
                    od_streets.append(str(street))
                    od_sides.append(side_name)
                sides_sampled += 1

        else:
            # ── Legacy sampling (POINTS_PER_SIDE) ─────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Public — snapping
# ─────────────────────────────────────────────────────────────────────────────

def snap_to_graph(
    od_points: list[tuple[float, float]],
    node_list: list,
    nodes_gdf: gpd.GeoDataFrame,
    edge_tuples: list[tuple[int, int]],
    edge_geoms: list,
) -> list[int]:
    """Snap each OD point to the nearest graph edge, then to the
    closest endpoint of that edge.

    Parameters
    ----------
    od_points : list of (x, y)
        Coordinates in EPSG:31370.
    node_list : list
        Ordered OSM node ids (index = graph vertex index).
    nodes_gdf : GeoDataFrame
        Projected node geometries.
    edge_tuples : list of (src_idx, tgt_idx)
        Graph vertex indices for each edge.
    edge_geoms : list
        Shapely geometries (projected) for each edge.

    Returns
    -------
    snapped : list of int
        Graph vertex index for each OD point.
    """
    print("Snapping OD points to graph edges...")

    # ── Build node coordinate array (for fallback) ────────────────────────
    node_xy = np.array([
        [nodes_gdf.loc[n, "x"], nodes_gdf.loc[n, "y"]]
        for n in node_list
    ])
    node_tree = STRtree([Point(x, y) for x, y in node_xy])

    # ── Build edge spatial index ──────────────────────────────────────────
    valid_edge_indices: list[int] = []
    valid_edge_geoms: list = []
    for eid, geom in enumerate(edge_geoms):
        if geom is None or geom.is_empty:
            continue
        if geom.length < _MIN_EDGE_LENGTH:
            continue
        valid_edge_indices.append(eid)
        valid_edge_geoms.append(geom)

    edge_tree = STRtree(valid_edge_geoms)
    print(f"  Valid edges for snapping: {len(valid_edge_indices)} "
          f"/ {len(edge_geoms)} total")

    # ── Precompute endpoint coordinates per valid edge ────────────────────
    src_xy = np.array([
        node_xy[edge_tuples[eid][0]] for eid in valid_edge_indices
    ])
    tgt_xy = np.array([
        node_xy[edge_tuples[eid][1]] for eid in valid_edge_indices
    ])

    # ── Snap each point ───────────────────────────────────────────────────
    snapped: list[int] = []
    n_edge_snapped = 0
    n_fallback = 0

    for x, y in od_points:
        pt = Point(x, y)

        nearest_valid_idx = edge_tree.nearest(pt)
        nearest_geom = valid_edge_geoms[nearest_valid_idx]
        best_dist = nearest_geom.distance(pt)

        # ── Ambiguity check ───────────────────────────────────────────────
        use_fallback = False
        if best_dist > 0:
            search_dist = best_dist * _AMBIGUITY_RATIO
            candidate_indices = edge_tree.query(pt.buffer(search_dist))
            n_tied = sum(
                1 for ci in candidate_indices
                if valid_edge_geoms[ci].distance(pt) <= search_dist
            )
            if n_tied > 2:
                use_fallback = True

        if use_fallback:
            snapped.append(int(node_tree.nearest(pt)))
            n_fallback += 1
            continue

        # ── Pick closest endpoint of the winning edge ─────────────────────
        sx, sy = src_xy[nearest_valid_idx]
        tx, ty = tgt_xy[nearest_valid_idx]
        d_src = (x - sx) ** 2 + (y - sy) ** 2
        d_tgt = (x - tx) ** 2 + (y - ty) ** 2

        real_eid = valid_edge_indices[nearest_valid_idx]
        if d_src <= d_tgt:
            snapped.append(edge_tuples[real_eid][0])
        else:
            snapped.append(edge_tuples[real_eid][1])
        n_edge_snapped += 1

    print(f"  Edge-snapped: {n_edge_snapped} | "
          f"Fallback (nearest node): {n_fallback}")
    return snapped
