#!/usr/bin/env python3
"""
Diagnostic: show what each address on a given street snaps to.

Usage (from repo root, after the pipeline has run the osmium steps):
    python3 scripts/debug_snap.py "Avenue de Messidor - Messidorlaan"

Prints for each address:
  - house number, even/odd side
  - nearest edge highway type and name
  - distance to that edge
  - which node it attaches to
"""

import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import warnings
warnings.filterwarnings("ignore")

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from build_graph import build_graph, _first_str
from sample_od import _extract_house_number

STREET = sys.argv[1] if len(sys.argv) > 1 else "Avenue de Messidor - Messidorlaan"
print(f"Diagnosing snapping for: {STREET}\n")

# ── Build graph ───────────────────────────────────────────────────────────────
gb = build_graph("routing_clean.osm")

node_xy = np.array([
    [gb.nodes_gdf.loc[n, "x"], gb.nodes_gdf.loc[n, "y"]]
    for n in gb.node_list
])

# ── Build edge index ──────────────────────────────────────────────────────────
valid_eids = []
valid_geoms = []
for eid, geom in enumerate(gb.edge_geoms):
    if geom is not None and not geom.is_empty and geom.length >= 0.5:
        valid_eids.append(eid)
        valid_geoms.append(geom)

edge_tree = STRtree(valid_geoms)
print(f"Valid edges: {len(valid_eids)}\n")

# ── Load addresses for this street ────────────────────────────────────────────
addr = gpd.read_file("addresses.geojson").to_crs("EPSG:31370")
addr["_num"] = addr.get("addr:housenumber", "").apply(_extract_house_number)
addr = addr.dropna(subset=["_num"])
addr["_num"] = addr["_num"].astype(int)

street_addr = addr[addr["addr:street"] == STREET].sort_values("_num")
print(f"Addresses found: {len(street_addr)}\n")

if street_addr.empty:
    print("No addresses found for this street. Try with exact OSM name.")
    sys.exit(1)

# ── Snap each address and report ──────────────────────────────────────────────
print(f"{'HN':>6}  {'Side':>4}  {'Dist':>7}  {'Highway':<16}  {'Edge name':<40}  {'Node'}")
print("─" * 100)

for _, row in street_addr.iterrows():
    hn = int(row["_num"])
    side = "even" if hn % 2 == 0 else "odd"
    pt = Point(row.geometry.x, row.geometry.y)

    nearest_vi = edge_tree.nearest(pt)
    nearest_geom = valid_geoms[nearest_vi]
    dist = nearest_geom.distance(pt)
    real_eid = valid_eids[nearest_vi]

    hw = gb.edge_highways[real_eid]
    name = gb.edge_names[real_eid]

    # Pick closest endpoint
    src_i, tgt_i = gb.edge_tuples[real_eid]
    sx, sy = node_xy[src_i]
    tx, ty = node_xy[tgt_i]
    d_src = (row.geometry.x - sx)**2 + (row.geometry.y - sy)**2
    d_tgt = (row.geometry.x - tx)**2 + (row.geometry.y - ty)**2
    node_idx = src_i if d_src <= d_tgt else tgt_i

    print(f"{hn:>6}  {side:>4}  {dist:>6.1f}m  {hw:<16}  {name:<40}  {node_idx}")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("── Top 5 closest edges for first even and first odd address ──")
for label, sub in [("First even", street_addr[street_addr["_num"] % 2 == 0]),
                   ("First odd",  street_addr[street_addr["_num"] % 2 == 1])]:
    if sub.empty:
        continue
    row = sub.iloc[0]
    pt = Point(row.geometry.x, row.geometry.y)
    # Query nearby edges
    candidates = edge_tree.query(pt.buffer(50))  # 50m radius
    results = []
    for ci in candidates:
        d = valid_geoms[ci].distance(pt)
        eid = valid_eids[ci]
        results.append((d, gb.edge_highways[eid], gb.edge_names[eid]))
    results.sort()

    print(f"\n{label}: HN {int(row['_num'])} at ({row.geometry.x:.0f}, {row.geometry.y:.0f})")
    for d, hw, nm in results[:5]:
        print(f"  {d:>6.1f}m  {hw:<16}  {nm}")
