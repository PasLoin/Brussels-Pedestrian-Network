from __future__ import annotations

SEPARATE = "separate"
YES = "yes"
NO = "no"
UNKNOWN = ""

SIDEWALK_VALUES = frozenset({"both", "left", "right", "yes", "no", "separate"})
SIDE_VALUES = frozenset({"yes", "no", "separate"})

_BASE_SIDES = {
    "both": (YES, YES),
    "yes": (YES, YES),
    "separate": (SEPARATE, SEPARATE),
    "no": (NO, NO),
    "left": (YES, NO),
    "right": (NO, YES),
}

_BASE_SIDES_LEFT_RIGHT_ONE_SIDED = {
    **_BASE_SIDES,
    "left": (YES, UNKNOWN),
    "right": (UNKNOWN, YES),
}

CATEGORY_SEPARATE = "separate"
CATEGORY_YES = "yes_or_both"
CATEGORY_NO = "no_explicit"
CATEGORY_PARTIAL = "partial"


def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip().lower()


def normalize(sw, sw_left, sw_right, sw_both) -> tuple[str, str, str, str]:
    sw = _clean(sw)
    sides = tuple(_clean(v) for v in (sw_left, sw_right, sw_both))
    return (
        sw if sw in SIDEWALK_VALUES else "",
        *(v if v in SIDE_VALUES else "" for v in sides),
    )


def resolve_sides(
    sw, sw_left, sw_right, sw_both, *, left_right_implies_no: bool = True,
) -> tuple[str, str]:
    sw, sw_left, sw_right, sw_both = normalize(sw, sw_left, sw_right, sw_both)
    base = _BASE_SIDES if left_right_implies_no else _BASE_SIDES_LEFT_RIGHT_ONE_SIDED
    left, right = base.get(sw, (UNKNOWN, UNKNOWN))
    if sw_both:
        left = right = sw_both
    if sw_left:
        left = sw_left
    if sw_right:
        right = sw_right
    return left, right


def side_category(left: str, right: str) -> str | None:
    known = [s for s in (left, right) if s]
    if not known:
        return None
    if len(known) == 1:
        return CATEGORY_PARTIAL
    if YES in known:
        return CATEGORY_YES
    if SEPARATE in known:
        return CATEGORY_SEPARATE
    return CATEGORY_NO


def stats_category(sw, sw_left, sw_right, sw_both) -> str | None:
    return side_category(*resolve_sides(
        sw, sw_left, sw_right, sw_both, left_right_implies_no=False,
    ))


def has_absent_side(sw, sw_left, sw_right, sw_both) -> bool:
    return NO in resolve_sides(sw, sw_left, sw_right, sw_both)
