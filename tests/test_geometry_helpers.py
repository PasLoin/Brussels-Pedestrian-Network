import pytest
from shapely.geometry import LineString

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

