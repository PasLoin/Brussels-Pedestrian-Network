"""Tests for the geometry helpers in scripts/sidewalk_gap.py and the
walkability accumulator in scripts/routing.py."""

import numpy as np
import pytest
from shapely.geometry import LineString

from routing import _accumulate_capped
from sidewalk_gap import _is_parallel, _line_bearing, _safe_str


# ─────────────────────────────────────────────────────────────────────────────
# sidewalk_gap helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_line_bearing():
    assert _line_bearing(LineString([(0, 0), (100, 0)])) == pytest.approx(0.0)
    assert _line_bearing(LineString([(0, 0), (0, 100)])) == pytest.approx(90.0)
    # direction-agnostic (folded to 0–180)
    assert _line_bearing(LineString([(100, 0), (0, 0)])) == pytest.approx(0.0)
    # degenerate: identical points → None
    assert _line_bearing(LineString([(0, 0), (0, 0)])) is None


def test_is_parallel_folds_around_180():
    # 178° vs 2° is only a 4° difference across the fold
    assert _is_parallel(178.0, 2.0)
    assert _is_parallel(10.0, 10.0)
    assert not _is_parallel(0.0, 90.0)
    assert not _is_parallel(0.0, None)


def test_safe_str():
    assert _safe_str(None) == ""
    assert _safe_str(float("nan")) == ""
    assert _safe_str("  Yes ") == "yes"
    assert _safe_str(3.5) == "3.5"


# ─────────────────────────────────────────────────────────────────────────────
# routing._accumulate_capped
# ─────────────────────────────────────────────────────────────────────────────

def test_accumulate_capped_basic():
    lengths = [100.0, 100.0, 100.0]
    ped = np.array([True, False, False])
    cyc = np.array([False, True, False])

    p, c, t = _accumulate_capped([0, 1, 2], 1000.0, lengths, ped, cyc)
    assert (p, c, t) == (100.0, 100.0, 300.0)


def test_accumulate_capped_respects_cap():
    lengths = [100.0, 100.0, 100.0]
    ped = np.array([True, True, True])
    cyc = np.array([False, False, False])

    # cap of 150 m: full first edge + 50 m of the second, third untouched
    p, c, t = _accumulate_capped([0, 1, 2], 150.0, lengths, ped, cyc)
    assert t == pytest.approx(150.0)
    assert p == pytest.approx(150.0)
    assert c == 0.0


def test_accumulate_capped_reversed_iterator():
    """Callers pass reversed(eids) for the trip's tail — the function
    must accept any iterable without materialising it."""
    lengths = [10.0, 20.0, 30.0]
    ped = np.array([True, False, True])
    cyc = np.array([False, False, False])

    p, c, t = _accumulate_capped(reversed([0, 1, 2]), 35.0, lengths, ped, cyc)
    # walks 30 (ped) then 5 of the 20 (not ped)
    assert t == pytest.approx(35.0)
    assert p == pytest.approx(30.0)
