from __future__ import annotations

import math
import os

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import Point
from shapely.strtree import STRtree

from timing import step

# ── Module-level config ─────────────────────────────────────────────────────

# tactile_paving values on the crossing node this check applies to.
# Anything else (contrasted, primitive, ...) is out of scope and skipped. ##todo include on scope after checking bxl data
_IN_SCOPE_VALUES = frozenset({"yes", "no", "incorrect"})

# Tolerances (m)
TACTILE_PAVING_WAY_MATCH_M = float(os.environ.get("TACTILE_PAVING_WAY_MATCH_M", 0.5))
TACTILE_PAVING_KERB_MATCH_M = float(os.environ.get("TACTILE_PAVING_KERB_MATCH_M", 0.5))


# ── String helper ────────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


def _safe_id(val) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


# ── Data loaders ─────────────────────────────────────────────────────────────

def _load_crossing_nodes(highways_path: str) -> gpd.GeoDataFrame:
    """highway=crossing points with an in-scope tactile_paving value."""
    gdf = gpd.read_file(highways_path)
    gdf = gdf[gdf.geometry.geom_type == "Point"].copy()
    for col in ("highway", "tactile_paving"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "crossing") &
        (gdf["tactile_paving"].apply(_safe_str).isin(_IN_SCOPE_VALUES))
    )
    gdf = gdf[mask].copy()
    gdf["tactile_paving"] = gdf["tactile_paving"].apply(_safe_str)
    gdf["osm_id"] = gdf["@id"].apply(_safe_id)
    return gdf.to_crs("EPSG:31370").reset_index(drop=True)


def _load_crossing_ways(
    footways_path: str,
) -> tuple[gpd.GeoDataFrame, STRtree | None, list, list]:

    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (gdf["footway"].apply(_safe_str) == "crossing")
    )
    gdf = gdf[mask].reset_index(drop=True)

    vertex_points: list[Point] = []
    vertex_way_idx: list[int] = []
    for w_idx, geom in enumerate(gdf.geometry):
        for coord in geom.coords:
            vertex_points.append(Point(coord))
            vertex_way_idx.append(w_idx)

    vertex_tree = STRtree(vertex_points) if vertex_points else None
    return gdf, vertex_tree, vertex_points, vertex_way_idx


def _crossing_points_from(gdf: gpd.GeoDataFrame) -> tuple[list, list, STRtree | None]:
    gdf = gdf[gdf.geometry.geom_type == "Point"].copy()
    for col in ("highway", "tactile_paving"):
        if col not in gdf.columns:
            gdf[col] = ""
    gdf = gdf[gdf["highway"].apply(_safe_str) == "crossing"]
    if gdf.empty:
        return [], [], None
    gdf = gdf.to_crs("EPSG:31370")
    geoms = list(gdf.geometry)
    tps = list(gdf["tactile_paving"].apply(_safe_str))
    return geoms, tps, STRtree(geoms)


def _other_way_vertices_near(
    sources, crossing_way_ids: set, targets: list, tol_m: float,
) -> tuple[list, STRtree | None]:
    if not targets:
        return [], None
    target_tree = STRtree(targets)
    kept: list[Point] = []
    for src in sources:
        if isinstance(src, str):
            if not src or not os.path.exists(src):
                continue
            gdf = gpd.read_file(src)
        else:
            gdf = src
        gdf = gdf[gdf.geometry.geom_type == "LineString"].copy()
        if gdf.empty:
            continue
        for col in ("highway", "footway"):
            if col not in gdf.columns:
                gdf[col] = ""
        if "@id" not in gdf.columns:
            gdf["@id"] = 0
        is_crossing = (
            (gdf["highway"].apply(_safe_str) == "footway") &
            (gdf["footway"].apply(_safe_str) == "crossing")
        )
        known = gdf["@id"].apply(_safe_id).isin(crossing_way_ids)
        gdf = gdf[~is_crossing & ~known].to_crs("EPSG:31370")
        if gdf.empty:
            continue
        pts = shapely.points(shapely.get_coordinates(gdf.geometry.values))
        hit_idx, _ = target_tree.query(pts, predicate="dwithin", distance=tol_m)
        kept.extend(pts[np.unique(hit_idx)])
    return kept, (STRtree(kept) if kept else None)


