import itertools
import math

import numpy as np
import pytest

import routing
from routing import generate_od_pairs

_XS = [0.0, 200.0, 400.0, 700.0, 6000.0]
_NODES = [10, 11, 12, 13, 14]
_X_BY_NODE = dict(zip(_NODES, _XS))
_VALID = {
    frozenset((0.0, 400.0)),
    frozenset((0.0, 700.0)),
    frozenset((200.0, 700.0)),
    frozenset((400.0, 700.0)),
}


@pytest.fixture(autouse=True)
def default_limits(monkeypatch):
    monkeypatch.setattr(routing, "MIN_OD_DISTANCE_M", 300.0)
    monkeypatch.setattr(routing, "MAX_OD_DISTANCE_M", 5000.0)
    monkeypatch.setattr(routing, "MAX_OD_PAIRS", 50_000)


def _points(xs):
    return [(x, 0.0) for x in xs]


def _as_x_pairs(od_pairs):
    return {frozenset((_X_BY_NODE[a], _X_BY_NODE[b])) for a, b in od_pairs}


def _brute_force(points, min_d, max_d):
    valid, near, far = set(), 0, 0
    for i, j in itertools.combinations(range(len(points)), 2):
        d = math.dist(points[i], points[j])
        if d > max_d:
            far += 1
        elif d < min_d:
            near += 1
        else:
            valid.add(frozenset((i, j)))
    return valid, near, far


def test_line_scenario_matches_hand_count():
    od_pairs, near, far = generate_od_pairs(_points(_XS), _NODES)

    assert _as_x_pairs(od_pairs) == _VALID
    assert len(od_pairs) == 4
    assert near == 2
    assert far == 4


def test_minimum_distance_is_inclusive():
    od_pairs, near, far = generate_od_pairs(_points([0.0, 300.0]), [1, 2])
    assert len(od_pairs) == 1
    assert (near, far) == (0, 0)


def test_maximum_distance_is_inclusive():
    od_pairs, near, far = generate_od_pairs(_points([0.0, 5000.0]), [1, 2])
    assert len(od_pairs) == 1
    assert (near, far) == (0, 0)


def test_just_beyond_maximum_is_far():
    od_pairs, near, far = generate_od_pairs(_points([0.0, 5000.5]), [1, 2])
    assert od_pairs == []
    assert (near, far) == (0, 1)


def test_pairs_snapped_to_the_same_node_are_dropped():
    snapped = [10, 11, 10, 13, 14]
    od_pairs, near, far = generate_od_pairs(_points(_XS), snapped)

    assert all(a != b for a, b in od_pairs)
    assert len(od_pairs) == 3
    assert (near, far) == (2, 4)


def test_output_uses_snapped_node_ids():
    od_pairs, _, _ = generate_od_pairs(_points(_XS), _NODES)
    assert {n for pair in od_pairs for n in pair} <= set(_NODES)


def test_cap_limits_pairs_to_valid_distinct_ones(monkeypatch):
    monkeypatch.setattr(routing, "MAX_OD_PAIRS", 2)
    od_pairs, _, _ = generate_od_pairs(_points(_XS), _NODES)

    picked = _as_x_pairs(od_pairs)
    assert len(od_pairs) == 2
    assert len(picked) == 2
    assert picked <= _VALID


def test_sampling_is_deterministic(monkeypatch):
    monkeypatch.setattr(routing, "MAX_OD_PAIRS", 2)
    first, _, _ = generate_od_pairs(_points(_XS), _NODES)
    second, _, _ = generate_od_pairs(_points(_XS), _NODES)
    assert first == second


def test_fewer_than_two_points():
    assert generate_od_pairs([], []) == ([], 0, 0)
    assert generate_od_pairs([(0.0, 0.0)], [1]) == ([], 0, 0)


def test_chunking_does_not_change_the_result(monkeypatch):
    whole, near_w, far_w = generate_od_pairs(_points(_XS), _NODES)
    monkeypatch.setattr(routing, "_OD_QUERY_CHUNK", 2)
    chunked, near_c, far_c = generate_od_pairs(_points(_XS), _NODES)

    assert _as_x_pairs(chunked) == _as_x_pairs(whole)
    assert len(chunked) == len(whole)
    assert (near_c, far_c) == (near_w, far_w)


@pytest.mark.parametrize("chunk", [1, 7, 2000])
def test_random_cloud_matches_brute_force(monkeypatch, chunk):
    monkeypatch.setattr(routing, "MIN_OD_DISTANCE_M", 150.0)
    monkeypatch.setattr(routing, "MAX_OD_DISTANCE_M", 600.0)
    monkeypatch.setattr(routing, "_OD_QUERY_CHUNK", chunk)

    rng = np.random.default_rng(1234)
    points = [tuple(p) for p in rng.uniform(0.0, 1000.0, size=(80, 2))]
    snapped = list(range(80))

    od_pairs, near, far = generate_od_pairs(points, snapped)
    expected, exp_near, exp_far = _brute_force(points, 150.0, 600.0)

    produced = {frozenset(p) for p in od_pairs}
    assert len(od_pairs) == len(expected)
    assert produced == expected
    assert (near, far) == (exp_near, exp_far)


def test_both_directions_are_sampled(monkeypatch):
    monkeypatch.setattr(routing, "MIN_OD_DISTANCE_M", 150.0)
    monkeypatch.setattr(routing, "MAX_OD_DISTANCE_M", 600.0)

    rng = np.random.default_rng(1234)
    points = [tuple(p) for p in rng.uniform(0.0, 1000.0, size=(80, 2))]
    od_pairs, _, _ = generate_od_pairs(points, list(range(80)))

    ascending = sum(1 for a, b in od_pairs if a < b)
    share = ascending / len(od_pairs)
    assert 0.3 < share < 0.7


def test_cap_on_large_set_draws_without_replacement(monkeypatch):
    monkeypatch.setattr(routing, "MIN_OD_DISTANCE_M", 150.0)
    monkeypatch.setattr(routing, "MAX_OD_DISTANCE_M", 600.0)

    rng = np.random.default_rng(1234)
    points = [tuple(p) for p in rng.uniform(0.0, 1000.0, size=(80, 2))]
    expected, _, _ = _brute_force(points, 150.0, 600.0)
    cap = len(expected) // 2
    monkeypatch.setattr(routing, "MAX_OD_PAIRS", cap)

    od_pairs, _, _ = generate_od_pairs(points, list(range(80)))

    produced = {frozenset(p) for p in od_pairs}
    assert len(od_pairs) == cap
    assert len(produced) == cap
    assert produced <= expected
