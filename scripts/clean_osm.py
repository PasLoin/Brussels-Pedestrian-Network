"""
Step 1 — Clean OSM XML and split ways at blocked barriers.

Reads ``routing_raw.osm`` and writes ``routing_clean.osm``.

Why this step exists
--------------------
Some OSM nodes represent physical barriers (e.g. a locked gate with
``access=private``).  The raw graph treats ways as continuous, so the
router could traverse *through* such barriers.  This module:

1. Identifies barrier nodes whose (barrier, access) pair is in the
   block-list (see :pydata:`config.BLOCKED_BARRIER_RULES`).
2. Splits every way that passes through a blocked node into segments
   that stop *before* the barrier.
3. Removes ways whose *all* referenced nodes are missing from the file
   (a rare artefact of regional extracts).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Sequence

from config import BLOCKED_BARRIER_RULES


def _find_blocked_nodes(root: ET.Element) -> set[str]:
    """Return OSM node ids that match a blocked barrier rule."""
    rules = set(BLOCKED_BARRIER_RULES)
    blocked: set[str] = set()
    for node in root.findall("node"):
        tags = {t.get("k"): t.get("v") for t in node.findall("tag")}
        if (tags.get("barrier", ""), tags.get("access", "")) in rules:
            blocked.add(node.get("id"))
    return blocked


def _split_way_at_barriers(
    way: ET.Element,
    root: ET.Element,
    blocked: set[str],
    id_counter: list[int],
) -> tuple[int, int]:
    """Split *way* at blocked nodes, mutating *root* in place.

    Returns (ways_split, ways_removed) counts.
    """
    nds = way.findall("nd")
    refs = [nd.get("ref") for nd in nds]
    blocked_indices = [i for i, ref in enumerate(refs) if ref in blocked]
    if not blocked_indices:
        return 0, 0

    # Collect way tags so we can copy them to new segments
    way_tags = [(t.get("k"), t.get("v")) for t in way.findall("tag")]

    # Build continuous segments that skip the blocked node itself
    segments: list[list[str]] = []
    prev = 0
    for bi in blocked_indices:
        if bi > prev:
            segments.append(refs[prev:bi])
        prev = bi + 1
    if prev < len(refs):
        segments.append(refs[prev:])
    segments = [s for s in segments if len(s) >= 2]

    if not segments:
        root.remove(way)
        return 0, 1

    # Rewrite the original way with the first segment
    for nd in nds:
        way.remove(nd)
    for ref in segments[0]:
        ET.SubElement(way, "nd", attrib={"ref": ref})

    # Create new <way> elements for remaining segments
    for seg in segments[1:]:
        new_way = ET.SubElement(root, "way", attrib={"id": str(id_counter[0])})
        id_counter[0] -= 1
        for ref in seg:
            ET.SubElement(new_way, "nd", attrib={"ref": ref})
        for k, v in way_tags:
            ET.SubElement(new_way, "tag", attrib={"k": k, "v": v})

    return 1, 0


def _remove_dangling_ways(root: ET.Element) -> int:
    """Remove ways that reference nodes not present in the file."""
    node_ids = {n.get("id") for n in root.findall("node")}
    removed = 0
    for way in list(root.findall("way")):
        refs = {nd.get("ref") for nd in way.findall("nd")}
        if not refs.issubset(node_ids):
            root.remove(way)
            removed += 1
    return removed


def clean_osm(input_path: str = "routing_raw.osm",
              output_path: str = "routing_clean.osm") -> None:
    """Read *input_path*, clean it, and write *output_path*."""
    print("Cleaning OSM XML...")
    tree = ET.parse(input_path)
    root = tree.getroot()

    blocked = _find_blocked_nodes(root)
    print(f"  Blocked barrier nodes: {len(blocked)}")

    id_counter = [-1]          # mutable counter shared across calls
    total_split = total_removed = 0

    for way in list(root.findall("way")):
        s, r = _split_way_at_barriers(way, root, blocked, id_counter)
        total_split += s
        total_removed += r

    print(f"  Ways split: {total_split} | removed: {total_removed}")

    dangling = _remove_dangling_ways(root)
    print(f"  Ways removed (missing nodes): {dangling}")

    tree.write(output_path)