def _any_within(pt: Point, tree: STRtree | None, geoms: list, tol_m: float) -> bool:
    if tree is None:
        return False
    return any(geoms[i].distance(pt) <= tol_m for i in tree.query(pt.buffer(tol_m)))


class _ContiguousPairs:

    def __init__(
        self, way_gdf, vertex_tree, vertex_points, vertex_way_idx,
        kerb_tree, kerb_geoms, xing_tree, xing_geoms, xing_tps,
        other_tree, other_geoms,
    ):
        self.way_gdf = way_gdf
        self.vertex_tree = vertex_tree
        self.vertex_points = vertex_points
        self.vertex_way_idx = vertex_way_idx
        self.kerb_tree = kerb_tree
        self.kerb_geoms = kerb_geoms
        self.xing_tree = xing_tree
        self.xing_geoms = xing_geoms
        self.xing_tps = xing_tps
        self.other_tree = other_tree
        self.other_geoms = other_geoms
        self.tol = TACTILE_PAVING_WAY_MATCH_M

    def _ends(self, w_idx: int) -> tuple[Point, Point]:
        coords = self.way_gdf.geometry.iloc[w_idx].coords
        return Point(coords[0]), Point(coords[-1])

    def partner(self, w_idx: int, end_pt: Point) -> int | None:
        if self.vertex_tree is None:
            return None
        if _any_within(end_pt, self.kerb_tree, self.kerb_geoms, TACTILE_PAVING_KERB_MATCH_M):
            return None
        if _any_within(end_pt, self.xing_tree, self.xing_geoms, self.tol):
            return None
        if _any_within(end_pt, self.other_tree, self.other_geoms, self.tol):
            return None
        ways_here = {
            self.vertex_way_idx[i]
            for i in self.vertex_tree.query(end_pt.buffer(self.tol))
            if self.vertex_points[i].distance(end_pt) <= self.tol
        }
        others = ways_here - {w_idx}
        if len(others) != 1:
            return None
        w2 = next(iter(others))
        a, b = self._ends(w2)
        if a.distance(end_pt) > self.tol and b.distance(end_pt) > self.tol:
            return None
        if a.distance(end_pt) <= self.tol and b.distance(end_pt) <= self.tol:
            return None
        return w2

    def resolve(self, w_idx: int, end_pt: Point) -> tuple[Point | None, int | None]:
        w2 = self.partner(w_idx, end_pt)
        if w2 is None:
            return end_pt, None
        a, b = self._ends(w2)
        far = b if a.distance(end_pt) <= self.tol else a
        if self.partner(w2, far) is not None:
            return end_pt, None
        if _any_within(far, self.xing_tree, self.xing_geoms, self.tol):
            return None, w2
        return far, w2

    def partner_crossing_tps(self, w2: int) -> set:
        if self.xing_tree is None:
            return set()
        tps = set()
        for coord in self.way_gdf.geometry.iloc[w2].coords:
            pt = Point(coord)
            for i in self.xing_tree.query(pt.buffer(self.tol)):
                if self.xing_geoms[i].distance(pt) <= self.tol and self.xing_tps[i]:
                    tps.add(self.xing_tps[i])
        return tps


