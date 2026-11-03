import os


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


MIN_OD_DISTANCE_M = _float("MIN_OD_DISTANCE_M", 600)
MAX_OD_DISTANCE_KM = _float("MAX_OD_DISTANCE_KM", 1)
MAX_OD_DISTANCE_M = MAX_OD_DISTANCE_KM * 1000
MAX_OD_PAIRS = _int("MAX_OD_PAIRS", 900_000)
TOP_RANK_PCT = _float("TOP_RANK_PCT", 15)
MIN_FLOW_THRESHOLD = _int("MIN_FLOW_THRESHOLD", 5)
POINTS_PER_SIDE = _int("POINTS_PER_SIDE", 5)
OD_SAMPLE_INTERVAL_M = _float("OD_SAMPLE_INTERVAL_M", 100)
MAX_SNAP_DISTANCE_M = _float("MAX_SNAP_DISTANCE_M", 150)

ISLAND_UNJOINED_GAP_M = _float("ISLAND_UNJOINED_GAP_M", 2)
ISLAND_PLATFORM_TOLERANCE_M = _float("ISLAND_PLATFORM_TOLERANCE_M", 1)
LEVEL_UNTAGGED_AS_GROUND = _flag("LEVEL_UNTAGGED_AS_GROUND", "0")

SIDEWALK_GAP_OFFSET_M = _float("SIDEWALK_GAP_OFFSET_M", 7)
SIDEWALK_GAP_SEARCH_M = _float("SIDEWALK_GAP_SEARCH_M", 8)
SIDEWALK_GAP_MAX_ANGLE = _float("SIDEWALK_GAP_MAX_ANGLE", 65)
SIDEWALK_GAP_MIN_COVERAGE = _float("SIDEWALK_GAP_MIN_COVERAGE", 0.4)

CROSSING_NODE_ROAD_SEARCH_M = _float("CROSSING_NODE_ROAD_SEARCH_M", 20)
CROSSING_WAY_SEARCH_RADIUS_M = _float("CROSSING_WAY_SEARCH_RADIUS_M", 3)
CROSSING_NODE_CONNECTED_M = _float("CROSSING_NODE_CONNECTED_M", 3)
CROSSING_SIDEWALK_OFFSET_M = _float("CROSSING_SIDEWALK_OFFSET_M", 7)
CROSSING_SIDEWALK_SEARCH_M = _float("CROSSING_SIDEWALK_SEARCH_M", 15)
CROSSING_SIDEWALK_MAX_ANGLE = _float("CROSSING_SIDEWALK_MAX_ANGLE", 40)
CROSSING_WRONG_TAG_SNAP_M = _float("CROSSING_WRONG_TAG_SNAP_M", 0.5)

FOOTWAY_CONN_ENDPOINT_TOL_M = _float("FOOTWAY_CONN_ENDPOINT_TOL_M", 3)
FOOTWAY_CONN_TIP_MARGIN_M = _float("FOOTWAY_CONN_TIP_MARGIN_M", 2)
FOOTWAY_CONN_MAX_LEN_M = _float("FOOTWAY_CONN_MAX_LEN_M", 40)

TACTILE_PAVING_WAY_MATCH_M = _float("TACTILE_PAVING_WAY_MATCH_M", 0.5)
TACTILE_PAVING_KERB_MATCH_M = _float("TACTILE_PAVING_KERB_MATCH_M", 0.5)

BENCH_N_SOURCES = _int("BENCH_N_SOURCES", 1000)
BENCH_N_TARGETS = _int("BENCH_N_TARGETS", 50)


PED_HIGHWAY_TYPES = frozenset({
    "footway", "pedestrian", "path",
    "living_street", "steps", "elevator",
    "track", "bridleway",
    "platform", "corridor",
})

ROAD_TYPES_SIDEWALK_EXPECTED = frozenset({
    "residential", "service", "unclassified",
    "tertiary", "tertiary_link",
    "secondary", "secondary_link",
    "primary", "primary_link",
})


EDGE_COST = {
    "pedestrian":     1.0,
    "footway":        1.0,
    "corridor":       1.0,
    "path":           1.2,
    "track":          1.2,
    "bridleway":      1.2,
    "living_street":  1.2,
    "elevator":       1.4,
    "steps":          1.5,
    "platform":       1.6,
    "residential":    2.0,
    "service":        2.0,
    "unclassified":   2.2,
    "tertiary":       3.5,
    "tertiary_link":  3.5,
    "secondary":      5.0,
    "secondary_link": 5.0,
    "primary":        8.0,
    "primary_link":   8.0,
}

EDGE_COST_DEFAULT = 2.5

CYCLEWAY_FOOT_ALLOWED_COST = 1.0

CYCLEWAY_NO_FOOT_COST = 1.8

CORRIDOR_PERMISSIVE_COST = 1.2


FOOT_FORBIDDEN = frozenset({"no", "private"})

ACCESS_EXCLUDED = frozenset({"no", "private"})

FOOT_ALLOWED = frozenset({"yes", "designated", "permissive"})


BLOCKED_BARRIER_RULES = frozenset({
    ("gate", "private"),
    ("gate", "no"),
})
