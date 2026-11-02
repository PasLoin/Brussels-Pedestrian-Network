import pytest

from sidewalk_tags import (
    has_absent_side,
    normalize,
    resolve_sides,
    side_category,
    stats_category,
)


@pytest.mark.parametrize("raw, expected", [
    (("", "", "", ""), ("", "", "", "")),
    ((None, None, None, None), ("", "", "", "")),
    ((float("nan"), "", "", ""), ("", "", "", "")),
    ((" Both ", "YES", "No", "Separate"), ("both", "yes", "no", "separate")),
    (("none", "", "", ""), ("", "", "", "")),
    (("lane", "", "", ""), ("", "", "", "")),
    (("separate;yes", "", "", ""), ("", "", "", "")),
    (("", "both", "left", "none"), ("", "", "", "")),
    (("", "", "", "separate;yes"), ("", "", "", "")),
    (("left", "none", "lane", "both"), ("left", "", "", "")),
])
def test_normalize_drops_non_conforming_values(raw, expected):
    assert normalize(*raw) == expected


_RESOLVE_CASES = [
    (("", "", "", ""), ("", ""), ("", "")),
    (("both", "", "", ""), ("yes", "yes"), ("yes", "yes")),
    (("yes", "", "", ""), ("yes", "yes"), ("yes", "yes")),
    (("no", "", "", ""), ("no", "no"), ("no", "no")),
    (("separate", "", "", ""), ("separate", "separate"), ("separate", "separate")),
    (("left", "", "", ""), ("yes", "no"), ("yes", "")),
    (("right", "", "", ""), ("no", "yes"), ("", "yes")),
    (("", "", "", "yes"), ("yes", "yes"), ("yes", "yes")),
    (("", "", "", "no"), ("no", "no"), ("no", "no")),
    (("", "", "", "separate"), ("separate", "separate"), ("separate", "separate")),
    (("", "yes", "no", ""), ("yes", "no"), ("yes", "no")),
    (("", "separate", "", ""), ("separate", ""), ("separate", "")),
    (("", "", "no", ""), ("", "no"), ("", "no")),
    (("no", "separate", "separate", ""), ("separate", "separate"), ("separate", "separate")),
    (("yes", "no", "no", ""), ("no", "no"), ("no", "no")),
    (("both", "", "no", ""), ("yes", "no"), ("yes", "no")),
    (("separate", "", "no", ""), ("separate", "no"), ("separate", "no")),
    (("", "yes", "", "no"), ("yes", "no"), ("yes", "no")),
    (("left", "", "separate", ""), ("yes", "separate"), ("yes", "separate")),
    (("right", "", "separate", ""), ("no", "separate"), ("", "separate")),
    (("none", "", "", ""), ("", ""), ("", "")),
    (("no", "", "", "separate;yes"), ("no", "no"), ("no", "no")),
    (("", "none", "", "yes"), ("yes", "yes"), ("yes", "yes")),
]


@pytest.mark.parametrize("tags, sides, _", _RESOLVE_CASES)
def test_resolve_sides_follows_wiki_precedence(tags, sides, _):
    assert resolve_sides(*tags) == sides


@pytest.mark.parametrize("tags, _, sides", _RESOLVE_CASES)
def test_resolve_sides_left_right_one_sided(tags, _, sides):
    assert resolve_sides(*tags, left_right_implies_no=False) == sides


@pytest.mark.parametrize("left, right, expected", [
    ("", "", None),
    ("yes", "", "partial"),
    ("", "no", "partial"),
    ("separate", "", "partial"),
    ("yes", "yes", "yes_or_both"),
    ("yes", "no", "yes_or_both"),
    ("separate", "yes", "yes_or_both"),
    ("separate", "separate", "separate"),
    ("separate", "no", "separate"),
    ("no", "separate", "separate"),
    ("no", "no", "no_explicit"),
])
def test_side_category(left, right, expected):
    assert side_category(left, right) == expected


@pytest.mark.parametrize("tags, expected", [
    (("", "", "", ""), None),
    (("none", "", "", ""), None),
    (("lane", "", "", ""), None),
    (("", "", "", "separate;yes"), None),
    (("left", "", "", ""), "partial"),
    (("right", "", "", ""), "partial"),
    (("left", "", "no", ""), "yes_or_both"),
    (("left", "", "separate", ""), "yes_or_both"),
    (("right", "", "separate", ""), "partial"),
    (("", "yes", "", ""), "partial"),
    (("", "no", "", ""), "partial"),
    (("", "separate", "no", ""), "separate"),
    (("no", "separate", "separate", ""), "separate"),
    (("yes", "no", "no", ""), "no_explicit"),
])
def test_stats_category(tags, expected):
    assert stats_category(*tags) == expected


@pytest.mark.parametrize("old_scheme, new_scheme", [
    (("both", "", "", ""), ("", "", "", "yes")),
    (("both", "", "", ""), ("", "yes", "yes", "")),
    (("yes", "", "", ""), ("", "", "", "yes")),
    (("no", "", "", ""), ("", "", "", "no")),
    (("no", "", "", ""), ("", "no", "no", "")),
    (("separate", "", "", ""), ("", "", "", "separate")),
    (("separate", "", "", ""), ("", "separate", "separate", "")),
])
def test_old_and_new_schemes_are_equivalent(old_scheme, new_scheme):
    assert resolve_sides(*old_scheme) == resolve_sides(*new_scheme)
    assert stats_category(*old_scheme) == stats_category(*new_scheme)
    assert has_absent_side(*old_scheme) == has_absent_side(*new_scheme)


@pytest.mark.parametrize("tags, expected", [
    (("", "", "", ""), False),
    (("yes", "", "", ""), False),
    (("left", "", "", ""), True),
    (("", "no", "", ""), True),
    (("no", "separate", "separate", ""), False),
    (("none", "", "", ""), False),
])
def test_has_absent_side(tags, expected):
    assert has_absent_side(*tags) is expected
