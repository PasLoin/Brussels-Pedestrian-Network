import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from build_graph import is_ground_level
from sample_od import snap_to_graph

_OSMID_OFFSET = 1000


class Scene:
    def __init__(self):
        self.coords = []
        self.main = []
        self.edge_tuples = []
        self.edge_geoms = []
        self.edge_levels = []

    def node(self, xy, main=True):
        if xy in self.coords:
            idx = self.coords.index(xy)
            self.main[idx] = self.main[idx] or main
            return idx
        self.coords.append(xy)
        self.main.append(main)
        return len(self.coords) - 1

    def segment(self, a, b, main=True, level=""):
        u, v = self.node(a, main), self.node(b, main)
        self.edge_tuples += [(u, v), (v, u)]
        self.edge_geoms += [LineString([a, b]), LineString([b, a])]
        self.edge_levels += [level, level]
        return u, v

    def snap(self, points, use_mask=False, max_snap_m=None, use_levels=False):
        node_list = [_OSMID_OFFSET + i for i in range(len(self.coords))]
        nodes_gdf = gpd.GeoDataFrame(
            {
                "x": [c[0] for c in self.coords],
                "y": [c[1] for c in self.coords],
                "geometry": [Point(c) for c in self.coords],
            },
            index=node_list,
            crs="EPSG:31370",
        )
        mask = np.array(self.main, dtype=bool) if use_mask else None
        return snap_to_graph(
            points, node_list, nodes_gdf,
            self.edge_tuples, self.edge_geoms,
            vertex_mask=mask, max_snap_m=max_snap_m,
            edge_snappable=[is_ground_level(lv) for lv in self.edge_levels] if use_levels else None,
        )


def test_point_snaps_to_nearest_end_of_nearest_edge():
    s = Scene()
    a, b = s.segment((0.0, 0.0), (100.0, 0.0))

    snapped, stats = s.snap([(20.0, 5.0), (80.0, 5.0), (10.0, 0.0)])

    assert snapped == [a, b, a]
    assert stats["points_fallback_nearest_node"] == 0


def test_result_is_vertex_index_not_osm_id():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    snapped, _ = s.snap([(20.0, 5.0)])
    assert snapped == [0]


def test_result_order_follows_input_order():
    s = Scene()
    a, b = s.segment((0.0, 0.0), (100.0, 0.0))
    snapped, _ = s.snap([(90.0, 3.0), (10.0, 3.0), (95.0, -3.0), (5.0, -3.0)])
    assert snapped == [b, a, b, a]


def test_max_snap_distance():
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))

    snapped, stats = s.snap([(30.0, 149.0), (30.0, 151.0)], max_snap_m=150.0)

    assert snapped == [a, -1]
    assert stats["points_dropped_too_far"] == 1


def test_no_max_snap_keeps_far_points():
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))
    snapped, stats = s.snap([(30.0, 5000.0)])
    assert snapped == [a]
    assert stats["points_dropped_too_far"] == 0


def test_point_near_island_is_redirected_to_main_network():
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))
    island = set(s.segment((0.0, 10.0), (100.0, 10.0), main=False))

    snapped, stats = s.snap([(20.0, 12.0)], use_mask=True)

    assert snapped == [a]
    assert snapped[0] not in island
    assert stats["points_redirected_from_islands"] == 1


def test_max_snap_is_measured_to_main_network_not_island():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    s.segment((0.0, 10.0), (100.0, 10.0), main=False)

    snapped, stats = s.snap([(20.0, 12.0)], use_mask=True, max_snap_m=10.0)

    assert snapped == [-1]
    assert stats["points_dropped_too_far"] == 1


def test_point_closer_to_main_network_is_not_counted_as_redirected():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    s.segment((0.0, 50.0), (100.0, 50.0), main=False)

    _, stats = s.snap([(20.0, 3.0)], use_mask=True)

    assert stats["points_redirected_from_islands"] == 0


def test_ambiguous_point_falls_back_to_nearest_node():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    c, _ = s.segment((40.0, 10.2), (60.0, 10.2))

    snapped, stats = s.snap([(48.0, 5.0)])

    assert snapped == [c]
    assert stats["points_fallback_nearest_node"] == 1


def test_second_edge_beyond_ambiguity_ratio_is_ignored():
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))
    s.segment((40.0, 10.5), (60.0, 10.5))

    snapped, stats = s.snap([(48.0, 5.0)])

    assert snapped == [a]
    assert stats["points_fallback_nearest_node"] == 0


def test_fallback_returns_global_index_when_mask_is_partial():
    s = Scene()
    s.segment((5000.0, 5000.0), (5100.0, 5000.0), main=False)
    s.segment((0.0, 0.0), (100.0, 0.0))
    c, _ = s.segment((40.0, 10.2), (60.0, 10.2))

    snapped, stats = s.snap([(48.0, 5.0)], use_mask=True)

    assert snapped == [c]
    assert stats["points_fallback_nearest_node"] == 1


def test_edges_shorter_than_half_a_metre_are_ignored():
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))
    tiny = set(s.segment((30.0, 3.0), (30.0, 3.3)))

    snapped, _ = s.snap([(30.0, 4.0)])

    assert snapped == [a]
    assert snapped[0] not in tiny


def test_edges_without_geometry_are_ignored():
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))
    u = s.node((20.0, 4.0))
    v = s.node((20.0, 6.0))
    s.edge_tuples += [(u, v), (v, u)]
    s.edge_geoms += [None, LineString()]
    s.edge_levels += ["", ""]

    snapped, _ = s.snap([(20.0, 5.0)])

    assert snapped == [a]


