"""
Detect ``highway=footway`` ways that structurally look like an unmapped
or mistagged crossing — independent of and complementary to the
node-based analysis in ``detect_missing_crossings.py``.

Why a separate, way-centric analysis
-------------------------------------
``detect_missing_crossings`` starts from a ``highway=crossing`` NODE and
searches a bearing-aligned zone on each side of the *nearest* road for a
parallel ``footway=sidewalk``. That geometric test breaks down at
diagonal / corner-cutting crossings in complex junctions: the sidewalk
exists, but it isn't parallel to whichever road happened to be closest
to the node, so the way is silently dropped (``no_sw``) — a real
missing-tag case goes unreported.

This script sidesteps the bearing / reference-road problem entirely by
asking a purely topological question about the WAY itself, not the
node:

    Does this footway cross an eligible road, and does each of its two
    endpoints touch a ``footway=sidewalk`` on a *different* side of
    that road?

That's a solid structural definition of a crossing, independent of
angle or of which road happens to be geometrically nearest. It also
doesn't require a ``highway=crossing`` node to exist at all, so it also
catches footways that silently cross a road with no crossing node
mapped — a blind spot for the node-based analysis.

Why this stays a SEPARATE, lower-confidence layer
----------------------------------------------------
"Touches a sidewalk at both ends" alone would also catch park paths,
plaza shortcuts, and footways that simply continue along one side of a
street. Three filters keep the false-positive rate down without
reintroducing an angle threshold:

1. **Must cross an eligible road mid-way**, not just brush it near a
   tip (``FOOTWAY_CONN_TIP_MARGIN_M``) — eliminates most park/plaza
   paths, which don't have a road cutting through their middle.
2. **The two connected sidewalks must be on opposite sides** of that
   road — eliminates footways that wrap around a corner and connect
   two sidewalks on the *same* side.
3. **Length cap** (``FOOTWAY_CONN_MAX_LEN_M``) — real crossings are
   short (carriageway + refuge); long looping park paths that
   coincidentally touch a sidewalk at each end are excluded.

Even with these filters this remains a heuristic — hence a dedicated
output file and (eventually) a distinct, lower-emphasis map layer
labelled "to verify" rather than merged into the higher-precision
``missing_way`` / ``missing_tag`` results.

Inputs
------
* ``sidewalk_footways_raw.geojson`` — raw osmium footway export.
* ``sidewalk_roads_raw.geojson``    — raw osmium road export.

Output
------
``footway_crossing_candidates.geojson`` — LineString layer with:
  ``name``      crossed road's name
  ``length_m``  footway length in metres (rounded)
  ``osm_id``    OSM way id (0 when the extract lacks ``@id``)
"""

from __future__ import annotations

import math
import os

import geopandas as gpd
from shapely.geometry import Point
from shapely.strtree import STRtree

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from timing import step

_CROSSING_ROAD_TYPES = ROAD_TYPES_SIDEWALK_EXPECTED - {"service"}
_MIN_ROAD_LENGTH = 15.0

# ── Module-level config ────────────────────────────────────────────────

# Tolerance (m) for "this endpoint touches a footway=sidewalk".
FOOTWAY_CONN_ENDPOINT_TOL_M = float(os.environ.get("FOOTWAY_CONN_ENDPOINT_TOL_M", 3.0))

# Margin (m) from either tip before a road intersection counts as a
# genuine mid-way crossing rather than the footway merely touching the
# road at its end (which means "connects to the road", not "crosses it").
FOOTWAY_CONN_TIP_MARGIN_M = float(os.environ.get("FOOTWAY_CONN_TIP_MARGIN_M", 2.0))

# Real crossings are short (carriageway + refuge). Longer candidates are
# almost always park/plaza paths that happen to touch a sidewalk at
# each end.
FOOTWAY_CONN_MAX_LEN_M = float(os.environ.get("FOOTWAY_CONN_MAX_LEN_M", 40.0))

# Degenerate candidates shorter than this are skipped outright.
_MIN_CAND_LEN_M = 1.0


# ── String / geometry helpers ───────────────────────────────────────────

def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip().lower()


def _iter_points(geom):
    """Yield representative Points from a (possibly mixed) intersection result."""
    gt = geom.geom_type
    if geom.is_empty:
        return
    if gt == "Point":
        yield geom
    elif gt == "MultiPoint":
        yield from geom.geoms
    elif gt == "LineString":
        # Footway runs briefly along the road (rare) — approximate with
        # the midpoint of the overlap.
        yield geom.interpolate(0.5, normalized=True)
    elif gt == "MultiLineString":
        for sub in geom.geoms:
            if not sub.is_empty:
                yield sub.interpolate(0.5, normalized=True)
    elif gt == "GeometryCollection":
        for sub in geom.geoms:
            yield from _iter_points(sub)


