import json
import re
from pathlib import Path

import build_site

ROOT = Path(__file__).resolve().parent.parent

STATS_HTML_PATHS = frozenset({
    "graph.edges",
    "graph.nodes",
    "missing_crossings.crossing_continuous",
    "missing_crossings.crossing_nodes_found",
    "missing_crossings.missing_crossing_tag",
    "missing_crossings.missing_crossing_way",
    "missing_crossings.on_excluded_way",
    "missing_crossings.wrong_crossing_tag",
    "network.km_by_category.cycleway_foot_yes",
    "network.km_by_category.cycleway_no_foot",
    "network.km_by_category.pedestrian",
    "network.km_by_category.road",
    "network.km_by_highway",
    "network.total_km",
    "od_sampling.od_points",
    "routing.avg_distance_m",
    "routing.routed_trips",
    "routing.routing_time_s",
    "sidewalk_gaps.both_length_km",
    "sidewalk_gaps.both_sides",
    "sidewalk_gaps.footway_filter.kept",
    "sidewalk_gaps.footway_filter.kept_crossing",
    "sidewalk_gaps.footway_filter.kept_cycleway_foot",
    "sidewalk_gaps.footway_filter.kept_link",
    "sidewalk_gaps.footway_filter.kept_pedestrian",
    "sidewalk_gaps.footway_filter.kept_sidewalk",
    "sidewalk_gaps.footway_filter.kept_traffic_island",
    "sidewalk_gaps.gap_length_km",
    "sidewalk_gaps.neither_length_km",
    "sidewalk_gaps.neither_side",
    "sidewalk_gaps.one_side_gap",
    "sidewalk_gaps.roads_analysed",
    "sidewalk_gaps.skipped_no_sidewalk",
    "sidewalk_roads.by_status",
    "sidewalk_roads.km_by_status",
    "sidewalk_roads.pct_by_status.documented",
    "sidewalk_roads.pct_by_status.partial",
    "sidewalk_roads.pct_by_status.separate",
    "sidewalk_roads.pct_by_status.unknown",
    "sidewalk_roads.pct_by_status.yes",
    "sidewalk_roads.separate_all_sides.pct",
    "sidewalk_roads.total_road_ways",
})

APP_STATS_PATHS = frozenset({
    "routing.avg_distance_m",
    "routing.routed_trips",
})

HISTORY_PATHS = frozenset({
    "crossing_continuous", "crossing_nodes", "crossing_tagged_pct", "cycleway_km",
    "footway_crossing", "footway_link", "footway_no_subtag", "footway_other",
    "footway_sidewalk", "footway_smoothness_pct", "footway_surface_pct",
    "footway_traffic_island", "footway_ways", "km_by_highway", "ped_km", "road_km",
    "road_sidewalk_no_explicit", "road_sidewalk_partial", "road_sidewalk_separate",
    "road_sidewalk_yes_or_both", "road_ways", "sidewalk_documented_pct",
    "sidewalk_separate_pct", "tactile_paving_pct",
})

LAYER_PROPS = {
    "highways": frozenset({"highway", "amenity"}),
    "flow_edges": frozenset({"flow_pct", "highway", "infra_type"}),
    "footway_crossing_candidates": frozenset({"length_m", "name", "osm_id"}),
    "graph_islands": frozenset({
        "bbox_e", "bbox_n", "bbox_s", "bbox_w", "gap_m", "highways",
        "length_m", "level_missing", "level_values", "node_id", "type", "way_ids",
    }),
    "kerb_issues": frozenset({
        "crossing_osm_id", "kerb_osm_id", "partner_way_osm_id", "type", "way_osm_id",
    }),
    "missing_crossings": frozenset({
        "detect_radius", "footway_value", "name", "nearest_tag_m",
        "osm_id", "type", "way_osm_id",
    }),
    "sidewalk_gaps": frozenset({"name"}),
    "sidewalk_roads": frozenset({"name", "sw"}),
    "tactile_paving_issues": frozenset({
        "crossing_tp", "kerb1_tp", "kerb2_tp", "osm_id", "partner_way_osm_id",
        "reason", "sides_checked", "way_osm_id",
    }),
}