@pytest.mark.parametrize("max_snap_m", [None, 150.0])
def test_snapped_vertices_are_always_on_main_network_or_minus_one(max_snap_m):
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    s.segment((100.0, 0.0), (100.0, 100.0))
    s.segment((0.0, 10.0), (90.0, 10.0), main=False)
    s.segment((300.0, 300.0), (400.0, 300.0), main=False)

    rng = np.random.default_rng(7)
    points = [tuple(p) for p in rng.uniform(-50.0, 450.0, size=(60, 2))]
    snapped, _ = s.snap(points, use_mask=True, max_snap_m=max_snap_m)

    main = {i for i, m in enumerate(s.main) if m}
    assert len(snapped) == len(points)
    assert all(v in main or v == -1 for v in snapped)
    if max_snap_m is None:
        assert -1 not in snapped


def test_edge_with_one_end_off_main_network_is_not_a_target():
    s = Scene()
    _, b = s.segment((0.0, 0.0), (100.0, 0.0))
    off = s.node((100.0, 50.0), main=False)
    s.edge_tuples += [(b, off), (off, b)]
    s.edge_geoms += [
        LineString([(100.0, 0.0), (100.0, 50.0)]),
        LineString([(100.0, 50.0), (100.0, 0.0)]),
    ]
    s.edge_levels += ["", ""]

    snapped, _ = s.snap([(102.0, 45.0)], use_mask=True)

    assert snapped == [b]



@pytest.mark.parametrize("level, ground", [
    ("", True),
    ("0", True),
    ("-1", False),
    ("-2", False),
    ("1", False),
    ("?", False),
    ("0;-1", False),
    ("-1;0", False),
    ("0;1", False),
])
def test_is_ground_level(level, ground):
    assert is_ground_level(level) is ground


@pytest.mark.parametrize("level", ["-2", "-1", "1", "5", "?", "0;-1"])
def test_point_above_off_ground_edge_snaps_to_ground(level):
    s = Scene()
    a, _ = s.segment((0.0, 0.0), (100.0, 0.0))
    below = set(s.segment((10.0, 9.0), (90.0, 9.0), level=level))

    snapped, stats = s.snap([(20.0, 9.5)], use_levels=True)

    assert snapped == [a]
    assert snapped[0] not in below
    assert stats["edges_not_at_ground_level"] == 2


@pytest.mark.parametrize("level", ["", "0"])
def test_ground_edges_stay_snappable(level):
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    c, _ = s.segment((10.0, 9.0), (90.0, 9.0), level=level)

    snapped, stats = s.snap([(20.0, 9.5)], use_levels=True)

    assert snapped == [c]
    assert stats["edges_not_at_ground_level"] == 0


def test_levels_are_ignored_without_edge_snappable():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    c, _ = s.segment((10.0, 9.0), (90.0, 9.0), level="-2")

    snapped, stats = s.snap([(20.0, 9.5)])

    assert snapped == [c]
    assert stats["edges_not_at_ground_level"] == 0


def test_max_snap_is_measured_to_ground_edges():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    s.segment((10.0, 50.0), (90.0, 50.0), level="-2")

    snapped, stats = s.snap([(20.0, 52.0)], use_levels=True, max_snap_m=20.0)

    assert snapped == [-1]
    assert stats["points_dropped_too_far"] == 1


def test_fallback_never_picks_a_node_reached_only_by_off_ground_edges():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    c, _ = s.segment((40.0, 10.2), (60.0, 10.2))
    under = set(s.segment((48.0, 6.0), (48.0, 40.0), level="-1"))

    snapped, stats = s.snap([(48.0, 5.0)], use_levels=True)

    assert snapped == [c]
    assert snapped[0] not in under
    assert stats["points_fallback_nearest_node"] == 1


def test_off_ground_edge_outside_main_network_is_not_a_redirection():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0))
    s.segment((0.0, 10.0), (100.0, 10.0), main=False, level="-1")

    _, stats = s.snap([(20.0, 12.0)], use_mask=True, use_levels=True)

    assert stats["points_redirected_from_islands"] == 0


def test_no_snappable_edge_is_an_explicit_error():
    s = Scene()
    s.segment((0.0, 0.0), (100.0, 0.0), level="-1")
    with pytest.raises(ValueError):
        s.snap([(20.0, 5.0)], use_levels=True)


def test_property_snapped_vertices_touch_a_ground_edge():
    s = Scene()
    s.segment((0.0, 0.0), (200.0, 0.0))
    s.segment((200.0, 0.0), (200.0, 200.0))
    s.segment((0.0, 0.0), (0.0, 200.0))
    s.segment((20.0, 20.0), (180.0, 20.0), level="-2")
    s.segment((20.0, 20.0), (20.0, 180.0), level="-2")
    s.segment((50.0, 100.0), (150.0, 100.0), level="?")
    s.segment((60.0, 150.0), (160.0, 150.0), level="3")

    rng = np.random.default_rng(11)
    points = [tuple(p) for p in rng.uniform(0.0, 200.0, size=(80, 2))]
    snapped, _ = s.snap(points, use_levels=True)

    ground_nodes = {
        n for (u, v), lv in zip(s.edge_tuples, s.edge_levels) if is_ground_level(lv) for n in (u, v)
    }
    assert all(v in ground_nodes for v in snapped)
