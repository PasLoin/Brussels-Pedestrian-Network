#!/usr/bin/env python3
"""
Diagnostic: show what each address on a given street snaps to.

Usage (from repo root, after the pipeline has run the osmium steps):
    python3 scripts/debug_snap.py "Avenue de Messidor - Messidorlaan"
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import warnings
warnings.filterwarnings("ignore")

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from build_graph import build_graph
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

# ── Load addresses for this street ────────────────────────────────────────────
addr = gpd.read_file("addresses.geojson").to_crs("EPSG:31370")
# Convert polygon geometries (building outlines) to centroids
addr["geometry"] = addr.geometry.apply(
    lambda g: g.centroid if g.geom_type != "Point" else g
)
street_addr = addr[addr["addr:street"] == STREET].copy()
street_addr["_raw_hn"] = street_addr.get("addr:housenumber", "").astype(str)
street_addr["_num"] = street_addr["_raw_hn"].apply(_extract_house_number)
street_addr = street_addr.dropna(subset=["_num"])
street_addr["_num"] = street_addr["_num"].astype(int)
street_addr = street_addr.sort_values("_num")

print(f"Addresses found: {len(street_addr)}")
print(f"  Even (pair): {len(street_addr[street_addr['_num'] % 2 == 0])}")
print(f"  Odd (impair): {len(street_addr[street_addr['_num'] % 2 == 1])}")
print()

if street_addr.empty:
    print("No addresses found.")
    sys.exit(1)

# ── Snap each address and report ──────────────────────────────────────────────
print(f"{'Raw HN':>8}  {'#':>4}  {'Side':>4}  {'Dist':>7}  {'Highway':<16}  {'Edge name':<40}  {'Node'}")
print("─" * 120)

for _, row in street_addr.iterrows():
    raw_hn = row["_raw_hn"]
    hn = int(row["_num"])
    side = "even" if hn % 2 == 0 else "odd"
    pt = Point(row.geometry.x, row.geometry.y)

    nearest_vi = edge_tree.nearest(pt)
    nearest_geom = valid_geoms[nearest_vi]
    dist = nearest_geom.distance(pt)
    real_eid = valid_eids[nearest_vi]

    hw = gb.edge_highways[real_eid]
    name = gb.edge_names[real_eid]

    src_i, tgt_i = gb.edge_tuples[real_eid]
    sx, sy = node_xy[src_i]
    tx, ty = node_xy[tgt_i]
    d_src = (row.geometry.x - sx)**2 + (row.geometry.y - sy)**2
    d_tgt = (row.geometry.x - tx)**2 + (row.geometry.y - ty)**2
    node_idx = src_i if d_src <= d_tgt else tgt_i

    print(f"{raw_hn:>8}  {hn:>4}  {side:>4}  {dist:>6.1f}m  {hw:<16}  {name:<40}  {node_idx}")

# ── Top 5 edges for sample addresses ─────────────────────────────────────────
print()
print("── Top 5 closest edges for sample even and sample odd ──")
for label, sub in [("Even (pair)", street_addr[street_addr["_num"] % 2 == 0]),
                   ("Odd (impair)", street_addr[street_addr["_num"] % 2 == 1])]:
    if sub.empty:
        print(f"\n{label}: no addresses")
        continue
    row = sub.iloc[len(sub) // 2]
    pt = Point(row.geometry.x, row.geometry.y)
    candidates = edge_tree.query(pt.buffer(50))
    results = []
    for ci in candidates:
        d = valid_geoms[ci].distance(pt)
        eid = valid_eids[ci]
        results.append((d, gb.edge_highways[eid], gb.edge_names[eid]))
    results.sort()

    print(f"\n{label}: HN {row['_raw_hn']} at ({row.geometry.x:.0f}, {row.geometry.y:.0f})")
    for d, hw, nm in results[:5]:
        print(f"  {d:>6.1f}m  {hw:<16}  {nm}")