FILTER_VALUES = {
    ("sidewalk_roads", "sw"): frozenset({"separate", "yes", "documented", "partial", "unknown"}),
    ("missing_crossings", "type"): frozenset({"missing_way", "missing_tag", "wrong_tag"}),
    ("kerb_issues", "type"): frozenset({"kerb_missing", "kerb_untagged"}),
    ("graph_islands", "type"): frozenset({"unjoined", "isolated", "level"}),
}


def read_text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


FRONT_JS = ("app.js", "popups.js")

PAGES = build_site.PAGES


def page_text(name: str) -> str:
    config = build_site.load_languages()
    return build_site.render_page(build_site.root_language(config), name, config)


def front_js() -> str:
    return "\n".join(read_text(name) for name in FRONT_JS)


def local_scripts(html: str) -> set:
    return set(re.findall(r'<script\s+src="\./([\w.-]+\.js)"', html))


def deployed_files() -> set:
    return set(build_site.STATIC)


def push_trigger_paths(workflow: str) -> set:
    start = workflow.index("paths:", workflow.index("push:"))
    block = workflow[start:workflow.index("workflow_dispatch", start)]
    return set(re.findall(r'-\s*"([^"]+)"', block))


def _block(src: str, start: int) -> str:
    depth = 0
    for i in range(start, len(src)):
        c = src[i]
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
            if depth < 0:
                return src[start:i]
    return src[start:]


def _bound_paths(src: str, root: str) -> dict:
    paths = {root: ""}
    changed = True
    while changed:
        changed = False
        for var, base, key in re.findall(r"const\s+(\w+)\s*=\s*(\w+)\.(\w+)\s*\|\|\s*\{\}", src):
            if base in paths and var not in paths:
                paths[var] = f"{paths[base]}.{key}".lstrip(".")
                changed = True
    return paths


def stats_reads(src: str, root: str = "s") -> set:
    paths = _bound_paths(src, root)
    bound = set(paths.values())
    reads = set()
    for var, prefix in paths.items():
        for m in re.finditer(r"\(\s*" + var + r"\.(\w+)\s*\|\|\s*\{\}\s*\)\.(\w+)", src):
            reads.add(f"{prefix}.{m.group(1)}.{m.group(2)}".lstrip("."))
        for m in re.finditer(r"(?<![\w.])" + var + r"\.(\w+)", src):
            if m.group(1) in ("toFixed", "toLocaleString", "length"):
                continue
            full = f"{prefix}.{m.group(1)}".lstrip(".")
            if full not in bound:
                reads.add(full)
    for p in bound:
        if p and not any(r.startswith(p + ".") for r in reads):
            reads.add(p)
    return {r for r in reads if not any(o.startswith(r + ".") for o in reads)}


def app_stats_block(src: str) -> str:
    start = src.index('fetch(i18n.dataUrl("stats.json"))')
    return src[start:src.index(".catch(", start)]


_LAYER_RE = re.compile(
    r'id:\s*(`[^`]+`|"[^"]+"),\s*type:\s*"\w+",\s*source:\s*"pedestrian",\s*"source-layer":\s*"(\w+)"'
)


def layer_sources(src: str) -> dict:
    return {m.group(1).strip('`"'): m.group(2) for m in _LAYER_RE.finditer(src)}


def _layer_of(layer_id: str, sources: dict) -> str | None:
    if layer_id in sources:
        return sources[layer_id]
    for pattern, layer in sources.items():
        if "${" in pattern and layer_id.startswith(pattern.split("${")[0]):
            return layer
    return None


def _gets(text: str) -> set:
    return set(re.findall(r'\["get",\s*"([^"]+)"\]', text))