def _load_kerb_nodes(
    kerbs_path: str,
) -> tuple[gpd.GeoDataFrame, list, STRtree | None]:
    """barrier=kerb points, with tactile_paving (may be absent/empty)."""
    try:
        gdf = gpd.read_file(kerbs_path)
    except Exception as e:
        print(f"  {kerbs_path} not available: {e}")
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:31370"), [], None
    gdf = gdf[gdf.geometry.geom_type == "Point"].copy()
    for col in ("barrier", "tactile_paving"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = gdf["barrier"].apply(_safe_str) == "kerb"
    gdf = gdf[mask].copy()
    gdf["tactile_paving"] = gdf["tactile_paving"].apply(_safe_str)
    gdf["osm_id"] = gdf["@id"].apply(_safe_id)
    gdf = gdf.to_crs("EPSG:31370").reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, (STRtree(geoms) if geoms else None)


# ── Matching helpers ─────────────────────────────────────────────────────────

def _nearest_within(pt: Point, tree: STRtree | None, geoms: list, tol_m: float):
    """Index into *geoms* of the nearest candidate to *pt* within *tol_m*,
    or None if nothing is close enough."""
    if tree is None:
        return None
    zone = pt.buffer(tol_m)
    cands = list(tree.query(zone))
    if not cands:
        return None
    return min(cands, key=lambda i: geoms[i].distance(pt))


def _match_crossing_way(
    node_pt: Point,
    vertex_tree: STRtree | None,
    vertex_points: list,
    vertex_way_idx: list,
    tol_m: float,
) -> tuple[int | None, bool]:

    if vertex_tree is None:
        return None, False
    zone = node_pt.buffer(tol_m)
    cand_idxs = list(vertex_tree.query(zone))
    if not cand_idxs:
        return None, False
    best = min(cand_idxs, key=lambda i: vertex_points[i].distance(node_pt))
    distinct_ways = {vertex_way_idx[i] for i in cand_idxs}
    return vertex_way_idx[best], len(distinct_ways) > 1


def _kerb_tp_at(
    endpoint: Point, kerb_gdf: gpd.GeoDataFrame,
    kerb_tree: STRtree | None, kerb_geoms: list,
) -> tuple[str | None, int]:
    """Return (tactile_paving value or None if no kerb matched, osm_id)."""
    idx = _nearest_within(endpoint, kerb_tree, kerb_geoms, TACTILE_PAVING_KERB_MATCH_M)
    if idx is None:
        return None, 0
    row = kerb_gdf.iloc[idx]
    tp = row["tactile_paving"] or ""
    return (tp if tp else ""), int(row["osm_id"])


def _is_footway_crossing(way_row) -> bool:

    return (
        _safe_str(way_row.get("highway")) == "footway" and
        _safe_str(way_row.get("footway")) == "crossing"
    )


def _classify(crossing_tp: str, tp1: str | None, tp2: str | None) -> str | None:

    if tp1 is None or tp2 is None:
        return "kerb_missing"
    if tp1 == "" or tp2 == "":
        return "kerb_untagged"
    if crossing_tp in ("yes", "no"):
        if tp1 != crossing_tp or tp2 != crossing_tp:
            return "value_mismatch"
        return None
    # crossing_tp == "incorrect" — expect exactly one yes + one no.
    if {tp1, tp2} != {"yes", "no"}:
        return "incorrect_not_mixed"
    return None


def _classify_single(crossing_tp: str, tp: str | None) -> str | None:

    assert crossing_tp in ("yes", "no"), (
        "incorrect_not_mixed can't be evaluated from a single side"
    )
    if tp is None:
        return "kerb_missing"
    if tp == "":
        return "kerb_untagged"
    if tp != crossing_tp:
        return "value_mismatch"
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def detect_tactile_paving_issues(
    highways_geojson_path: str = "highways.geojson",
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    kerbs_geojson_path:    str = "kerbs_raw.geojson",
    other_ways_geojson_paths: tuple = (),
) -> dict:
    """Detect tactile_paving incoherences between crossing nodes and the
    kerb nodes at each end of their attached footway=crossing way.

    Returns a statistics dict for stats.json.
    """
    print("Detecting tactile_paving incoherences (crossing ↔ kerb)...")
    print(
        f"  Way match tolerance: {TACTILE_PAVING_WAY_MATCH_M} m | "
        f"Kerb match tolerance: {TACTILE_PAVING_KERB_MATCH_M} m"
    )

    with step("load crossing nodes with tactile_paving"):
        crossing_gdf = _load_crossing_nodes(highways_geojson_path)
    print(f"  highway=crossing nodes with in-scope tactile_paving "
          f"(yes/no/incorrect): {len(crossing_gdf)}")

    if crossing_gdf.empty:
        print("  Nothing to analyse — skipping.")
        _write_empty_output()
        _write_empty_kerb_issues_output()
        return {"crossings_in_scope": 0, "flagged": 0}

    with step("load footway=crossing ways"):
        way_gdf, vertex_tree, vertex_points, vertex_way_idx = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways: {len(way_gdf)} ({len(vertex_points)} vertices indexed)")

    with step("load kerb nodes"):
        kerb_gdf, kerb_geoms, kerb_tree = _load_kerb_nodes(kerbs_geojson_path)
    print(f"  barrier=kerb nodes: {len(kerb_gdf)}")

    with step("index contiguous footway=crossing pairs"):
        highways_gdf = gpd.read_file(highways_geojson_path)
        xing_geoms, xing_tps, xing_tree = _crossing_points_from(highways_gdf)
        crossing_way_ids = {i for i in way_gdf["@id"].apply(_safe_id) if i}
        way_ends = [
            Point(c)
            for geom in way_gdf.geometry
            for c in (geom.coords[0], geom.coords[-1])
        ]
        other_geoms, other_tree = _other_way_vertices_near(
            (highways_gdf, footways_geojson_path, *other_ways_geojson_paths),
            crossing_way_ids, way_ends, TACTILE_PAVING_WAY_MATCH_M,
        )
        del highways_gdf
        pairs = _ContiguousPairs(
            way_gdf, vertex_tree, vertex_points, vertex_way_idx,
            kerb_tree, kerb_geoms, xing_tree, xing_geoms, xing_tps,
            other_tree, other_geoms,
        )
    print(f"  Other-way vertices indexed for junction test: {len(other_geoms)}")

    rows: list[dict] = []
    kerb_issue_rows: list[dict] = []
    n_no_way          = 0
    n_ambiguous_way    = 0
    n_degenerate_way   = 0
    n_half_mapped_sides = 0
    n_half_mapped_incorrect_skipped = 0
    n_kerb_missing     = 0
    n_kerb_untagged    = 0
    n_kerb_missing_points  = 0
    n_kerb_untagged_points = 0
    n_value_mismatch   = 0
    n_incorrect_mixed  = 0
    n_ok               = 0
    n_contiguous_sides = 0
    n_contiguous_conflict = 0
    emitted_pair_points: set = set()

    def _pair_point_seen(kind, pt, way_a, way_b):
        if not way_b:
            return False
        key = (kind, frozenset((way_a, way_b)), round(pt.x, 1), round(pt.y, 1))
        if key in emitted_pair_points:
            return True
        emitted_pair_points.add(key)
        return False

    with step("crossing/kerb coherence loop"):
        for _, node_row in crossing_gdf.iterrows():
            node_pt = node_row.geometry
            crossing_tp = node_row["tactile_paving"]

            way_idx, ambiguous = _match_crossing_way(
                node_pt, vertex_tree, vertex_points, vertex_way_idx,
                TACTILE_PAVING_WAY_MATCH_M,
            )
            if way_idx is None:
                n_no_way += 1
                continue
            if ambiguous:
                # More than one footway=crossing way has a vertex here —
                # can't be sure which one actually owns this crossing
                # node, so don't guess (that's exactly the kind of false
                # match this check exists to avoid).
                n_ambiguous_way += 1
                continue

            way_row = way_gdf.iloc[way_idx]

            if not _is_footway_crossing(way_row):
                n_no_way += 1
                continue

            way_geom = way_row.geometry
            p1 = Point(way_geom.coords[0])
            p2 = Point(way_geom.coords[-1])
            own_wid = _safe_id(way_row.get("@id"))
            partner_wid = 0

            p1_is_crossing_node = p1.distance(node_pt) <= TACTILE_PAVING_WAY_MATCH_M
            p2_is_crossing_node = p2.distance(node_pt) <= TACTILE_PAVING_WAY_MATCH_M

            if p1_is_crossing_node and p2_is_crossing_node:
                # Degenerate way (e.g. a zero-length or duplicate-point
                # way) — neither "extremity" is a real position at all.
                n_degenerate_way += 1
                continue

            partner_idx = None
            single_pt = None
            if p1_is_crossing_node or p2_is_crossing_node:
                single_pt = p2 if p1_is_crossing_node else p1
                q, w2 = pairs.resolve(way_idx, single_pt)
                if w2 is not None and q is not None:
                    single_pt, partner_idx = q, w2
            else:
                junction1 = pairs.partner(way_idx, p1) is not None
                junction2 = pairs.partner(way_idx, p2) is not None
                if junction1 != junction2:
                    q, w2 = pairs.resolve(way_idx, p1 if junction1 else p2)
                    if w2 is not None:
                        partner_idx = w2
                        if q is None:
                            single_pt = p2 if junction1 else p1
                        elif junction1:
                            p1 = q
                        else:
                            p2 = q

            if single_pt is not None and crossing_tp == "incorrect":
                # Half-mapped crossing: only the OTHER endpoint is a
                # genuine kerb position. "incorrect" describes a yes/no
                # PAIR and can't be evaluated from a single side, so
                # skip it entirely rather than guess.
                n_half_mapped_incorrect_skipped += 1
                continue

            if partner_idx is not None:
                if pairs.partner_crossing_tps(partner_idx) - {crossing_tp}:
                    n_contiguous_conflict += 1
                    continue
                partner_wid = _safe_id(way_gdf.iloc[partner_idx].get("@id"))
                n_contiguous_sides += 1

            if single_pt is not None:
                n_half_mapped_sides += 1
                pt = single_pt

                tp, kerb_id = _kerb_tp_at(pt, kerb_gdf, kerb_tree, kerb_geoms)

                reason = _classify_single(crossing_tp, tp)
                if reason is None:
                    n_ok += 1
                    continue

                if reason == "kerb_missing":
                    n_kerb_missing += 1
                    if not _pair_point_seen("kerb_missing", pt, own_wid, partner_wid):
                        n_kerb_missing_points += 1
                        kerb_issue_rows.append({
                            "geometry":           pt,
                            "type":               "kerb_missing",
                            "crossing_osm_id":    int(node_row["osm_id"]),
                            "way_osm_id":         own_wid,
                            "partner_way_osm_id": partner_wid,
                            "kerb_osm_id":        0,
                        })
                    continue
                elif reason == "kerb_untagged":
                    n_kerb_untagged += 1
                    if not _pair_point_seen("kerb_untagged", pt, own_wid, partner_wid):
                        n_kerb_untagged_points += 1
                        kerb_issue_rows.append({
                            "geometry":           pt,
                            "type":               "kerb_untagged",
                            "crossing_osm_id":    int(node_row["osm_id"]),
                            "way_osm_id":         own_wid,
                            "partner_way_osm_id": partner_wid,
                            "kerb_osm_id":        kerb_id,
                        })
                    continue
                else:
                    # value_mismatch — incorrect_not_mixed can never
                    # come back here, guarded above.
                    n_value_mismatch += 1

                rows.append({
                    "geometry":      node_pt,
                    "osm_id":        int(node_row["osm_id"]),
                    "way_osm_id":    own_wid,
                    "partner_way_osm_id": partner_wid,
                    "crossing_tp":   crossing_tp,
                    "sides_checked": 1,
                    "kerb1_tp":      tp or "",
                    "kerb1_osm_id":  kerb_id,
                    "kerb2_tp":      "",
                    "kerb2_osm_id":  0,
                    "reason":        reason,
                })
                continue

            # Normal case (unchanged): the crossing node is a genuine
            # middle vertex, both endpoints are real kerb positions.
            tp1, kerb1_id = _kerb_tp_at(p1, kerb_gdf, kerb_tree, kerb_geoms)
            tp2, kerb2_id = _kerb_tp_at(p2, kerb_gdf, kerb_tree, kerb_geoms)

            reason = _classify(crossing_tp, tp1, tp2)
            if reason is None:
                n_ok += 1
                continue

            if reason == "kerb_missing":
                n_kerb_missing += 1
                # One point per extremity that has no matched kerb node
                # at all — located at the way's endpoint (the "expected"
                # kerb position), since there's no real kerb to point to.
                for pt, tp in ((p1, tp1), (p2, tp2)):
                    if tp is None and not _pair_point_seen("kerb_missing", pt, own_wid, partner_wid):
                        n_kerb_missing_points += 1
                        kerb_issue_rows.append({
                            "geometry":           pt,
                            "type":               "kerb_missing",
                            "crossing_osm_id":    int(node_row["osm_id"]),
                            "way_osm_id":         own_wid,
                            "partner_way_osm_id": partner_wid,
                            "kerb_osm_id":        0,
                        })
                continue
            elif reason == "kerb_untagged":
                n_kerb_untagged += 1
                # One point per extremity whose matched kerb node has no
                # tactile_paving value at all.
                for pt, tp, kid in ((p1, tp1, kerb1_id), (p2, tp2, kerb2_id)):
                    if tp == "" and not _pair_point_seen("kerb_untagged", pt, own_wid, partner_wid):
                        n_kerb_untagged_points += 1
                        kerb_issue_rows.append({
                            "geometry":           pt,
                            "type":               "kerb_untagged",
                            "crossing_osm_id":    int(node_row["osm_id"]),
                            "way_osm_id":         own_wid,
                            "partner_way_osm_id": partner_wid,
                            "kerb_osm_id":        kid,
                        })
                continue
            elif reason == "value_mismatch":
                n_value_mismatch += 1
            else:
                n_incorrect_mixed += 1

            rows.append({
                "geometry":      node_pt,
                "osm_id":        int(node_row["osm_id"]),
                "way_osm_id":    own_wid,
                "partner_way_osm_id": partner_wid,
                "crossing_tp":   crossing_tp,
                "sides_checked": 2,
                "kerb1_tp":      tp1 or "",
                "kerb1_osm_id":  kerb1_id,
                "kerb2_tp":      tp2 or "",
                "kerb2_osm_id":  kerb2_id,
                "reason":        reason,
            })

    with step("write tactile_paving_issues.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = _empty_gdf()
        out_gdf.to_file("tactile_paving_issues.geojson", driver="GeoJSON")

    with step("write kerb_issues.geojson"):
        if kerb_issue_rows:
            kerb_out_gdf = gpd.GeoDataFrame(kerb_issue_rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            kerb_out_gdf = _empty_kerb_issues_gdf()
        kerb_out_gdf.to_file("kerb_issues.geojson", driver="GeoJSON")

    n_total = len(crossing_gdf)
    n_flagged = len(rows)
    print(f"  Crossings in scope (yes/no/incorrect):     {n_total}")
    print(f"  Skipped — no footway=crossing way found:   {n_no_way}")
    print(f"  Skipped — ambiguous way match (≥2 ways):   {n_ambiguous_way}")
    print(f"  Skipped — degenerate way:                  {n_degenerate_way} (both endpoints == crossing node)")
    print(f"  Half-mapped — one side only checked:       {n_half_mapped_sides}")
    print(f"  Skipped — half-mapped incorrect crossing:  {n_half_mapped_incorrect_skipped} (needs both sides)")
    print(f"  Contiguous crossing pairs — merged sides:  {n_contiguous_sides}")
    print(f"  Skipped — contiguous pair tp conflict:     {n_contiguous_conflict}")
    print(f"  Coherent (not flagged):                    {n_ok}")
    print(f"  Skipped — kerb missing at an extremity:    {n_kerb_missing} (data gap, not flagged — see kerb_issues.geojson)")
    print(f"  Skipped — kerb without tactile_paving:     {n_kerb_untagged} (data gap, not flagged — see kerb_issues.geojson)")
    print(f"  Kerb-issue points — kerb absent:            {n_kerb_missing_points}")
    print(f"  Kerb-issue points — kerb sans tactile_paving:{n_kerb_untagged_points}")
    print(f"  Flagged — kerb value mismatch:              {n_value_mismatch}")
    print(f"  Flagged — incorrect not a yes/no pair:       {n_incorrect_mixed}")
    print(f"  Total flagged:                              {n_flagged}")

    return {
        "crossings_in_scope":              n_total,
        "no_crossing_way_found":           n_no_way,
        "ambiguous_way_match":             n_ambiguous_way,
        "degenerate_way":                  n_degenerate_way,
        "half_mapped_sides":               n_half_mapped_sides,
        "half_mapped_incorrect_skipped":   n_half_mapped_incorrect_skipped,
        "contiguous_pair_merged":          n_contiguous_sides,
        "contiguous_pair_tp_conflict":     n_contiguous_conflict,
        "coherent":                        n_ok,
        "kerb_missing":                    n_kerb_missing,
        "kerb_untagged":                   n_kerb_untagged,
        "kerb_missing_points":             n_kerb_missing_points,
        "kerb_untagged_points":            n_kerb_untagged_points,
        "value_mismatch":                  n_value_mismatch,
        "incorrect_not_mixed":             n_incorrect_mixed,
        "flagged":                         n_flagged,
    }


def _empty_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"geometry": None, "osm_id": 0, "way_osm_id": 0,
          "partner_way_osm_id": 0,
          "crossing_tp": "", "sides_checked": 0,
          "kerb1_tp": "", "kerb1_osm_id": 0,
          "kerb2_tp": "", "kerb2_osm_id": 0, "reason": ""}],
        crs="EPSG:4326",
    )


def _write_empty_output() -> None:
    _empty_gdf().to_file("tactile_paving_issues.geojson", driver="GeoJSON")


def _empty_kerb_issues_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"geometry": None, "type": "", "crossing_osm_id": 0,
          "way_osm_id": 0, "partner_way_osm_id": 0, "kerb_osm_id": 0}],
        crs="EPSG:4326",
    )


def _write_empty_kerb_issues_output() -> None:
    _empty_kerb_issues_gdf().to_file("kerb_issues.geojson", driver="GeoJSON")
