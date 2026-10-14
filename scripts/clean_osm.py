from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Sequence

from config import BLOCKED_BARRIER_RULES, FOOT_ALLOWED, FOOT_FORBIDDEN


def _find_blocked_nodes(root: ET.Element) -> set[str]:
    rules = set(BLOCKED_BARRIER_RULES)
    blocked: set[str] = set()
    for node in root.findall("node"):
        tags = {t.get("k"): t.get("v") for t in node.findall("tag")}
        barrier = tags.get("barrier", "")
        if not barrier:
            continue
        foot = tags.get("foot", "").lower()
        if foot in FOOT_FORBIDDEN:
            blocked.add(node.get("id"))
        elif (barrier, tags.get("access", "")) in rules and foot not in FOOT_ALLOWED:
            blocked.add(node.get("id"))
    return blocked


def _split_way_at_barriers(
    way: ET.Element,
    root: ET.Element,
    blocked: set[str],
    id_counter: list[int],
) -> tuple[int, int]:
    nds = way.findall("nd")
    refs = [nd.get("ref") for nd in nds]
    blocked_indices = [i for i, ref in enumerate(refs) if ref in blocked]
    if not blocked_indices:
        return 0, 0

    way_tags = [(t.get("k"), t.get("v")) for t in way.findall("tag")]

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

    for nd in nds:
        way.remove(nd)
    for ref in segments[0]:
        ET.SubElement(way, "nd", attrib={"ref": ref})

    for seg in segments[1:]:
        new_way = ET.SubElement(root, "way", attrib={"id": str(id_counter[0])})
        id_counter[0] -= 1
        for ref in seg:
            ET.SubElement(new_way, "nd", attrib={"ref": ref})
        for k, v in way_tags:
            ET.SubElement(new_way, "tag", attrib={"k": k, "v": v})

    return 1, 0


def _remove_dangling_ways(root: ET.Element) -> int:
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
    print("Cleaning OSM XML...")
    tree = ET.parse(input_path)
    root = tree.getroot()

    blocked = _find_blocked_nodes(root)
    print(f"  Blocked barrier nodes: {len(blocked)}")

    id_counter = [-1]
    total_split = total_removed = 0

    for way in list(root.findall("way")):
        s, r = _split_way_at_barriers(way, root, blocked, id_counter)
        total_split += s
        total_removed += r

    print(f"  Ways split: {total_split} | removed: {total_removed}")

    dangling = _remove_dangling_ways(root)
    print(f"  Ways removed (missing nodes): {dangling}")

    tree.write(output_path)
