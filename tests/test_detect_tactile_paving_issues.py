"""Tests for scripts/detect_tactile_paving_issues.py — coherence check
between a highway=crossing node's tactile_paving tag and the
tactile_paving tags on the barrier=kerb nodes at each end of its
attached footway=crossing way."""

import json
import math

from detect_tactile_paving_issues import _classify, detect_tactile_paving_issues

LAT0 = 50.85
LON0 = 4.35

_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def _xy(x_m: float, y_m: float) -> list[float]:
    """Convert local ENU metre offsets (from LON0, LAT0) to [lon, lat]."""
    return [LON0 + x_m / _M_PER_DEG_LON, LAT0 + y_m / _M_PER_DEG_LAT]


def _write_geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def _crossing_feature(x_m, y_m, tactile_paving, fid):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": {"highway": "crossing", "tactile_paving": tactile_paving, "@id": fid},
    }


def _crossing_way_feature(x0, y0, xc, yc, x1, y1, fid):
    """A footway=crossing way running kerb → crossing node → kerb, so the
    crossing node is an exact vertex of the line (as in real OSM data)."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [_xy(x0, y0), _xy(xc, yc), _xy(x1, y1)]},
        "properties": {"highway": "footway", "footway": "crossing", "@id": fid},
    }


def _kerb_feature(x_m, y_m, tactile_paving, fid):
    props = {"barrier": "kerb", "@id": fid}
    if tactile_paving is not None:
        props["tactile_paving"] = tactile_paving
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": props,
    }


# ── Pure classification logic ───────────────────────────────────────────────

def test_classify_yes_coherent_when_both_kerbs_yes():
    assert _classify("yes", "yes", "yes") is None


def test_classify_yes_flagged_when_one_kerb_no():
    assert _classify("yes", "yes", "no") == "value_mismatch"


def test_classify_no_coherent_when_both_kerbs_no():
    assert _classify("no", "no", "no") is None


def test_classify_incorrect_coherent_when_kerbs_are_a_mixed_pair():
    assert _classify("incorrect", "yes", "no") is None
    assert _classify("incorrect", "no", "yes") is None


def test_classify_incorrect_flagged_when_kerbs_not_mixed():
    assert _classify("incorrect", "yes", "yes") == "incorrect_not_mixed"
    assert _classify("incorrect", "no", "no") == "incorrect_not_mixed"


def test_classify_missing_kerb_is_a_reason_code_but_not_flagged_by_caller():
    """_classify itself still reports the pair as inconsistent (there's
    nothing to compare) — it's detect_tactile_paving_issues() that
    decides not to write it to the output layer, see the pipeline test
    below."""
    assert _classify("yes", "yes", None) == "kerb_missing"
    assert _classify("incorrect", None, None) == "kerb_missing"


def test_classify_untagged_kerb_is_a_reason_code_but_not_flagged_by_caller():
    assert _classify("no", "no", "") == "kerb_untagged"


# ── Full pipeline (geometric matching + GeoJSON I/O) ───────────────────────

def test_coherent_yes_crossing_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=1),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=101),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=201),
        _kerb_feature(3, 0, "yes", fid=202),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["coherent"] == 1
    assert stats["flagged"] == 0


def test_no_crossing_with_mismatched_kerb_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=2),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=102),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no",  fid=203),
        _kerb_feature(3, 0, "yes", fid=204),  # should be "no" too
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 1
    assert stats["value_mismatch"] == 1

    out = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())
    props = out["features"][0]["properties"]
    assert props["osm_id"] == 2
    assert props["reason"] == "value_mismatch"
    assert props["kerb1_tp"] == "no"
    assert props["kerb2_tp"] == "yes"


def test_incorrect_crossing_with_mixed_kerbs_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=3),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=103),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=205),
        _kerb_feature(3, 0, "no",  fid=206),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["coherent"] == 1
    assert stats["flagged"] == 0


def test_incorrect_crossing_with_both_kerbs_yes_is_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "incorrect", fid=4),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=104),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=207),
        _kerb_feature(3, 0, "yes", fid=208),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 1
    assert stats["incorrect_not_mixed"] == 1


def test_missing_kerb_at_one_extremity_is_not_flagged(tmp_path, monkeypatch):
    """Out of scope for now: a missing kerb node is a data gap, not a
    contradiction — don't flag it, but keep it visible in stats."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=5),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=105),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=209),
        # no kerb node at the other extremity
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["kerb_missing"] == 1

    out = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())
    # Empty-output placeholder feature only, no real flagged feature.
    assert all(f["properties"].get("osm_id", 0) != 5 for f in out["features"])


def test_kerb_without_tactile_paving_tag_is_not_flagged(tmp_path, monkeypatch):
    """Out of scope for now: a kerb with no tactile_paving tag at all is
    a data gap, not a contradiction — don't flag it, but keep it visible
    in stats."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "no", fid=6),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=106),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no", fid=210),
        _kerb_feature(3, 0, None,  fid=211),  # kerb exists, no tactile_paving tag
    ])

    stats = detect_tactile_paving_issues()
    assert stats["flagged"] == 0
    assert stats["kerb_untagged"] == 1


def test_out_of_scope_tactile_paving_value_is_skipped(tmp_path, monkeypatch):
    """tactile_paving=contrasted/primitive/etc. isn't yes/no/incorrect —
    this check doesn't apply and the node is silently ignored."""
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "contrasted", fid=7),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        _crossing_way_feature(-3, 0, 0, 0, 3, 0, fid=107),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "no",  fid=212),
        _kerb_feature(3, 0, "yes", fid=213),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 0
    assert stats["flagged"] == 0


def test_crossing_without_nearby_crossing_way_is_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_geojson(tmp_path / "highways.geojson", [
        _crossing_feature(0, 0, "yes", fid=8),
    ])
    _write_geojson(tmp_path / "sidewalk_footways_raw.geojson", [
        # Way is far away (200 m) — not attached to this crossing node.
        _crossing_way_feature(197, 200, 200, 200, 203, 200, fid=108),
    ])
    _write_geojson(tmp_path / "kerbs_raw.geojson", [
        _kerb_feature(-3, 0, "yes", fid=214),
        _kerb_feature(3, 0, "yes", fid=215),
    ])

    stats = detect_tactile_paving_issues()
    assert stats["crossings_in_scope"] == 1
    assert stats["no_crossing_way_found"] == 1
    assert stats["flagged"] == 0
