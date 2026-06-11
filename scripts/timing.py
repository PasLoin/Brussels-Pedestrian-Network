"""
Lightweight wallclock instrumentation for the pipeline.

Usage
-----
Top-level (orchestration code)::

    from timing import step, print_summary

    with step("build_graph"):
        gb = build_graph("routing_clean.osm")
    # ...
    print_summary()

Sub-step inside a function::

    from timing import step
    with step("ox.graph_from_xml"):
        G = ox.graph_from_xml(...)

Cumulative timer inside a hot loop (avoids context-manager overhead per
iteration)::

    from timing import record
    t_dij = 0.0
    for src in sources:
        t0 = time.time()
        graph.get_shortest_paths(...)
        t_dij += time.time() - t0
    record("dijkstra (cumulative)", t_dij)

The summary is sorted in pipeline order (by start time), with sub-steps
indented under their parent.  Percentages are computed against the sum
of top-level steps so they always total roughly 100%.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

# (depth, label, start_time, elapsed)
_results: list[dict] = []
_depth = [0]


@contextmanager
def step(label: str):
    """Time a block.  Prints on entry and exit; logs for the summary."""
    t0 = time.time()
    depth = _depth[0]
    indent = "  " * depth
    head = "▶" if depth == 0 else "·"
    print(f"{indent}{head} {label}")
    _depth[0] += 1
    try:
        yield
    finally:
        _depth[0] -= 1
        elapsed = time.time() - t0
        _results.append({
            "label": label,
            "depth": depth,
            "start": t0,
            "elapsed": elapsed,
        })
        tail = "✓" if depth == 0 else "·"
        print(f"{indent}{tail} {label}: {elapsed:.2f}s")


def record(label: str, elapsed: float, depth: int | None = None) -> None:
    """Manually log a (label, elapsed) entry without using the context manager.

    Used for cumulative timers inside tight loops where wrapping every
    iteration would add measurable overhead.
    """
    if depth is None:
        depth = _depth[0]
    _results.append({
        "label": label,
        "depth": depth,
        "start": time.time() - elapsed,
        "elapsed": elapsed,
    })
    indent = "  " * depth
    print(f"{indent}· {label} (cumulative): {elapsed:.2f}s")


def print_summary() -> None:
    """Print a sorted-by-start timing breakdown."""
    if not _results:
        return

    top_level = [r for r in _results if r["depth"] == 0]
    total = sum(r["elapsed"] for r in top_level)

    by_start = sorted(_results, key=lambda r: r["start"])

    print()
    print("=" * 78)
    print("  TIMING SUMMARY  (wallclock, in pipeline order)")
    print("=" * 78)
    for r in by_start:
        elapsed = r["elapsed"]
        pct = (elapsed / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)         # 50% → 25 chars wide
        indent = "  " * r["depth"]
        prefix = "· " if r["depth"] > 0 else ""
        print(f"  {elapsed:7.2f}s  {pct:5.1f}%  {bar:25}  {indent}{prefix}{r['label']}")
    print("=" * 78)
    print(f"  {total:7.2f}s  total (sum of top-level steps)")
    print("=" * 78)