def layer_props(src: str) -> dict:
    sources = layer_sources(src)
    consts = {
        name: _gets(_block(src, m.end()))
        for m in re.finditer(r"const\s+(\w+)\s*=\s*\[", src)
        for name in [m.group(1)]
    }
    props: dict = {}
    for m in _LAYER_RE.finditer(src):
        body = _block(src, m.start())
        found = _gets(body)
        for name, gets in consts.items():
            if gets and re.search(r"\b" + name + r"\b", body):
                found |= gets
        props.setdefault(m.group(2), set()).update(found)

    funcs = {m.group(1): _block(src, m.end()) for m in re.finditer(r"function\s+(\w+)\s*\(p\b[^)]*\)\s*\{", src)}
    for m in re.finditer(r"ids:\s*\[([^\]]*)\],\s*format:", src):
        body = _block(src, m.end())
        for name in re.findall(r"\b(\w+)\(p\b[^)]*\)", body):
            body += funcs.get(name, "")
        found = set(re.findall(r"\bp\.(\w+)", body)) | set(re.findall(r'\bp\["([^"]+)"\]', body))
        for layer_id in re.findall(r'"([^"]+)"', m.group(1)):
            props.setdefault(_layer_of(layer_id, sources), set()).update(found)

    for (layer, prop), _ in filter_values(src).items():
        props.setdefault(layer, set()).add(prop)
    return props


def filter_values(src: str) -> dict:
    sources = layer_sources(src)
    out = {}
    for layer_id, prop, items in re.findall(
        r'makeMembershipFilterUpdater\([^,]+,\s*"([^"]+)",\s*"([^"]+)",\s*\w+,\s*(\w+)\)', src
    ):
        array = _block(src, re.search(r"const\s+" + items + r"\s*=\s*\[", src).end())
        out[(sources[layer_id], prop)] = frozenset(re.findall(r'value:\s*"([^"]+)"', array))
    return out


def built_layers(workflow: str) -> set:
    return set(re.findall(r"--named-layer=(\w+):", workflow))


def slim_highway_props(workflow: str) -> set:
    start = workflow.index(".properties |= {", workflow.index("name: Slim highways GeoJSON properties"))
    block = _block(workflow, start + len(".properties |= {"))
    return set(re.findall(r'^\s*"?([\w:@]+)"?\s*:', block, flags=re.M))


def get_path(data: dict, path: str):
    node = data
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(path)
        node = node[key]
    return node


def assert_layer_contract(geojson_path, layer: str) -> list:
    features = json.loads(Path(geojson_path).read_text())["features"]
    real = [f for f in features if f.get("geometry")]
    assert real, f"{layer}: no feature to check"
    for feature in real:
        missing = LAYER_PROPS[layer] - set(feature["properties"])
        assert not missing, f"{layer}: missing {sorted(missing)}"
        for (lyr, prop), allowed in FILTER_VALUES.items():
            if lyr == layer:
                assert feature["properties"][prop] in allowed, (
                    f"{layer}.{prop}={feature['properties'][prop]!r} not shown by app.js"
                )
    return real


_HISTORY_PREFIXES = ("road_", "sidewalk_", "km_by", "footway_", "crossing_", "ped_", "cycleway_")


def history_reads(src: str) -> set:
    keys = set(re.findall(r"series\('(\w+)'\)", src))
    keys |= set(re.findall(r"\[\s*'[^']*',\s*'(\w+)',\s*'[^']*'\s*\]", src))
    keys |= set(re.findall(r"\bkey:\s*'(\w+)'", src))
    keys |= set(re.findall(r"\b(?:entry|last|first|lastSnapshot|dailyEntry)\.(\w+)", src))
    keys |= {k for k in re.findall(r"\bd\.(\w+)", src) if k.startswith(_HISTORY_PREFIXES)}
    return keys - {"date", "type"}


def evolution_ped_types(src: str) -> set:
    return set(re.findall(r"'(\w+)'", re.search(r"const PED_TYPES = \[([^\]]*)\]", src).group(1)))
