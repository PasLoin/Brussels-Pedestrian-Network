"""Tests for the pure helpers in scripts/sample_od.py."""

import numpy as np
import pytest

from sample_od import (
    _extract_house_number,
    _pick_indices,
    _principal_axis,
    _sample_side_geographic,
)


# ─────────────────────────────────────────────────────────────────────────────
# _extract_house_number
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("12", 12),
        ("12A", 12),          # 
        ("3-5", 3),
        (7, 7),
        ("bis", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_house_number(raw, expected):
    assert _extract_house_number(raw) == expected


# ─────────────────────────────────────────────────────────────────────────────
# _pick_indices (legacy mode)
# ─────────────────────────────────────────────────────────────────────────────

def test_pick_indices():
    assert _pick_indices(0, 5) == []
    assert _pick_indices(3, 5) == [1]           # fewer items than k → middle
    idxs = _pick_indices(100, 5)
    assert len(idxs) == 5
    assert idxs == sorted(idxs)
    assert all(0 <= i < 100 for i in idxs)


# ─────────────────────────────────────────────────────────────────────────────
# _principal_axis
# ─────────────────────────────────────────────────────────────────────────────

def test_principal_axis_horizontal_street():
    coords = np.array([[0.0, 0.0], [100.0, 1.0], [200.0, -1.0], [300.0, 0.5]])
    axis = _principal_axis(coords)
    # unit vector, essentially along x
    assert np.isclose(np.linalg.norm(axis), 1.0)
    assert abs(axis[0]) > 0.99


def test_principal_axis_degenerate():
    assert list(_principal_axis(np.array([[5.0, 5.0]]))) == [1.0, 0.0]


# ─────────────────────────────────────────────────────────────────────────────
# _sample_side_geographic
# ─────────────────────────────────────────────────────────────────────────────

def test_sample_side_one_point_per_bin():
    # addresses every 10 m along a 300 m street; 100 m bins → 3 points
    proj = np.arange(0.0, 300.0, 10.0)
    selected = _sample_side_geographic(proj, 100.0, 0.0, 300.0)
    assert len(selected) == 3
    # picked points are near bin centers (50, 150, 250)
    picked = sorted(proj[i] for i in selected)
    assert picked == [50.0, 150.0, 250.0]


def test_sample_side_empty_bins_are_skipped():
    # addresses only in the first 50 m of a 300 m street
    proj = np.array([0.0, 10.0, 20.0])
    selected = _sample_side_geographic(proj, 100.0, 0.0, 300.0)
    assert len(selected) == 1


def test_sample_side_edge_cases():
    assert _sample_side_geographic(np.array([]), 100.0, 0.0, 300.0) == []
    assert _sample_side_geographic(np.array([1.0]), 0.0, 0.0, 300.0) == []
