#!/usr/bin/env python3
"""
Standalone benchmark — measure if ``igraph.Graph.get_shortest_paths``
parallelises on this runner's CPU.

The whole question driving this script: does igraph release the GIL
during multi-target Dijkstra?  If yes, a ``ThreadPoolExecutor`` will
divide the routing wallclock by ~N on N cores, for free.  If no,
threading is useless and we'd need to consider multiprocessing
(expensive: the graph has to be serialised to each worker).

What this script does
---------------------
1. Builds the routing graph from ``routing_raw.osm`` (must exist).
2. Picks ``BENCH_N_SOURCES`` random sources, each with
   ``BENCH_N_TARGETS`` random targets — roughly mirrors the real
   workload's multi-target shape (~50 targets per source).
3. Runs the workload once **sequentially** (baseline).
4. Re-runs it through a ``ThreadPoolExecutor`` with 1, 2, 4, and 8
   workers.  Records wallclock for each.
5. **Correctness check**: every parallel config must produce
   bit-for-bit identical edge paths to the sequential run.  Any
   divergence means igraph isn't thread-safe for concurrent reads
   on the same Graph object, which would be a deal-breaker.
6. Prints a verdict.

Usage
-----
::

    # Locally (after the main pipeline has produced routing_raw.osm)
    PYTHONPATH=scripts python3 scripts/bench_dijkstra.py

    # On CI: triggered by .github/workflows/bench.yml (workflow_dispatch)

Environment knobs
-----------------
* ``BENCH_N_SOURCES`` — number of random source nodes (default 1000)
* ``BENCH_N_TARGETS`` — random targets per source (default 50)
"""

from __future__ import annotations

import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

from clean_osm import clean_osm
from build_graph import build_graph

N_SOURCES = int(os.environ.get("BENCH_N_SOURCES", 1000))
N_TARGETS_PER_SOURCE = int(os.environ.get("BENCH_N_TARGETS", 50))
THREAD_COUNTS = [1, 2, 4, 8]


def _shortest_paths_batch(graph, source: int, targets: list[int]):
    """One unit of work: multi-target shortest paths from one source.

    Mirrors exactly what ``routing.route_pairs`` calls per source in
    the real pipeline.
    """
    return graph.get_shortest_paths(
        source, to=targets, weights="weight", output="epath",
    )


def _run_sequential(graph, work_items):
    """Run all work items in one thread.  Returns (paths_by_src, wallclock)."""
    paths_by_src: dict[int, tuple] = {}
    t0 = time.time()
    for src, targets in work_items:
        paths = _shortest_paths_batch(graph, src, targets)
        # Freeze as tuples of tuples for hashable / comparable storage.
        paths_by_src[src] = tuple(tuple(p) for p in paths)
    return paths_by_src, time.time() - t0


def _run_parallel(graph, work_items, n_threads: int):
    """Run all work items across n_threads.  Returns (paths_by_src, wallclock)."""
    paths_by_src: dict[int, tuple] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        future_to_src = {
            ex.submit(_shortest_paths_batch, graph, src, targets): src
            for src, targets in work_items
        }
        for future, src in future_to_src.items():
            paths = future.result()
            paths_by_src[src] = tuple(tuple(p) for p in paths)
    return paths_by_src, time.time() - t0


