"""Tests for the walkability quality penalties in scripts/export.py."""

import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from config import LIT_PENALTY_MAX, PED_INFRA_RADIUS_M, SURFACE_PENALTY_MAX
from export import _attr_quality_penalty, _PedInfraIndex, export_walkability_scores


# ─────────────────────────────────────────────────────────────────────────────
# _attr_quality_penalty
# ─────────────────────────────────────────────────────────────────────────────

def test_attr_penalty_fully_documented_is_free():
    assert _attr_quality_penalty(1.0, 1.0) == pytest.approx(1.0)


def test_attr_penalty_fully_undocumented_is_max():
    expected = (1 - SURFACE_PENALTY_MAX) * (1 - LIT_PENALTY_MAX)
    assert _attr_quality_penalty(0.0, 0.0) == pytest.approx(expected)


def test_attr_penalty_is_linear_per_attribute():
    assert _attr_quality_penalty(0.5, 1.0) == pytest.approx(1 - SURFACE_PENALTY_MAX * 0.5)
    assert _attr_quality_penalty(1.0, 0.5) == pytest.approx(1 - LIT_PENALTY_MAX * 0.5)


# ─────────────────────────────────────────────────────────────────────────────
# _PedInfraIndex
# ─────────────────────────────────────────────────────────────────────────────

def _mk_index(edges):
    """edges: list of (u, v, geom, highway, surface, lit)."""
    return _PedInfraIndex(
        edge_tuples=[(e[0], e[1]) for e in edges],
        edge_geoms=[e[2] for e in edges],
        edge_highways=[e[3] for e in edges],
        edge_surfaces=[e[4] for e in edges],
        edge_lits=[e[5] for e in edges],
    )


def test_infra_index_counts_each_way_once_and_clips_radius():
    # 200 m footway crossing the centre, present in BOTH directions
    # (bidirectional graph) → must count once.  A road edge and a far
    # footway must not count at all.
    fw = LineString([(-100, 0), (100, 0)])
    far = LineString([(10000, 0), (10100, 0)])
    road = LineString([(0, -50), (0, 50)])
    idx = _mk_index([
        (1, 2, fw, "footway", "asphalt", "yes"),
        (2, 1, fw, "footway", "asphalt", "yes"),      # reverse duplicate
        (3, 4, far, "footway", "", ""),
        (5, 6, road, "residential", "asphalt", "yes"),
    ])
    total, surf, lit = idx.local_stats(0.0, 0.0)
    assert total == pytest.approx(200.0, rel=1e-3)
    assert surf == pytest.approx(1.0)
    assert lit == pytest.approx(1.0)

    # Centred 400 m east: only 100 m of the footway lies inside the disc
    # (from x=300... the footway spans -100..100 → distance 300..500).
    total2, _, _ = idx.local_stats(PED_INFRA_RADIUS_M - 100 + 100, 0.0)
    assert total2 < total


def test_infra_index_shares_are_length_weighted():
    tagged = LineString([(0, 0), (100, 0)])       # 100 m, surface + lit
    untagged = LineString([(0, 10), (300, 10)])   # 300 m, no tags
    idx = _mk_index([
        (1, 2, tagged, "footway", "paving_stones", "yes"),
        (3, 4, untagged, "path", "", ""),
    ])
    total, surf, lit = idx.local_stats(50.0, 5.0)
    assert total == pytest.approx(400.0, rel=1e-3)
    assert surf == pytest.approx(0.25, abs=0.01)
    assert lit == pytest.approx(0.25, abs=0.01)


def test_infra_index_empty():
    idx = _mk_index([])
    assert idx.local_stats(0.0, 0.0) == (0.0, 0.0, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# export_walkability_scores end-to-end (regression: untagged footways
# must drag a 100% street down)
# ─────────────────────────────────────────────────────────────────────────────

def test_untagged_footways_penalise_perfect_street(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    addr = gpd.GeoDataFrame(
        {"addr:street": ["Rue Parfaite", "Rue Documentée"]},
        geometry=[Point(0, 0), Point(50000, 0)],
        crs="EPSG:31370",
    )
    from build_graph import SidewalkInfo
    status = {
        "Rue Parfaite": SidewalkInfo("both", 1.0, 1.0),
        "Rue Documentée": SidewalkInfo("both", 1.0, 1.0),
    }
    # Footways near Rue Parfaite: NO surface/lit tags.
    # Footways near Rue Documentée (50 km away): fully tagged.
    edges = [
        ((1, 2), LineString([(-100, 10), (100, 10)]), "footway", "", ""),
        ((3, 4), LineString([(49900, 10), (50100, 10)]), "footway", "asphalt", "yes"),
    ]
    export_walkability_scores(
        street_ped_m={"Rue Parfaite": 1000, "Rue Documentée": 1000},
        street_cyc_nf_m={},
        street_total_m={"Rue Parfaite": 1000, "Rue Documentée": 1000},
        street_sidewalk_status=status,
        addr_gdf=addr,
        edge_tuples=[e[0] for e in edges],
        edge_geoms=[e[1] for e in edges],
        edge_highways=[e[2] for e in edges],
        edge_surfaces=[e[3] for e in edges],
        edge_lits=[e[4] for e in edges],
    )

    props = {
        f["properties"]["street"]: f["properties"]
    for f in json.load(open("street_scores.geojson"))["features"]}

    perfect = props["Rue Parfaite"]
    documented = props["Rue Documentée"]

    # Both have raw 100% and sidewalk=both, but only the street whose
    # surrounding footways carry surface/lit keeps 100%.
    assert documented["walkability"] == pytest.approx(1.0)
    expected = (1 - SURFACE_PENALTY_MAX) * (1 - LIT_PENALTY_MAX)
    assert perfect["walkability"] == pytest.approx(expected, abs=0.01)

    # Display metric: physical infra within the radius, not trip meters.
    assert perfect["ped_infra_m"] == pytest.approx(200.0, rel=1e-2)
    assert perfect["surface_pct"] == 0
    assert documented["surface_pct"] == 100
    assert documented["lit_pct"] == 100
