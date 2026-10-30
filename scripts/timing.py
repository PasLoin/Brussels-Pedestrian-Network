from __future__ import annotations

import time
from contextlib import contextmanager

_results: list[dict] = []
_depth = [0]


@contextmanager
def step(label: str):
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
        bar = "█" * int(pct / 2)
        indent = "  " * r["depth"]
        prefix = "· " if r["depth"] > 0 else ""
        print(f"  {elapsed:7.2f}s  {pct:5.1f}%  {bar:25}  {indent}{prefix}{r['label']}")
    print("=" * 78)
    print(f"  {total:7.2f}s  total (sum of top-level steps)")
    print("=" * 78)
