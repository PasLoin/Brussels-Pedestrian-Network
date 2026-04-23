"""
Configuration for the Brussels pedestrian routing pipeline.

All tunable parameters are read from environment variables (set in
.github/workflows/build.yml) with sensible defaults.  Constants that
never change across runs are defined here as plain Python values.
"""

import os


# ─── Origin-Destination sampling ─────────────────────────────────────────────
# Minimum straight-line distance (metres) between an OD pair.
# Pairs closer than this are discarded to avoid trivially short trips.
MIN_OD_DISTANCE_M = float(os.environ.get("MIN_OD_DISTANCE_M", 300))

# Maximum straight-line distance (km / m) between an OD pair.
MAX_OD_DISTANCE_KM = float(os.environ.get("MAX_OD_DISTANCE_KM", 5))
MAX_OD_DISTANCE_M = MAX_OD_DISTANCE_KM * 1000

# Upper bound on the number of OD pairs generated.  Caps runtime.
MAX_OD_PAIRS = int(os.environ.get("MAX_OD_PAIRS", 50_000))

# Only the top N% of edges by flow count are flagged as "forced".
TOP_RANK_PCT = float(os.environ.get("TOP_RANK_PCT", 5))

# How many evenly-spaced address points to sample per side of each street.
POINTS_PER_SIDE = int(os.environ.get("POINTS_PER_SIDE", 5))


# ─── Walkability score ───────────────────────────────────────────────────────
# Only the first/last N metres of each trip contribute to walkability.
WALK_SCORE_RADIUS_M = float(os.environ.get("WALK_SCORE_RADIUS_M", 1000))

# Multiplier applied when a street has no sidewalk at all.
SIDEWALK_PENALTY_NONE = float(os.environ.get("SIDEWALK_PENALTY_NONE", 0.3))

# Multiplier when a street has a sidewalk on one side only.
SIDEWALK_PENALTY_PARTIAL = float(os.environ.get("SIDEWALK_PENALTY_PARTIAL", 0.6))

# Multiplier when no sidewalk tag exists on the road edges.
SIDEWALK_PENALTY_UNKNOWN = float(os.environ.get("SIDEWALK_PENALTY_UNKNOWN", 0.5))


# ─── Highway classification ─────────────────────────────────────────────────
# Highway types that count as dedicated pedestrian infrastructure.
PED_HIGHWAY_TYPES = frozenset({
    "footway", "pedestrian", "path",
    "living_street", "steps", "elevator",
})

# Road types where we expect a sidewalk tag to be present.
ROAD_TYPES_SIDEWALK_EXPECTED = frozenset({
    "residential", "service", "unclassified",
    "tertiary", "tertiary_link",
    "secondary", "secondary_link",
    "primary", "primary_link",
})


# ─── Edge cost model ─────────────────────────────────────────────────────────
# Weight = edge length × cost factor.  Lower cost → preferred by router.
EDGE_COST = {
    "pedestrian":     1.0,
    "footway":        1.0,
    "path":           1.2,
    "living_street":  1.2,
    "cycleway":       1.7,   # default for cycleway without foot=yes
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

# Default cost when highway type is not in the table above.
EDGE_COST_DEFAULT = 2.5

# Cost override for cycleways where foot=yes/designated/permissive.
CYCLEWAY_FOOT_ALLOWED_COST = 1.0

# Cost for cycleways without explicit pedestrian permission.
CYCLEWAY_NO_FOOT_COST = 1.8


# ─── Access filtering ────────────────────────────────────────────────────────
# Edges with these foot tag values are completely excluded from the graph.
FOOT_FORBIDDEN = frozenset({"no"})

# Edges with these access tag values are excluded.
ACCESS_EXCLUDED = frozenset({"no", "private"})

# Foot tag values that grant explicit pedestrian permission on cycleways.
FOOT_ALLOWED = frozenset({"yes", "designated", "permissive"})


# ─── Barrier handling ────────────────────────────────────────────────────────
# (barrier_type, access_value) pairs that block passage through a node.
# Ways are split at these nodes so the router cannot cross them.
BLOCKED_BARRIER_RULES = frozenset({
    ("gate", "private"),
    ("gate", "no"),
})
