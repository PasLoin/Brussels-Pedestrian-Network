import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_communes import export_communes  # noqa: E402

POLY = """brussels
1
   4.30 50.80
   4.40 50.80
   4.40 50.90
   4.30 50.90
END
END
"""


def _square(x0, y0, size, steps=40):
    pts = []
    for i in range(steps):
        pts.append([x0 + size * i / steps, y0])
    for i in range(steps):
        pts.append([x0 + size, y0 + size * i / steps])
    for i in range(steps):
        pts.append([x0 + size - size * i / steps, y0 + size])
    for i in range(steps):
        pts.append([x0, y0 + size - size * i / steps])
    pts.append(pts[0])
    return [pts]


def _feature(props, x0, y0, size=0.02):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": _square(x0, y0, size)}}


def _write(tmp_path, features):
    src = tmp_path / "admin.geojson"
    src.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    poly = tmp_path / "region.poly"
    poly.write_text(POLY, encoding="utf-8")
    return src, poly


def test_keeps_only_brussels_municipalities_with_bilingual_names(tmp_path):
    src, poly = _write(tmp_path, [
        _feature({"boundary": "administrative", "admin_level": "8", "name": "Ixelles - Elsene",
                  "name:fr": "Ixelles", "name:nl": "Elsene", "ref:INS": "21009"}, 4.35, 50.82),
        _feature({"boundary": "administrative", "admin_level": "8", "name": "Tervuren",
                  "name:nl": "Tervuren"}, 4.50, 50.82),
        _feature({"boundary": "administrative", "admin_level": "4", "name": "Région"}, 4.31, 50.81),
        _feature({"boundary": "postal_code", "admin_level": "8", "name": "1050"}, 4.33, 50.85),
    ])
    out = tmp_path / "communes.geojson"
    assert export_communes(str(src), str(poly), str(out)) == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [f["properties"] for f in data["features"]] == [
        {"name": "Ixelles - Elsene", "name_fr": "Ixelles", "name_nl": "Elsene"},
    ]


def test_outlines_are_simplified_and_rounded(tmp_path):
    src, poly = _write(tmp_path, [
        _feature({"boundary": "administrative", "admin_level": "8", "name": "A", "name:fr": "A", "name:nl": "A"}, 4.35, 50.82),
    ])
    out = tmp_path / "communes.geojson"
    export_communes(str(src), str(poly), str(out))
    ring = json.loads(out.read_text(encoding="utf-8"))["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) <= 6
    for x, y in ring:
        assert round(x, 6) == x and round(y, 6) == y


def test_missing_boundary_keeps_every_municipality(tmp_path):
    src, _ = _write(tmp_path, [
        _feature({"boundary": "administrative", "admin_level": "8", "name": "Tervuren"}, 4.50, 50.82),
    ])
    out = tmp_path / "communes.geojson"
    assert export_communes(str(src), str(tmp_path / "absent.poly"), str(out)) == 1


def test_no_municipality_still_writes_a_valid_empty_file(tmp_path):
    src, poly = _write(tmp_path, [])
    out = tmp_path / "communes.geojson"
    assert export_communes(str(src), str(poly), str(out)) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"type": "FeatureCollection", "features": []}