def main() -> None:
    # ── Build the routing graph ──────────────────────────────────────────
    # Uses exactly the same code path as the production pipeline so the
    # benchmark sees the same graph (vertex count, edge weights, etc).
    print("Cleaning OSM XML...")
    clean_osm("routing_raw.osm", "routing_clean.osm")

    print("\nBuilding graph...")
    t_build = time.time()
    gb = build_graph("routing_clean.osm")
    print(f"  Graph built in {time.time() - t_build:.1f}s")

    g = gb.graph
    n_vertices = g.vcount()
    print(f"  Graph: {n_vertices} vertices, {g.ecount()} edges")

    # ── Build the workload ───────────────────────────────────────────────
    # Same seed → reproducible across runs, so any wallclock differences
    # are due to thread count or runner noise, not workload variance.
    random.seed(42)
    work_items: list[tuple[int, list[int]]] = []
    for _ in range(N_SOURCES):
        src = random.randrange(n_vertices)
        targets = [random.randrange(n_vertices) for _ in range(N_TARGETS_PER_SOURCE)]
        work_items.append((src, targets))

    n_queries = N_SOURCES * N_TARGETS_PER_SOURCE
    print(f"\nWorkload: {N_SOURCES} sources × {N_TARGETS_PER_SOURCE} targets "
          f"= {n_queries} pair queries")

    # ── Warm-up ──────────────────────────────────────────────────────────
    # First call typically has extra cost (JIT-like effects in pyc, page
    # faults, igraph internal caches).  Run one query throw-away.
    _shortest_paths_batch(g, work_items[0][0], work_items[0][1])

    # ── Sequential baseline ──────────────────────────────────────────────
    print("\nRunning sequential baseline...")
    seq_paths, seq_time = _run_sequential(g, work_items)
    print(f"  Sequential: {seq_time:.2f}s")

    # ── Parallel runs ────────────────────────────────────────────────────
    results: list[tuple[str, float, float, bool]] = [
        ("sequential", seq_time, 1.0, True),
    ]
    for n in THREAD_COUNTS:
        label = f"{n} thread{'s' if n > 1 else ''}"
        print(f"\nRunning with {label}...")
        par_paths, par_time = _run_parallel(g, work_items, n)
        speedup = seq_time / par_time if par_time > 0 else 0.0
        # Strict correctness: exact same edge paths for every (src, tgt).
        # If this fails, igraph isn't safe for concurrent reads.
        correct = (par_paths == seq_paths)
        results.append((label, par_time, speedup, correct))
        print(f"  {label}: {par_time:.2f}s | "
              f"speedup {speedup:.2f}× | correct: {correct}")

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  DIJKSTRA PARALLELISATION BENCHMARK")
    print(f"  {N_SOURCES} sources × {N_TARGETS_PER_SOURCE} targets "
          f"({n_queries} queries)")
    print(f"  Graph: {n_vertices} vertices, {g.ecount()} edges")
    print(f"  Runner: {os.cpu_count()} logical CPUs")
    print("=" * 70)
    print(f"  {'Config':<16} {'Wallclock':>12} {'Speedup':>10} {'Correct':>10}")
    print("-" * 70)
    for name, t, sp, ok in results:
        ok_str = "✓" if ok else "✗ MISMATCH"
        print(f"  {name:<16} {t:>11.2f}s {sp:>9.2f}× {ok_str:>10}")
    print("=" * 70)

    # ── Verdict ──────────────────────────────────────────────────────────
    par_results = results[1:]  # skip the sequential baseline
    best_speedup = max(sp for _, _, sp, _ in par_results)
    all_correct = all(ok for _, _, _, ok in par_results)

    print()
    if not all_correct:
        print("✗ VERDICT: igraph.get_shortest_paths is NOT thread-safe on")
        print("  this graph — parallel runs returned different paths than")
        print("  sequential.  Threading is OUT.  Investigate multiprocessing.")
    elif best_speedup >= 2.5:
        print(f"✓ VERDICT: Solid parallel speedup — best {best_speedup:.2f}×.")
        print("  igraph releases the GIL during Dijkstra.")
        print("  Refactoring route_pairs with a ThreadPoolExecutor would")
        print(f"  cut routing wallclock by roughly {(1 - 1/best_speedup) * 100:.0f}%.")
    elif best_speedup >= 1.5:
        print(f"~ VERDICT: Modest speedup — best {best_speedup:.2f}×.")
        print("  Some GIL release, but contention or other bottlenecks limit gains.")
        print("  Threading would help but less than hoped.  Worth doing if the")
        print("  refactor is cheap; otherwise consider other optimisations.")
    else:
        print(f"✗ VERDICT: No meaningful speedup — best {best_speedup:.2f}×.")
        print("  igraph appears to hold the GIL during get_shortest_paths.")
        print("  Threading is out.  Options left:")
        print("    1. Multiprocessing with graph serialisation (expensive).")
        print("    2. Reduce work — fewer OD sources, larger MIN_OD_DISTANCE.")
        print("    3. Switch routing library (networkit, graph-tool — risky).")


if __name__ == "__main__":
    main()
