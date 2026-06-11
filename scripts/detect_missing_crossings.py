"""
Detect highway=crossing nodes that are missing a corresponding crossing way.

A ``highway=crossing`` node on a road records a pedestrian crossing location
but does not guarantee that the corresponding crossing **way**
(``highway=footway`` + ``footway=crossing``) has been mapped.  Without the
way, walkers have no routable path across the road at that point — the router
silently falls back to the road surface and no flow break appears.

Detection heuristic
-------------------
For each ``highway=crossing`` node located on an eligible road:

1. **Crossing-way check** — if a ``footway=crossing`` way already exists
   within ``CROSSING_WAY_SEARCH_RADIUS_M``, the crossing is mapped → skip.

2. **Sidewalk presence check** — at the node's exact position on the road,
   compute the perpendicular direction and build two small circular search
   zones — one on each side of the road.  Check whether any
   ``footway=sidewalk`` way intersects each zone.

   Only ``footway=sidewalk`` is accepted as evidence — NOT
   ``footway=link``, ``footway=crossing``, or ``highway=pedestrian``.
   Using the broader set (as ``sidewalk_gap._load_sidewalk_footways``
   does) produces systematic false positives: ``footway=crossing`` ways
   at nearby intersections often run parallel to the road being tested
   and falsely satisfy the sidewalk check even when no sidewalk is drawn.

3. Flag if **both** sides have a sidewalk AND no crossing way exists.

Why not the parallel-coverage approach from sidewalk_gap?
---------------------------------------------------------
sidewalk_gap checks coverage along a full road segment.  Here we care
only about the *point* where the crossing node sits.  A simple presence
query in a perpendicular zone at that point is more precise and avoids
the false-positive path described above.

Inputs
------
* ``highways.geojson`` — slimmed pedestrian layer (crossing nodes as
  Point features with ``highway=crossing``).
* ``sidewalk_footways_raw.geojson`` — raw osmium footway export.
* ``sidewalk_roads_raw.geojson`` — raw osmium road export.

Output
------
``missing_crossings.geojson`` — point layer, one feature per detected
missing crossing way, with properties ``name``, ``left``, ``right``
(boolean sidewalk presence on each side).
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

# Road types eligible for crossing analysis.
_CROSSING_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}

# Minimum road segment length to process (metres).
_MIN_ROAD_LENGTH = 15.0


# ── Module-level config ───────────────────────────────────────────────────────

# Max distance from crossing node to nearest eligible road centre (metres).
CROSSING_NODE_ROAD_SEARCH_M = float(os.environ.get("CROSSING_NODE_ROAD_SEARCH_M", 20.0))

# Distance from road centreline to the centre of each sidewalk search zone.
# Matches SIDEWALK_GAP_OFFSET_M so both layers use consistent geometry.
CROSSING_SIDEWALK_OFFSET_M = float(os.environ.get("CROSSING_SIDEWALK_OFFSET_M", 7.0))

# Radius of the circular search zone on each side of the road.
# Generous enough to catch sidewalks offset 1–15 m from the road edge.
CROSSING_SIDEWALK_SEARCH_M = float(os.environ.get("CROSSING_SIDEWALK_SEARCH_M", 15.0))

# If a footway=crossing way exists within this radius of the node, skip it.
CROSSING_WAY_SEARCH_RADIUS_M = float(os.environ.get("CROSSING_WAY_SEARCH_RADIUS_M", 20.0))


# ─────────────────────────────────────────────────────────────────────────────
# String normalisation (self-contained, no sidewalk_gap import needed)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    """Normalise a GeoJSON property value to a lowercase string."""
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────

def _load_crossing_nodes(highways_path: str) -> gpd.GeoDataFrame:
    """Read highway=crossing *point* features from the pedestrian layer.

    Uses stdlib ``json`` instead of ``gpd.read_file`` because:

    * ``highways.geojson`` mixes Point and LineString geometries — some
      pyogrio/OGR versions refuse mixed-geometry FeatureCollections.
    * The jq slim step in ``build.yml`` can produce a nested structure
      where ``"features"`` is a FeatureCollection object instead of an
      array (``|= map(...) | {... features: .}`` evaluates ``.`` as the
      whole updated FC).  The json path handles both cases.
    """
    with open(highways_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    features = raw.get("features", [])
    if isinstance(features, dict):          # unwrap nested FC
        features = features.get("features", [])

    rows = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
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
    """Return (geoms, STRtree) for already-mapped footway=crossing ways."""
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


def _load_sidewalk_ways(footways_path: str) -> tuple[list, STRtree | None]:
    """Return (geoms, STRtree) for footway=sidewalk ways ONLY.

    Intentionally strict: link, crossing, and highway=pedestrian are
    excluded.  footway=crossing ways at nearby intersections can be
    roughly parallel to the road being tested, falsely satisfying a
    parallel-coverage check even when no sidewalk is drawn.  Limiting
    to footway=sidewalk eliminates this false-positive path entirely.
    """
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
    print(f"  footway=sidewalk ways indexed: {len(geoms)}")
    return geoms, (STRtree(geoms) if geoms else None)


def _load_roads(roads_path: str) -> tuple[gpd.GeoDataFrame, list, STRtree]:
    """Load eligible road ways; return (gdf, geom_list, STRtree)."""
    gdf = gpd.read_file(roads_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    gdf = gdf[gdf["highway"].isin(_CROSSING_ROAD_TYPES)]
    gdf = gdf[gdf.geometry.length >= _MIN_ROAD_LENGTH]
    gdf = gdf.reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, STRtree(geoms)


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def _road_left_perp(road_geom, node_pt, step: float = 3.0) -> tuple[float, float] | None:
    """Return the unit left-perpendicular of the road at *node_pt*.

    Interpolates two points ±*step* metres along the road from the
    node's projection, then computes the direction vector and rotates
    it 90° left.  Returns ``None`` if the road is degenerate at that
    location.
    """
    d = road_geom.project(node_pt)
    p1 = road_geom.interpolate(max(0.0, d - step))
    p2 = road_geom.interpolate(min(road_geom.length, d + step))
    dx, dy = p2.x - p1.x, p2.y - p1.y
    norm = math.hypot(dx, dy)
    if norm < 0.01:
        return None
    return (-dy / norm, dx / norm)   # left perpendicular


def _sidewalk_zones(
    node_pt: Point,
    perp: tuple[float, float],
) -> tuple[Point, Point]:
    """Build left and right circular search zones at *node_pt*."""
    px, py = perp
    left_center  = Point(node_pt.x + px * CROSSING_SIDEWALK_OFFSET_M,
                         node_pt.y + py * CROSSING_SIDEWALK_OFFSET_M)
    right_center = Point(node_pt.x - px * CROSSING_SIDEWALK_OFFSET_M,
                         node_pt.y - py * CROSSING_SIDEWALK_OFFSET_M)
    return (
        left_center.buffer(CROSSING_SIDEWALK_SEARCH_M),
        right_center.buffer(CROSSING_SIDEWALK_SEARCH_M),
    )


def _has_sidewalk(zone, tree: STRtree, geoms: list) -> bool:
    """Return True if any sidewalk geometry intersects *zone*."""
    for i in tree.query(zone):
        if geoms[i].intersects(zone):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def detect_missing_crossings(
    highways_geojson_path: str = "highways.geojson",
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    roads_geojson_path: str = "sidewalk_roads_raw.geojson",
) -> dict:
    """Detect highway=crossing nodes that lack a footway=crossing way
    where sidewalks exist on both sides of the road.

    Returns a dict of statistics for stats.json.
    """
    print("Detecting missing crossing ways...")
    print(
        f"  Node→road search: {CROSSING_NODE_ROAD_SEARCH_M} m | "
        f"Sidewalk offset: {CROSSING_SIDEWALK_OFFSET_M} m | "
        f"Sidewalk search radius: {CROSSING_SIDEWALK_SEARCH_M} m | "
        f"Crossing-way radius: {CROSSING_WAY_SEARCH_RADIUS_M} m"
    )

    # ── Load data ─────────────────────────────────────────────────────────
    with step("load crossing nodes (highways.geojson)"):
        crossing_nodes = _load_crossing_nodes(highways_geojson_path)
    print(f"  highway=crossing nodes: {len(crossing_nodes)}")

    if crossing_nodes.empty:
        print("  No crossing nodes found — skipping.")
        _write_empty_output()
        return {"crossing_nodes_found": 0, "missing_crossings_detected": 0}

    with step("load crossing ways"):
        cw_geoms, cw_tree = _load_crossing_ways(footways_geojson_path)
    print(f"  footway=crossing ways indexed: {len(cw_geoms)}")

    with step("load sidewalk ways (footway=sidewalk only)"):
        sw_geoms, sw_tree = _load_sidewalk_ways(footways_geojson_path)

    with step("load eligible roads"):
        roads_gdf, road_geoms, road_tree = _load_roads(roads_geojson_path)
    print(f"  Road segments: {len(roads_gdf)}")

    if sw_tree is None:
        print("  No footway=sidewalk ways found — skipping.")
        _write_empty_output()
        return {
            "crossing_nodes_found": len(crossing_nodes),
            "missing_crossings_detected": 0,
        }

    # ── Analyse each crossing node ────────────────────────────────────────
    rows: list[dict] = []
    n_no_road = 0        # no eligible road found within search radius
    n_has_way = 0        # crossing way already mapped nearby
    n_no_sidewalks = 0   # sidewalks missing on one or both sides
    n_missing = 0        # confirmed missing crossing way

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

            # 2. Skip if a crossing way is already mapped nearby ────────────
            if cw_tree is not None:
                cw_zone = node_pt.buffer(CROSSING_WAY_SEARCH_RADIUS_M)
                nearby = cw_tree.query(cw_zone)
                if any(cw_geoms[i].intersects(cw_zone) for i in nearby):
                    n_has_way += 1
                    continue

            # 3. Compute perpendicular direction at the crossing node ───────
            perp = _road_left_perp(road_geom, node_pt)
            if perp is None:
                n_no_road += 1
                continue

            # 4. Check for footway=sidewalk on both sides ───────────────────
            left_zone, right_zone = _sidewalk_zones(node_pt, perp)
            has_left  = _has_sidewalk(left_zone,  sw_tree, sw_geoms)
            has_right = _has_sidewalk(right_zone, sw_tree, sw_geoms)

            if not (has_left and has_right):
                n_no_sidewalks += 1
                continue

            # 5. Flag ──────────────────────────────────────────────────────
            road_name = ""
            if "name" in roads_gdf.columns:
                road_name = _safe_str(roads_gdf.iloc[best_idx]["name"])

            n_missing += 1
            rows.append({
                "geometry": node_pt,
                "name": road_name,
                "left":  has_left,
                "right": has_right,
            })

    # ── Save output ───────────────────────────────────────────────────────
    with step("write missing_crossings.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = gpd.GeoDataFrame(
                [{"geometry": None, "name": "", "left": False, "right": False}],
                crs="EPSG:4326",
            )
        out_gdf.to_file("missing_crossings.geojson", driver="GeoJSON")

    n_total = len(crossing_nodes)
    print(f"  Nodes analysed: {n_total}")
    print(f"  Skipped — no eligible road: {n_no_road}")
    print(f"  Skipped — crossing way exists: {n_has_way}")
    print(f"  Skipped — sidewalks missing on a side: {n_no_sidewalks}")
    print(f"  Missing crossing ways detected: {n_missing}")

    return {
        "crossing_nodes_found":         n_total,
        "no_eligible_road":             n_no_road,
        "crossing_way_exists":          n_has_way,
        "sidewalks_missing_on_a_side":  n_no_sidewalks,
        "missing_crossings_detected":   n_missing,
    }


def _write_empty_output() -> None:
    gpd.GeoDataFrame(
        [{"geometry": None, "name": "", "left": False, "right": False}],
        crs="EPSG:4326",
    ).to_file("missing_crossings.geojson", driver="GeoJSON")
