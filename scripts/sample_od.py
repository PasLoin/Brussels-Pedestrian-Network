from __future__ import annotations

import re
import time

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from config import OD_SAMPLE_INTERVAL_M, POINTS_PER_SIDE
from timing import record, step

_AMBIGUITY_RATIO = 1.05

_MIN_EDGE_LENGTH = 0.5


def _extract_house_number(hn) -> int | None:
    m = re.match(r"(\d+)", str(hn))
    return int(m.group(1)) if m else None


def _pick_indices(n: int, k: int) -> list[int]:
    if n == 0:
        return []
    if n < k:
        return [n // 2]
    return [int(n * (i + 1) / (k + 1)) for i in range(k)]


def _principal_axis(coords: np.ndarray) -> np.ndarray:
    if len(coords) < 2:
        return np.array([1.0, 0.0])
    centered = coords - coords.mean(axis=0)
    cov = np.cov(centered.T)
    if cov.ndim < 2:
        return np.array([1.0, 0.0])
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, -1]
    norm = np.linalg.norm(axis)
    return axis / norm if norm > 0 else np.array([1.0, 0.0])


def _sample_side_geographic(
    side_proj: np.ndarray,
    interval_m: float,
    proj_min: float,
    proj_max: float,
) -> list[int]:
    n = len(side_proj)
    if n == 0 or interval_m <= 0:
        return []

    n_bins = max(1, int(np.ceil((proj_max - proj_min) / interval_m)))
    bin_edges = np.linspace(proj_min, proj_max, n_bins + 1)

    selected: list[int] = []
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        bin_center = (lo + hi) / 2

        if i < n_bins - 1:
            mask = (side_proj >= lo) & (side_proj < hi)
        else:
            mask = (side_proj >= lo) & (side_proj <= hi)

        if not mask.any():
            continue

        candidates = np.where(mask)[0]
        dists = np.abs(side_proj[candidates] - bin_center)
        best = candidates[np.argmin(dists)]
        selected.append(int(best))

    return selected


def sample_od_points(
    addresses_path: str = "addresses.geojson",
) -> tuple[list[tuple[float, float]], list[str], list[str], gpd.GeoDataFrame]:
    use_geographic = OD_SAMPLE_INTERVAL_M > 0
    if use_geographic:
        print(f"Sampling OD points (geographic, interval={OD_SAMPLE_INTERVAL_M}m)...")
    else:
        print(f"Sampling OD points (legacy, {POINTS_PER_SIDE} per side)...")

    with step("read_file + to_crs(31370)"):
        addr = gpd.read_file(addresses_path).to_crs("EPSG:31370")

    with step("data prep (centroids + housenumber + filter)"):
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

        addr["_x"] = addr.geometry.x
        addr["_y"] = addr.geometry.y

    od_points: list[tuple[float, float]] = []
    od_streets: list[str] = []
    od_sides: list[str] = []
    streets_both = streets_one = 0

    t_to_numpy = 0.0
    t_axis_project = 0.0
    t_sample_side = 0.0
    t_collect_rows = 0.0

    with step("groupby sampling loop"):
        for street, grp in addr.groupby("addr:street", sort=False):
            if use_geographic:
                _t = time.time()
                xs = grp["_x"].to_numpy()
                ys = grp["_y"].to_numpy()
                nums = grp["_num"].to_numpy()
                t_to_numpy += time.time() - _t

                _t = time.time()
                coords = np.column_stack([xs, ys])
                origin = coords.mean(axis=0)
                axis = _principal_axis(coords)
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

        if use_geographic:
            record("grp[..].to_numpy() per street", t_to_numpy)
            record("principal axis + projection", t_axis_project)
            record("_sample_side_geographic (numpy)", t_sample_side)
            record("collect rows (numpy index + append)", t_collect_rows)

    print(f"  OD points: {len(od_points)}")
    print(f"  Streets both sides: {streets_both} | one side: {streets_one}")
    return od_points, od_streets, od_sides, addr


def snap_to_graph(
    od_points: list[tuple[float, float]],
    node_list: list,
    nodes_gdf: gpd.GeoDataFrame,
    edge_tuples: list[tuple[int, int]],
    edge_geoms: list,
    vertex_mask: np.ndarray | None = None,
    max_snap_m: float | None = None,
) -> tuple[list[int], dict]:
    print("Snapping OD points to graph edges...")

    node_xy = np.column_stack([
        nodes_gdf.loc[node_list, "x"].to_numpy(dtype=np.float64),
        nodes_gdf.loc[node_list, "y"].to_numpy(dtype=np.float64),
    ])
    n_nodes = len(node_xy)
    allowed = (
        np.ones(n_nodes, dtype=bool) if vertex_mask is None
        else np.asarray(vertex_mask, dtype=bool)
    )

    with step("STRtree build (nodes + edges)"):
        allowed_nodes = np.flatnonzero(allowed)
        node_tree = STRtree([Point(node_xy[i]) for i in allowed_nodes])

        valid_edge_indices: list[int] = []
        valid_edge_geoms: list = []
        other_edge_geoms: list = []
        for eid, geom in enumerate(edge_geoms):
            if geom is None or geom.is_empty:
                continue
            if geom.length < _MIN_EDGE_LENGTH:
                continue
            u, v = edge_tuples[eid]
            if allowed[u] and allowed[v]:
                valid_edge_indices.append(eid)
                valid_edge_geoms.append(geom)
            else:
                other_edge_geoms.append(geom)

        edge_tree = STRtree(valid_edge_geoms)
        other_tree = STRtree(other_edge_geoms) if other_edge_geoms else None
    print(f"  Valid edges for snapping: {len(valid_edge_indices)} "
          f"/ {len(edge_geoms)} total "
          f"(outside main network: {len(other_edge_geoms)})")

    src_xy = np.array([
        node_xy[edge_tuples[eid][0]] for eid in valid_edge_indices
    ])
    tgt_xy = np.array([
        node_xy[edge_tuples[eid][1]] for eid in valid_edge_indices
    ])

    snapped: list[int] = []
    n_edge_snapped = 0
    n_fallback = 0
    n_redirected = 0
    n_too_far = 0

    with step("snap loop (Python per-point)"):
        for x, y in od_points:
            pt = Point(x, y)

            nearest_valid_idx = edge_tree.nearest(pt)
            nearest_geom = valid_edge_geoms[nearest_valid_idx]
            best_dist = nearest_geom.distance(pt)

            if max_snap_m is not None and best_dist > max_snap_m:
                snapped.append(-1)
                n_too_far += 1
                continue

            if other_tree is not None:
                other_idx = other_tree.nearest(pt)
                if other_edge_geoms[other_idx].distance(pt) < best_dist:
                    n_redirected += 1

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
                snapped.append(int(allowed_nodes[node_tree.nearest(pt)]))
                n_fallback += 1
                continue

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
    print(f"  Redirected from an island to the main network: {n_redirected} | "
          f"Dropped (> {max_snap_m} m from main network): {n_too_far}")
    return snapped, {
        "points_redirected_from_islands": n_redirected,
        "points_dropped_too_far": n_too_far,
        "points_fallback_nearest_node": n_fallback,
    }
