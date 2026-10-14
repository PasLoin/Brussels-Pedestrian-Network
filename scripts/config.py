import os


MIN_OD_DISTANCE_M = float(os.environ.get("MIN_OD_DISTANCE_M", 300))

MAX_OD_DISTANCE_KM = float(os.environ.get("MAX_OD_DISTANCE_KM", 5))
MAX_OD_DISTANCE_M = MAX_OD_DISTANCE_KM * 1000

MAX_OD_PAIRS = int(os.environ.get("MAX_OD_PAIRS", 50_000))

TOP_RANK_PCT = float(os.environ.get("TOP_RANK_PCT", 5))

MIN_FLOW_THRESHOLD = int(os.environ.get("MIN_FLOW_THRESHOLD", 5))

POINTS_PER_SIDE = int(os.environ.get("POINTS_PER_SIDE", 5))

OD_SAMPLE_INTERVAL_M = float(os.environ.get("OD_SAMPLE_INTERVAL_M", 100))

MAX_SNAP_DISTANCE_M = float(os.environ.get("MAX_SNAP_DISTANCE_M", 150))

ISLAND_UNJOINED_GAP_M = float(os.environ.get("ISLAND_UNJOINED_GAP_M", 2))

ISLAND_PLATFORM_TOLERANCE_M = float(os.environ.get("ISLAND_PLATFORM_TOLERANCE_M", 1))


WALK_SCORE_RADIUS_M = float(os.environ.get("WALK_SCORE_RADIUS_M", 1000))

SIDEWALK_PENALTY_NONE = float(os.environ.get("SIDEWALK_PENALTY_NONE", 0.3))

SIDEWALK_PENALTY_PARTIAL = float(os.environ.get("SIDEWALK_PENALTY_PARTIAL", 0.6))

SIDEWALK_PENALTY_UNKNOWN = float(os.environ.get("SIDEWALK_PENALTY_UNKNOWN", 0.5))

PED_INFRA_RADIUS_M = float(os.environ.get("PED_INFRA_RADIUS_M", 500))

SURFACE_PENALTY_MAX = float(os.environ.get("SURFACE_PENALTY_MAX", 0.15))

LIT_PENALTY_MAX = float(os.environ.get("LIT_PENALTY_MAX", 0.10))


PED_HIGHWAY_TYPES = frozenset({
    "footway", "pedestrian", "path",
    "living_street", "steps", "elevator",
    "track", "bridleway",
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
    "path":           1.2,
    "track":          1.2,
    "bridleway":      1.2,
    "living_street":  1.2,
    "cycleway":       1.7,
    "steps":          1.5,
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


FOOT_FORBIDDEN = frozenset({"no"})

ACCESS_EXCLUDED = frozenset({"no", "private"})

FOOT_ALLOWED = frozenset({"yes", "designated", "permissive"})


BLOCKED_BARRIER_RULES = frozenset({
    ("gate", "private"),
    ("gate", "no"),
})
