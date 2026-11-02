import pytest

from compute_history import _BrusselsStatsHandler, _build_record

_COORDS = [[4.35, 50.85], [4.351, 50.85]]

_CATEGORY_KEYS = (
    "road_sidewalk_separate",
    "road_sidewalk_yes_or_both",
    "road_sidewalk_no_explicit",
    "road_sidewalk_partial",
)


def _record(*ways):
    h = _BrusselsStatsHandler()
    for tags in ways:
        h.process_feature({
            "geometry": {"type": "LineString", "coordinates": _COORDS},
            "properties": tags,
        })
    return _build_record("2026-11-01", h)


def _category(record):
    hits = [k for k in _CATEGORY_KEYS if record[k]]
    assert len(hits) <= 1
    return hits[0].removeprefix("road_sidewalk_") if hits else None


@pytest.mark.parametrize("tags, expected", [
    ({}, None),
    ({"sidewalk": "both"}, "yes_or_both"),
    ({"sidewalk": "yes"}, "yes_or_both"),
    ({"sidewalk:both": "yes"}, "yes_or_both"),
    ({"sidewalk:left": "yes", "sidewalk:right": "yes"}, "yes_or_both"),
    ({"sidewalk:left": "yes", "sidewalk:right": "no"}, "yes_or_both"),
    ({"sidewalk:left": "separate", "sidewalk:right": "yes"}, "yes_or_both"),
    ({"sidewalk": "separate"}, "separate"),
    ({"sidewalk:both": "separate"}, "separate"),
    ({"sidewalk:left": "separate", "sidewalk:right": "separate"}, "separate"),
    ({"sidewalk:left": "separate", "sidewalk:right": "no"}, "separate"),
    ({"sidewalk": "no", "sidewalk:left": "separate", "sidewalk:right": "separate"}, "separate"),
    ({"sidewalk": "no"}, "no_explicit"),
    ({"sidewalk:both": "no"}, "no_explicit"),
    ({"sidewalk:left": "no", "sidewalk:right": "no"}, "no_explicit"),
    ({"sidewalk": "yes", "sidewalk:left": "no", "sidewalk:right": "no"}, "no_explicit"),
    ({"sidewalk": "left"}, "partial"),
    ({"sidewalk": "right"}, "partial"),
    ({"sidewalk:left": "yes"}, "partial"),
    ({"sidewalk:right": "no"}, "partial"),
    ({"sidewalk": "none"}, None),
    ({"sidewalk": "lane"}, None),
    ({"sidewalk:both": "separate;yes"}, None),
])
def test_road_sidewalk_category(tags, expected):
    record = _record({"highway": "residential", **tags})
    assert record["road_ways"] == 1
    assert _category(record) == expected
    assert record["road_sidewalk_any_tag"] == (0 if expected is None else 1)


def test_by_type_matches_totals():
    record = _record(
        {"highway": "residential", "sidewalk:left": "yes", "sidewalk:right": "yes"},
        {"highway": "residential", "sidewalk": "none"},
        {"highway": "tertiary", "sidewalk:both": "separate"},
        {"highway": "tertiary", "sidewalk": "left"},
        {"highway": "service", "sidewalk": "no"},
    )
    assert record["road_ways"] == 4
    assert record["road_sidewalk_by_type"] == {
        "residential": {
            "total": 2, "any_tag": 1, "separate": 0,
            "yes_or_both": 1, "partial": 0, "no_explicit": 0,
        },
        "tertiary": {
            "total": 2, "any_tag": 2, "separate": 1,
            "yes_or_both": 0, "partial": 1, "no_explicit": 0,
        },
    }
    assert record["sidewalk_documented_pct"] == 50.0
    assert record["sidewalk_separate_pct"] == 25.0