def _road_perp_at(road_geom, pt: Point, step_m: float = 3.0):
    """Perpendicular unit vector to *road_geom* at the point nearest *pt*."""
    d = road_geom.project(pt)
    p1 = road_geom.interpolate(max(0.0, d - step_m))
    p2 = road_geom.interpolate(min(road_geom.length, d + step_m))
    dx, dy = p2.x - p1.x, p2.y - p1.y
    norm = math.hypot(dx, dy)
    if norm < 0.01:
        return None
    return (-dy / norm, dx / norm)


def _side(perp, origin: Point, pt: Point) -> float:
    """Signed side of *pt* relative to *origin*, projected on *perp*."""
    return (pt.x - origin.x) * perp[0] + (pt.y - origin.y) * perp[1]


def _touches_sidewalk(pt: Point, tree: STRtree, geoms: list) -> bool:
    zone = pt.buffer(FOOTWAY_CONN_ENDPOINT_TOL_M)
    return any(geoms[i].intersects(zone) for i in tree.query(zone))


# ── Data loaders ─────────────────────────────────────────────────────────

_ALREADY_CLASSIFIED = frozenset({"crossing", "sidewalk", "traffic_island"})


def _load_footway_candidates(footways_path: str) -> gpd.GeoDataFrame:
    """highway=footway ways not already unambiguously classified.

    Excludes ``footway=crossing`` (already correctly tagged — the point
    of this analysis) and, deliberately going a bit further than "just
    not crossing": also excludes ``footway=sidewalk`` and
    ``footway=traffic_island``. Those two are already positively
    classified as something other than a crossing, so testing them as
    crossing candidates would be both wasted work and — if one happened
    to pass the geometric filters — a confusing false positive (telling
    a mapper to add ``footway=crossing`` to a way that's legitimately a
    sidewalk). Untagged footways and ``footway=link`` remain candidates:
    those are genuinely ambiguous.
    """
    gdf = gpd.read_file(footways_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    for col in ("highway", "footway"):
        if col not in gdf.columns:
            gdf[col] = ""
    if "@id" not in gdf.columns:
        gdf["@id"] = 0
    mask = (
        (gdf["highway"].apply(_safe_str) == "footway") &
        (~gdf["footway"].apply(_safe_str).isin(_ALREADY_CLASSIFIED))
    )
    return gdf[mask].reset_index(drop=True)


def _load_sidewalk_ways(footways_path: str) -> tuple[list, STRtree | None]:
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
    return geoms, (STRtree(geoms) if geoms else None)


def _load_roads(roads_path: str) -> tuple[gpd.GeoDataFrame, list, STRtree | None]:
    gdf = gpd.read_file(roads_path)
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy().to_crs("EPSG:31370")
    gdf = gdf[gdf["highway"].isin(_CROSSING_ROAD_TYPES)]
    gdf = gdf[gdf.geometry.length >= _MIN_ROAD_LENGTH]
    gdf = gdf.reset_index(drop=True)
    geoms = list(gdf.geometry)
    return gdf, geoms, (STRtree(geoms) if geoms else None)


def _write_empty_output() -> None:
    gpd.GeoDataFrame(
        [{"geometry": None, "name": "", "length_m": 0.0, "osm_id": 0}],
        crs="EPSG:4326",
    ).to_file("footway_crossing_candidates.geojson", driver="GeoJSON")


# ── Main ──────────────────────────────────────────────────────────────────

def detect_footway_connectivity_candidates(
    footways_geojson_path: str = "sidewalk_footways_raw.geojson",
    roads_geojson_path:    str = "sidewalk_roads_raw.geojson",
) -> dict:
    """Way-centric heuristic for footways that look like unmapped crossings.

    Returns a statistics dict for stats.json.
    """
    print("Detecting footway/sidewalk connectivity crossing candidates...")
    print(
        f"  Endpoint tolerance: {FOOTWAY_CONN_ENDPOINT_TOL_M} m | "
        f"Tip margin: {FOOTWAY_CONN_TIP_MARGIN_M} m | "
        f"Max length: {FOOTWAY_CONN_MAX_LEN_M} m"
    )

    with step("load footway candidates"):
        cand_gdf = _load_footway_candidates(footways_geojson_path)
    print(f"  Candidate footways (highway=footway, not already crossing/"
          f"sidewalk/traffic_island): {len(cand_gdf)}")

    with step("load sidewalks"):
        sw_geoms, sw_tree = _load_sidewalk_ways(footways_geojson_path)
    print(f"  footway=sidewalk ways: {len(sw_geoms)}")

    with step("load eligible roads"):
        roads_gdf, road_geoms, road_tree = _load_roads(roads_geojson_path)
    print(f"  Eligible road segments: {len(roads_gdf)}")

    if cand_gdf.empty or sw_tree is None or road_tree is None:
        print("  Nothing to analyse — skipping.")
        _write_empty_output()
        return {"candidates_scanned": int(len(cand_gdf)), "flagged": 0}

    has_name_col = "name" in roads_gdf.columns

    rows: list[dict] = []
    n_too_short_or_long = 0
    n_no_road_cross      = 0
    n_same_side          = 0
    n_no_sidewalk_both   = 0
    n_flagged            = 0

    with step("candidate analysis loop"):
        for _, cand in cand_gdf.iterrows():
            geom = cand.geometry
            length = geom.length

            if length < _MIN_CAND_LEN_M or length > FOOTWAY_CONN_MAX_LEN_M:
                n_too_short_or_long += 1
                continue

            p_start = Point(geom.coords[0])
            p_end   = Point(geom.coords[-1])

            # 1. Must cross an eligible road mid-way (not just near a tip).
            best_ri, best_cross_pt, best_mid_dist = None, None, None
            for ri in road_tree.query(geom):
                road_geom = road_geoms[ri]
                if not geom.intersects(road_geom):
                    continue
                inter = geom.intersection(road_geom)
                for cross_pt in _iter_points(inter):
                    d = geom.project(cross_pt)
                    if d < FOOTWAY_CONN_TIP_MARGIN_M or d > length - FOOTWAY_CONN_TIP_MARGIN_M:
                        continue  # touches near a tip — not a genuine crossing
                    mid_dist = abs(d - length / 2.0)
                    if best_mid_dist is None or mid_dist < best_mid_dist:
                        best_mid_dist, best_ri, best_cross_pt = mid_dist, ri, cross_pt

            if best_ri is None:
                n_no_road_cross += 1
                continue

            # 2. The two endpoints must fall on opposite sides of that road.
            road_geom = road_geoms[best_ri]
            perp = _road_perp_at(road_geom, best_cross_pt)
            if perp is None:
                n_no_road_cross += 1
                continue
            side_start = _side(perp, best_cross_pt, p_start)
            side_end   = _side(perp, best_cross_pt, p_end)
            if side_start == 0 or side_end == 0 or (side_start > 0) == (side_end > 0):
                n_same_side += 1
                continue

            # 3. Both endpoints must touch a footway=sidewalk.
            if not (_touches_sidewalk(p_start, sw_tree, sw_geoms) and
                    _touches_sidewalk(p_end, sw_tree, sw_geoms)):
                n_no_sidewalk_both += 1
                continue

            n_flagged += 1
            road_name = _safe_str(roads_gdf.iloc[best_ri]["name"]) if has_name_col else ""
            try:
                osm_id = int(cand.get("@id") or 0)
            except (TypeError, ValueError):
                osm_id = 0

            rows.append({
                "geometry": geom,
                "name": road_name,
                "length_m": round(length, 1),
                "osm_id": osm_id,
            })

    with step("write footway_crossing_candidates.geojson"):
        if rows:
            out_gdf = gpd.GeoDataFrame(rows, crs="EPSG:31370").to_crs("EPSG:4326")
        else:
            out_gdf = gpd.GeoDataFrame(
                [{"geometry": None, "name": "", "length_m": 0.0, "osm_id": 0}],
                crs="EPSG:4326",
            )
        out_gdf.to_file("footway_crossing_candidates.geojson", driver="GeoJSON")

    n_total = len(cand_gdf)
    print(f"  Candidates scanned:                      {n_total}")
    print(f"  Skipped — length out of range:           {n_too_short_or_long}")
    print(f"  Skipped — no mid-way road crossing:      {n_no_road_cross}")
    print(f"  Skipped — sidewalks on same side:        {n_same_side}")
    print(f"  Skipped — no sidewalk on both ends:      {n_no_sidewalk_both}")
    print(f"  Flagged as crossing candidates:          {n_flagged}")

    return {
        "candidates_scanned":       n_total,
        "length_out_of_range":      n_too_short_or_long,
        "no_midway_road_crossing":  n_no_road_cross,
        "sidewalks_same_side":      n_same_side,
        "no_sidewalk_both_ends":    n_no_sidewalk_both,
        "flagged":                  n_flagged,
    }
