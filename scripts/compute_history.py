#!/usr/bin/env python3
"""
Compute lightweight historical statistics for one OSM PBF snapshot.

Reads a single ``.pbf`` extract and emits a JSON record summarising
pedestrian infrastructure statistics.

This version uses ``osmium export`` via subprocess to avoid the ``pyosmium``
dependency which can be problematic on newer Python versions.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import defaultdict

from pyproj import Transformer

# Highway types whose km we report individually in the evolution chart.
_TRACKED_HIGHWAY_TYPES = frozenset({
    "footway", "pedestrian", "path", "living_street", "steps",
    "elevator", "cycleway",
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


class _BrusselsStatsHandler:
    def __init__(self) -> None:
        # Belgian Lambert 72 — metric and accurate for Brussels.
        self._proj = Transformer.from_crs("EPSG:4326", "EPSG:31370", always_xy=True)

        self.km_by_highway: dict[str, float] = defaultdict(float)
        self.ways_by_highway: dict[str, int] = defaultdict(int)

        self.n_crossing_nodes        = 0
        self.n_crossing_continuous   = 0
        self.n_crossing_marked       = 0
        self.n_crossing_unmarked     = 0
        self.n_crossing_signals      = 0
        self.n_crossing_with_tactile = 0
        self.n_elevator_nodes        = 0

        self.n_footway_ways        = 0
        self.n_footway_sidewalk    = 0
        self.n_footway_crossing    = 0
        self.n_footway_link        = 0
        self.n_footway_with_surface    = 0
        self.n_footway_with_smoothness = 0

        self.n_road_ways                  = 0
        self.n_road_sidewalk_any_tag      = 0
        self.n_road_sidewalk_separate     = 0
        self.n_road_sidewalk_yes_or_both  = 0
        self.n_road_sidewalk_no_explicit  = 0
        self.n_road_sidewalk_partial      = 0

    def process_feature(self, feature: dict) -> None:
        geom = feature.get("geometry")
        if not geom:
            return
        
        props = feature.get("properties", {})
        gtype = geom.get("type")

        if gtype == "Point":
            self._handle_node(props)
        elif gtype == "LineString":
            self._handle_way(props, geom.get("coordinates", []))

    def _handle_node(self, tags: dict) -> None:
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

    def _handle_way(self, tags: dict, coords: list[list[float]]) -> None:
        hw = tags.get("highway")
        if not hw:
            return

        if hw in _TRACKED_HIGHWAY_TYPES:
            length_m = self._way_length_m(coords)
            self.km_by_highway[hw] += length_m / 1000.0
            self.ways_by_highway[hw] += 1

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

        if hw in _ROAD_TYPES_SIDEWALK_EXPECTED:
            self.n_road_ways += 1
            sw   = str(tags.get("sidewalk", "")).lower()
            sw_b = str(tags.get("sidewalk:both", "")).lower()
            sw_l = str(tags.get("sidewalk:left", "")).lower()
            sw_r = str(tags.get("sidewalk:right", "")).lower()

            has_any = any([sw, sw_b, sw_l, sw_r])
            if has_any:
                self.n_road_sidewalk_any_tag += 1

            if sw == "separate" or sw_b == "separate" or (sw_l == "separate" and sw_r == "separate"):
                self.n_road_sidewalk_separate += 1
            elif sw in ("yes", "both") or sw_b in ("yes", "both"):
                self.n_road_sidewalk_yes_or_both += 1
            elif sw == "no" or sw_b == "no":
                self.n_road_sidewalk_no_explicit += 1
            elif (sw_l and not sw_r) or (sw_r and not sw_l):
                self.n_road_sidewalk_partial += 1

    def _way_length_m(self, coords: list[list[float]]) -> float:
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
    km_by_hw = {k: round(v, 1) for k, v in h.km_by_highway.items()}
    ped_km  = sum(v for k, v in km_by_hw.items() if k in _PED_HIGHWAY_TYPES)
    road_km = sum(v for k, v in km_by_hw.items() if k in _ROAD_TYPES_SIDEWALK_EXPECTED)
    cyc_km  = km_by_hw.get("cycleway", 0.0)

    def _safe_div(num: float, den: float) -> float:
        return round(num / den * 100, 2) if den > 0 else 0.0

    sw_doc = (
        h.n_road_sidewalk_separate
        + h.n_road_sidewalk_yes_or_both
        + h.n_road_sidewalk_no_explicit
    )

    return {
        "date": date_iso,
        "km_by_highway":    km_by_hw,
        "ways_by_highway":  dict(h.ways_by_highway),
        "ped_km":           round(ped_km, 1),
        "road_km":          round(road_km, 1),
        "cycleway_km":      round(cyc_km, 1),
        "crossing_nodes":         h.n_crossing_nodes,
        "crossing_continuous":    h.n_crossing_continuous,
        "crossing_marked":        h.n_crossing_marked,
        "crossing_unmarked":      h.n_crossing_unmarked,
        "crossing_signals":       h.n_crossing_signals,
        "crossing_with_tactile":  h.n_crossing_with_tactile,
        "elevator_nodes":         h.n_elevator_nodes,
        "footway_ways":          h.n_footway_ways,
        "footway_sidewalk":      h.n_footway_sidewalk,
        "footway_crossing":      h.n_footway_crossing,
        "footway_link":          h.n_footway_link,
        "footway_with_surface":     h.n_footway_with_surface,
        "footway_with_smoothness":  h.n_footway_with_smoothness,
        "road_ways":                   h.n_road_ways,
        "road_sidewalk_any_tag":       h.n_road_sidewalk_any_tag,
        "road_sidewalk_separate":      h.n_road_sidewalk_separate,
        "road_sidewalk_yes_or_both":   h.n_road_sidewalk_yes_or_both,
        "road_sidewalk_no_explicit":   h.n_road_sidewalk_no_explicit,
        "road_sidewalk_partial":       h.n_road_sidewalk_partial,
        "crossing_tagged_pct":      _safe_div(h.n_footway_crossing, h.n_crossing_nodes),
        "sidewalk_documented_pct":  _safe_div(sw_doc, h.n_road_ways),
        "sidewalk_separate_pct":    _safe_div(h.n_road_sidewalk_separate, h.n_road_ways),
        "footway_surface_pct":      _safe_div(h.n_footway_with_surface, h.n_footway_ways),
        "footway_smoothness_pct":   _safe_div(h.n_footway_with_smoothness, h.n_footway_ways),
        "tactile_paving_pct":       _safe_div(h.n_crossing_with_tactile, h.n_crossing_nodes),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: compute_history.py <pbf_path> <YYYY-MM-DD>", file=sys.stderr)
        return 1

    pbf_path = sys.argv[1]
    date_iso = sys.argv[2]

    handler = _BrusselsStatsHandler()

    cmd = [
        "osmium", "export", pbf_path,
        "--output-format=geojsonseq",
        "--geometry-types=point,linestring"
    ]
    
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1) as proc:
        if proc.stdout:
            for line in proc.stdout:
                # geojsonseq uses RS (0x1e) as record separator
                line = line.lstrip('\x1e').strip()
                if not line:
                    continue
                try:
                    feature = json.loads(line)
                    handler.process_feature(feature)
                except json.JSONDecodeError:
                    continue
        
        exit_code = proc.wait()
        if exit_code != 0:
            print(f"osmium export failed with exit code {exit_code}", file=sys.stderr)
            return exit_code

    record = _build_record(date_iso, handler)
    json.dump(record, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
