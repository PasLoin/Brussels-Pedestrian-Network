import json

from geo_fixtures import metric_xy


def _node(x, y, tp, props):
    if tp is not None:
        props["tactile_paving"] = tp
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": metric_xy(x, y)},
            "properties": props}


def crossing_node(x, y, tp, fid):
    return _node(x, y, tp, {"highway": "crossing", "@id": fid})


def kerb_node(x, y, tp, fid):
    return _node(x, y, tp, {"barrier": "kerb", "@id": fid})


def tagged_line(coords, fid, **tags):
    return {"type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [metric_xy(x, y) for x, y in coords]},
            "properties": {**tags, "@id": fid}}


def crossing_way(coords, fid):
    return tagged_line(coords, fid, highway="footway", footway="crossing")


def kerb_issues(tmp_path, kind=None):
    feats = json.loads((tmp_path / "kerb_issues.geojson").read_text())["features"]
    props = [f["properties"] for f in feats if f["properties"].get("type")]
    if kind is not None:
        props = [p for p in props if p["type"] == kind]
    return props


def tactile_issues(tmp_path):
    feats = json.loads((tmp_path / "tactile_paving_issues.geojson").read_text())["features"]
    return [f["properties"] for f in feats if f["properties"].get("osm_id")]
