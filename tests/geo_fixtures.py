import json
import math

from pyproj import Transformer

TO_WGS = Transformer.from_crs("EPSG:31370", "EPSG:4326", always_xy=True)
X0, Y0 = 150000.0, 170000.0

LAT0 = 50.85
LON0 = 4.35
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def lambert_ll(x, y):
    return list(TO_WGS.transform(X0 + x, Y0 + y))


def lambert_line(coords, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": [lambert_ll(*c) for c in coords]}}


def lambert_point(x, y, props):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": lambert_ll(x, y)}}


def metric_xy(x_m, y_m):
    return [LON0 + x_m / M_PER_DEG_LON, LAT0 + y_m / M_PER_DEG_LAT]


def write_features(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return str(path)
