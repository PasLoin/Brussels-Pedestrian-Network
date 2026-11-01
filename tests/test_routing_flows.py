import igraph as ig
import numpy as np
import pytest

from routing import route_pairs

_LINE_EDGES = [(0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2)]
_SEGMENT_M = 100.0


def _line_graph(extra_edges=(), extra_weights=(), extra_lengths=()):
    edges = list(_LINE_EDGES) + list(extra_edges)
    lengths = [_SEGMENT_M] * len(_LINE_EDGES) + list(extra_lengths)
    weights = [_SEGMENT_M] * len(_LINE_EDGES) + list(extra_weights)
    g = ig.Graph(directed=True, n=5)
    g.add_edges(edges)
    g.es["weight"] = weights
    g.es["length"] = lengths
    return g, lengths


def _flows_by_edge(graph, flow_arr):
    out = {}
    for eid, edge in enumerate(graph.es):
        key = (edge.source, edge.target)
        out[key] = out.get(key, 0) + int(flow_arr[eid])
    return out


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_flows_on_line_graph_match_hand_count():
    g, lengths = _line_graph()
    result = route_pairs(g, [(0, 3), (3, 0), (0, 2), (0, 4)], lengths)

    assert _flows_by_edge(g, result.flow_arr) == {
        (0, 1): 2,
        (1, 2): 2,
        (2, 3): 1,
        (3, 2): 1,
        (2, 1): 1,
        (1, 0): 1,
    }
    assert result.routed == 3
    assert result.total_routed_distance == pytest.approx(800.0)
    assert result.od_pairs_count == 4


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_unreachable_pair_adds_no_flow():
    g, lengths = _line_graph()
    result = route_pairs(g, [(0, 4)], lengths)

    assert result.routed == 0
    assert int(result.flow_arr.sum()) == 0
    assert result.total_routed_distance == 0.0


def test_flow_array_is_aligned_with_graph_edges():
    g, lengths = _line_graph()
    result = route_pairs(g, [(0, 3)], lengths)

    assert len(result.flow_arr) == g.ecount()
    assert np.issubdtype(result.flow_arr.dtype, np.integer)


def test_duplicate_pairs_are_counted_each_time():
    g, lengths = _line_graph()
    result = route_pairs(g, [(0, 3), (0, 3)], lengths)

    flows = _flows_by_edge(g, result.flow_arr)
    assert flows[(0, 1)] == 2
    assert flows[(1, 2)] == 2
    assert flows[(2, 3)] == 2
    assert flows[(3, 2)] == 0
    assert result.routed == 2
    assert result.total_routed_distance == pytest.approx(600.0)


def test_pair_order_does_not_change_flows():
    g, lengths = _line_graph()
    pairs = [(0, 3), (3, 0), (0, 2), (2, 0), (1, 3)]

    forward = route_pairs(g, pairs, lengths)
    backward = route_pairs(g, list(reversed(pairs)), lengths)

    assert np.array_equal(forward.flow_arr, backward.flow_arr)
    assert forward.routed == backward.routed == len(pairs)


def test_routing_follows_weight_not_length():
    g, lengths = _line_graph(
        extra_edges=[(0, 3)],
        extra_weights=[1000.0],
        extra_lengths=[50.0],
    )
    result = route_pairs(g, [(0, 3)], lengths)

    flows = _flows_by_edge(g, result.flow_arr)
    assert flows[(0, 3)] == 0
    assert flows[(0, 1)] == flows[(1, 2)] == flows[(2, 3)] == 1
    assert result.total_routed_distance == pytest.approx(300.0)


def test_cheap_shortcut_is_taken_when_its_weight_is_lower():
    g, lengths = _line_graph(
        extra_edges=[(0, 3)],
        extra_weights=[250.0],
        extra_lengths=[400.0],
    )
    result = route_pairs(g, [(0, 3)], lengths)

    flows = _flows_by_edge(g, result.flow_arr)
    assert flows[(0, 3)] == 1
    assert flows[(0, 1)] == 0
    assert result.total_routed_distance == pytest.approx(400.0)


def test_no_pairs_gives_empty_result():
    g, lengths = _line_graph()
    result = route_pairs(g, [], lengths)

    assert result.routed == 0
    assert result.od_pairs_count == 0
    assert int(result.flow_arr.sum()) == 0
    assert result.total_routed_distance == 0.0


_FLUSH_PAIRS = [(0, 3), (0, 2), (3, 0), (1, 3), (2, 0), (3, 1), (1, 0)]


def _route_with_flush(monkeypatch, flush_edges):
    import routing
    monkeypatch.setattr(routing, "_FLOW_FLUSH_EDGES", flush_edges)
    g, lengths = _line_graph()
    return g, route_pairs(g, _FLUSH_PAIRS, lengths)


def test_flush_scenario_matches_hand_count(monkeypatch):
    g, result = _route_with_flush(monkeypatch, 1_000_000)

    assert _flows_by_edge(g, result.flow_arr) == {
        (0, 1): 2,
        (1, 2): 3,
        (2, 3): 2,
        (3, 2): 2,
        (2, 1): 3,
        (1, 0): 3,
    }
    assert result.routed == 7
    assert result.total_routed_distance == pytest.approx(1500.0)


@pytest.mark.parametrize("flush_edges", [0, 1, 2, 3, 5])
def test_flushing_often_does_not_change_flows(monkeypatch, flush_edges):
    g, reference = _route_with_flush(monkeypatch, 1_000_000)
    _, flushed = _route_with_flush(monkeypatch, flush_edges)

    assert np.array_equal(flushed.flow_arr, reference.flow_arr)
    assert flushed.routed == reference.routed
    assert flushed.total_routed_distance == pytest.approx(reference.total_routed_distance)


def _count_bincount_calls(monkeypatch):
    import routing
    calls = []
    original = routing.np.bincount

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(routing.np, "bincount", counting)
    return calls


def test_default_threshold_accumulates_in_a_single_pass(monkeypatch):
    calls = _count_bincount_calls(monkeypatch)
    _route_with_flush(monkeypatch, 1_000_000)
    assert len(calls) == 1


def test_low_threshold_really_flushes_several_times(monkeypatch):
    calls = _count_bincount_calls(monkeypatch)
    _route_with_flush(monkeypatch, 0)
    assert len(calls) == 4
