#!/usr/bin/env python3
"""
Compute lightweight historical statistics for one OSM PBF snapshot.

Reads a single ``.pbf`` extract (typically a monthly snapshot from
``PasLoin/Osm-python-analyse_Belgium/pbf_analyse/history``) and emits a
JSON record summarising:

* Length per highway type (footway, pedestrian, path, cycleway,
  residential, …) in kilometres.
* Counts of pedestrian-relevant nodes (``highway=crossing``,
  ``highway=elevator``, ``amenity=elevator``).
* Counts of pedestrian-relevant ways tagged for QA
  (``footway=crossing``, ``footway=sidewalk``, sidewalk attribute tags,
  ``surface``, ``smoothness``, ``tactile_paving``).
* Derived quality ratios (e.g. ``crossings_tagged_pct``).

What this script intentionally does NOT do
------------------------------------------
* No OSMnx graph construction.
* No routing or simulation.
* No sidewalk-gap geometric analysis.

The motivation is speed: the evolution page reads ~24 monthly snapshots,
and full-pipeline runs (~10 min each) are infeasible.  This script runs
in well under a minute per snapshot by streaming the PBF with osmium.

Append-mode merging
-------------------
The script emits one record (``{date, ...stats}``) per invocation.  The
caller (``history.yml``) is responsible for merging it into an
accumulating ``history.json`` keyed by date.

Usage
-----
::

    python3 scripts/compute_history.py path/to/snapshot.pbf YYYY-MM-DD \\
        > snapshot_stats.json

The date is taken from the second argument rather than parsed from the
filename — the filename pattern ``DD_MM_YYYY_brussels_capital_region.pbf``
uses European day-first ordering, which is fragile; the caller knows
the date with certainty.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

import osmium
from pyproj import Transformer

# Highway types whose km we report individually in the evolution chart.
# Anything outside this list is bucketed into ``other_road_km``.
_TRACKED_HIGHWAY_TYPES = frozenset({
    # Pedestrian-dedicated
    "footway", "pedestrian", "path", "living_street", "steps",
    "elevator", "cycleway",
    # Roads pedestrians walk along
    "residential", "service", "unclassified",
    "tertiary", "tertiary_link",
    "secondary", "secondary_link",
    "primary", "primary_link",
    "track",
})

# Pedestrian infrastructure used for ratio metrics.
_PED_HIGHWAY_TYPES = frozenset({
    "footway", "pedestrian", "path", "living_street", "steps", "elevator",
})

# Road types where we expect sidewalk documentation.
_ROAD_TYPES_SIDEWALK_EXPECTED = frozenset({
    "residential", "unclassified",
    "tertiary", "tertiary_link",
    "secondary", "secondary_link",
    "primary", "primary_link",
})


class _BrusselsStatsHandler(osmium.SimpleHandler):
    """Stream-process the PBF and accumulate stats in memory.

    Stays well under a few MB of RAM even for the full Brussels extract
    — we only keep counters and per-type sums.
    """

    def __init__(self) -> None:
        super().__init__()
        # Belgian Lambert 72 — metric and accurate for Brussels.
        self._proj = Transformer.from_crs("EPSG:4326", "EPSG:31370", always_xy=True)

        # ── Counters keyed by highway tag ────────────────────────────────
        self.km_by_highway: dict[str, float] = defaultdict(float)
        self.ways_by_highway: dict[str, int] = defaultdict(int)

        # ── Pedestrian-relevant node counters ────────────────────────────
        self.n_crossing_nodes        = 0
        self.n_crossing_continuous   = 0
        self.n_crossing_marked       = 0
        self.n_crossing_unmarked     = 0
        self.n_crossing_signals      = 0
        self.n_crossing_with_tactile = 0
        self.n_elevator_nodes        = 0

        # ── Pedestrian-relevant way counters ─────────────────────────────
        self.n_footway_ways        = 0
        self.n_footway_sidewalk    = 0
        self.n_footway_crossing    = 0   # = number of crossing ways
        self.n_footway_link        = 0
        self.n_footway_with_surface    = 0
        self.n_footway_with_smoothness = 0

        # ── Sidewalk attribute tags on roads ─────────────────────────────
        # We count per-way (binary), not per side.  A way with
        # sidewalk:both=separate is one ``sw_separate`` count.
        self.n_road_ways                  = 0  # ways in expected-sidewalk types
        self.n_road_sidewalk_any_tag      = 0
        self.n_road_sidewalk_separate     = 0
        self.n_road_sidewalk_yes_or_both  = 0
        self.n_road_sidewalk_no_explicit  = 0
        self.n_road_sidewalk_partial      = 0

    # ── osmium callbacks ─────────────────────────────────────────────────

    def node(self, n) -> None:
        # Pedestrian node-level features
        tags = n.tags
        if tags.get("highway") == "crossing":
            self.n_crossing_nodes += 1
            if tags.get("crossing:continuous") == "yes":
                self.n_crossing_continuous += 1
            xing = tags.get("crossing", "")
            if xing == "marked":
                self.n_crossing_marked += 1
            elif xing == "unmarked":
                self.n_crossing_unmarked += 1
            elif xing == "traffic_signals":
                self.n_crossing_signals += 1
            if tags.get("tactile_paving") in ("yes", "contrasted", "primitive"):
                self.n_crossing_with_tactile += 1
        if tags.get("highway") == "elevator" or tags.get("amenity") == "elevator":
            self.n_elevator_nodes += 1

    def way(self, w) -> None:
        tags = w.tags
        hw = tags.get("highway")
        if not hw:
            return

        # ── Length (only for tracked types — others would just bloat) ────
        if hw in _TRACKED_HIGHWAY_TYPES:
            length_m = self._way_length_m(w)
            self.km_by_highway[hw] += length_m / 1000.0
            self.ways_by_highway[hw] += 1

        # ── Footway sub-tag breakdown ────────────────────────────────────
        if hw == "footway":
            self.n_footway_ways += 1
            sub = tags.get("footway", "")
            if sub == "sidewalk":
                self.n_footway_sidewalk += 1
            elif sub == "crossing":
                self.n_footway_crossing += 1
            elif sub == "link":
                self.n_footway_link += 1
            if tags.get("surface"):
                self.n_footway_with_surface += 1
            if tags.get("smoothness"):
                self.n_footway_with_smoothness += 1

        # ── Sidewalk attribute tags on eligible roads ────────────────────
        if hw in _ROAD_TYPES_SIDEWALK_EXPECTED:
            self.n_road_ways += 1
            sw   = tags.get("sidewalk", "").lower()
            sw_b = tags.get("sidewalk:both", "").lower()
            sw_l = tags.get("sidewalk:left", "").lower()
            sw_r = tags.get("sidewalk:right", "").lower()

            has_any = any([sw, sw_b, sw_l, sw_r])
            if has_any:
                self.n_road_sidewalk_any_tag += 1

            # Classification matches sidewalk_roads.py's logic at a high level.
            if sw == "separate" or sw_b == "separate" or (sw_l == "separate" and sw_r == "separate"):
                self.n_road_sidewalk_separate += 1
            elif sw in ("yes", "both") or sw_b in ("yes", "both"):
                self.n_road_sidewalk_yes_or_both += 1
            elif sw == "no" or sw_b == "no":
                self.n_road_sidewalk_no_explicit += 1
            elif (sw_l and not sw_r) or (sw_r and not sw_l):
                self.n_road_sidewalk_partial += 1

    # ── Internal helpers ─────────────────────────────────────────────────

    def _way_length_m(self, w) -> float:
        """Approximate way length in metres via EPSG:31370 reprojection.

        osmium nodes-of-way carries lat/lon — we batch-project and sum
        consecutive segment lengths.  Skips ways with fewer than 2 nodes
        or missing coordinates.
        """
        coords = []
        for nd in w.nodes:
            if not nd.location.valid():
                # Member node not in extract.  Common at extract edges.
                continue
            coords.append((nd.location.lon, nd.location.lat))
        if len(coords) < 2:
            return 0.0
        lons, lats = zip(*coords)
        xs, ys = self._proj.transform(lons, lats)
        total = 0.0
        for i in range(1, len(xs)):
            dx = xs[i] - xs[i - 1]
            dy = ys[i] - ys[i - 1]
            total += math.hypot(dx, dy)
        return total


def _build_record(date_iso: str, h: _BrusselsStatsHandler) -> dict:
    """Build the JSON record for one snapshot.

    Lengths are rounded to one decimal place — sub-metric precision is
    meaningless given the source extract granularity and looks noisy in
    charts.  Ratios use 2 decimals (4-digit precision is illusory here).
    """
    km_by_hw = {k: round(v, 1) for k, v in h.km_by_highway.items()}

    # Aggregate category sums
    ped_km  = sum(v for k, v in km_by_hw.items() if k in _PED_HIGHWAY_TYPES)
    road_km = sum(v for k, v in km_by_hw.items() if k in _ROAD_TYPES_SIDEWALK_EXPECTED)
    cyc_km  = km_by_hw.get("cycleway", 0.0)

    # ── Derived ratios ────────────────────────────────────────────────────
    # ``crossing_tagged_pct`` measures the fraction of crossing *ways*
    # (footway=crossing) per crossing *node* (highway=crossing).
    # A healthy network has both: nodes capture location, ways the
    # routable geometry.  Anything well under 1.0 indicates many nodes
    # are not yet connected to a crossing way.
    def _safe_div(num: float, den: float) -> float:
        return round(num / den * 100, 2) if den > 0 else 0.0

    sw_doc = (
        h.n_road_sidewalk_separate
        + h.n_road_sidewalk_yes_or_both
        + h.n_road_sidewalk_no_explicit
    )

    return {
        "date": date_iso,
        # ── Network length ───────────────────────────────────────────────
        "km_by_highway":    km_by_hw,
        "ways_by_highway":  dict(h.ways_by_highway),
        "ped_km":           round(ped_km, 1),
        "road_km":          round(road_km, 1),
        "cycleway_km":      round(cyc_km, 1),

        # ── Node counters ────────────────────────────────────────────────
        "crossing_nodes":         h.n_crossing_nodes,
        "crossing_continuous":    h.n_crossing_continuous,
        "crossing_marked":        h.n_crossing_marked,
        "crossing_unmarked":      h.n_crossing_unmarked,
        "crossing_signals":       h.n_crossing_signals,
        "crossing_with_tactile":  h.n_crossing_with_tactile,
        "elevator_nodes":         h.n_elevator_nodes,

        # ── Way counters ─────────────────────────────────────────────────
        "footway_ways":          h.n_footway_ways,
        "footway_sidewalk":      h.n_footway_sidewalk,
        "footway_crossing":      h.n_footway_crossing,
        "footway_link":          h.n_footway_link,
        "footway_with_surface":     h.n_footway_with_surface,
        "footway_with_smoothness":  h.n_footway_with_smoothness,

        # ── Sidewalk tag breakdown on roads ──────────────────────────────
        "road_ways":                   h.n_road_ways,
        "road_sidewalk_any_tag":       h.n_road_sidewalk_any_tag,
        "road_sidewalk_separate":      h.n_road_sidewalk_separate,
        "road_sidewalk_yes_or_both":   h.n_road_sidewalk_yes_or_both,
        "road_sidewalk_no_explicit":   h.n_road_sidewalk_no_explicit,
        "road_sidewalk_partial":       h.n_road_sidewalk_partial,

        # ── Derived percentages ──────────────────────────────────────────
        "crossing_tagged_pct":      _safe_div(h.n_footway_crossing, h.n_crossing_nodes),
        "sidewalk_documented_pct":  _safe_div(sw_doc, h.n_road_ways),
        "sidewalk_separate_pct":    _safe_div(h.n_road_sidewalk_separate, h.n_road_ways),
        "footway_surface_pct":      _safe_div(h.n_footway_with_surface, h.n_footway_ways),
        "footway_smoothness_pct":   _safe_div(h.n_footway_with_smoothness, h.n_footway_ways),
        "tactile_paving_pct":       _safe_div(h.n_crossing_with_tactile, h.n_crossing_nodes),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: compute_history.py <pbf_path> <YYYY-MM-DD>",
            file=sys.stderr,
        )
        return 1

    pbf_path = sys.argv[1]
    date_iso = sys.argv[2]

    handler = _BrusselsStatsHandler()
    # locations=True lets osmium attach lon/lat to way-member nodes so
    # ``_way_length_m`` can compute lengths in a single streaming pass.
    handler.apply_file(pbf_path, locations=True)

    record = _build_record(date_iso, handler)
    json.dump(record, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
