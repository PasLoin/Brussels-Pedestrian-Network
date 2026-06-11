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
import time

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from config import OD_SAMPLE_INTERVAL_M, POINTS_PER_SIDE
from timing import record, step

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
    side_proj: np.ndarray,
    interval_m: float,
    proj_min: float,
    proj_max: float,
) -> list[int]:
    """Pick one index per spatial bin for a single side of the street.

    Pure-NumPy implementation: the caller pre-computes the projection
    of every address on the street's principal axis, and passes the
    slice for one side here.  This avoids both per-side DataFrame
    slicing and redundant projection work.

    Parameters
    ----------
    side_proj : ndarray
        1-D array of axis projections (one per address on this side).
    interval_m : float
        Bin width in metres along the axis.
    proj_min, proj_max : float
        Projection bounds of the *entire* street (both sides combined)
        so that bins are aligned across sides.

    Returns
    -------
    list of positional indices into *side_proj*.
    """
    n = len(side_proj)
    if n == 0 or interval_m <= 0:
        return []

    n_bins = max(1, int(np.ceil((proj_max - proj_min) / interval_m)))
    bin_edges = np.linspace(proj_min, proj_max, n_bins + 1)

    selected: list[int] = []
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        bin_center = (lo + hi) / 2

        # Find addresses in this bin
        if i < n_bins - 1:
            mask = (side_proj >= lo) & (side_proj < hi)
        else:
            # Last bin includes right edge
            mask = (side_proj >= lo) & (side_proj <= hi)

        if not mask.any():
            continue

        # Pick the address closest to bin center
        candidates = np.where(mask)[0]
        dists = np.abs(side_proj[candidates] - bin_center)
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

    with step("read_file + to_crs(31370)"):
        addr = gpd.read_file(addresses_path).to_crs("EPSG:31370")

    with step("data prep (centroids + housenumber + filter)"):
        # ── Vectorised centroid conversion ────────────────────────────────
        n_poly = int((~addr.geometry.geom_type.isin(["Point"])).sum())
        if n_poly > 0:
            addr["geometry"] = addr.geometry.centroid
            print(f"  Converted {n_poly} polygon addresses to centroids")

        addr["_num"] = addr.get("addr:housenumber", "").apply(_extract_house_number)
        addr = addr.dropna(subset=["_num"])
        addr["_num"] = addr["_num"].astype(int)

        if "addr:street" not in addr.columns:
            addr["addr:street"] = ""
        addr = addr[addr["addr:street"].notna()]
        addr = addr[addr["addr:street"].astype(str).str.strip() != ""]

        # ── Pre-extract coordinates as scalar columns ─────────────────────
        # Lets the per-street loop pull NumPy arrays directly without
        # going through Shapely (.x/.y per geometry) or per-side
        # DataFrame slicing.  This is the key to making the loop fast.
        addr["_x"] = addr.geometry.x
        addr["_y"] = addr.geometry.y

    od_points: list[tuple[float, float]] = []
    od_streets: list[str] = []
    od_sides: list[str] = []
    streets_both = streets_one = 0

    # ── Cumulative timers for the loop body ──────────────────────────────
    t_to_numpy = 0.0
    t_axis_project = 0.0
    t_sample_side = 0.0
    t_collect_rows = 0.0

    with step("groupby sampling loop"):
        for street, grp in addr.groupby("addr:street", sort=False):
            if use_geographic:
                # ── Pull NumPy arrays once, work on masks afterwards ──────
                # No more DataFrame slicing per side — that was the 94s
                # bottleneck.  Everything below is NumPy.
                _t = time.time()
                xs = grp["_x"].to_numpy()
                ys = grp["_y"].to_numpy()
                nums = grp["_num"].to_numpy()
                t_to_numpy += time.time() - _t

                _t = time.time()
                coords = np.column_stack([xs, ys])
                origin = coords.mean(axis=0)
                axis = _principal_axis(coords)
                # Project ALL addresses once; slice per side with masks.
                all_proj = (coords - origin) @ axis
                proj_min = float(all_proj.min())
                proj_max = float(all_proj.max())
                t_axis_project += time.time() - _t

                even_mask = (nums % 2 == 0)
                street_str = str(street)

                sides_sampled = 0
                for side_name, mask in (("even", even_mask), ("odd", ~even_mask)):
                    if not mask.any():
                        continue

                    side_xs = xs[mask]
                    side_ys = ys[mask]
                    side_proj = all_proj[mask]

                    _t = time.time()
                    selected = _sample_side_geographic(
                        side_proj, OD_SAMPLE_INTERVAL_M, proj_min, proj_max,
                    )
                    t_sample_side += time.time() - _t
                    if not selected:
                        continue

                    _t = time.time()
                    # NumPy fancy indexing once instead of .iloc[i] per row
                    sel = np.asarray(selected, dtype=np.intp)
                    picked_xs = side_xs[sel]
                    picked_ys = side_ys[sel]
                    for px, py in zip(picked_xs, picked_ys):
                        od_points.append((float(px), float(py)))
                        od_streets.append(street_str)
                        od_sides.append(side_name)
                    t_collect_rows += time.time() - _t
                    sides_sampled += 1

            else:
                # ── Legacy sampling (POINTS_PER_SIDE) ─────────────────────
                # Rarely used (only when OD_SAMPLE_INTERVAL_M=0).  Kept
                # unchanged — uses DataFrame slicing but only runs in
                # the legacy mode.
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

        # ── Report cumulative breakdown (inside the with so the records ──
        # appear nested under "groupby sampling loop").
        if use_geographic:
            record("grp[..].to_numpy() per street", t_to_numpy)
            record("principal axis + projection", t_axis_project)
            record("_sample_side_geographic (numpy)", t_sample_side)
            record("collect rows (numpy index + append)", t_collect_rows)

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
    # Use vectorised .loc lookup over the whole node_list — much faster
    # than a per-node .loc inside a Python comprehension.
    node_xy = np.column_stack([
        nodes_gdf.loc[node_list, "x"].to_numpy(dtype=np.float64),
        nodes_gdf.loc[node_list, "y"].to_numpy(dtype=np.float64),
    ])

    with step("STRtree build (nodes + edges)"):
        node_tree = STRtree([Point(x, y) for x, y in node_xy])

        # ── Build edge spatial index ──────────────────────────────────────
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

    with step("snap loop (Python per-point)"):
        for x, y in od_points:
            pt = Point(x, y)

            nearest_valid_idx = edge_tree.nearest(pt)
            nearest_geom = valid_edge_geoms[nearest_valid_idx]
            best_dist = nearest_geom.distance(pt)

            # ── Ambiguity check ───────────────────────────────────────────
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

            # ── Pick closest endpoint of the winning edge ─────────────────
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
