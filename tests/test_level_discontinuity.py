import json

import pytest

from build_graph import LEVEL_UNKNOWN, _edge_level, build_graph
from detect_graph_islands import (
    detect_graph_islands,
    find_level_discontinuities,
    levels_overlap,
    parse_level,
)
from export import undirected_edge_groups


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", (0.0, 0.0)),
        ("-1", (-1.0, -1.0)),
        ("-2;-1", (-2.0, -1.0)),
        ("0;1;2", (0.0, 2.0)),
        ("0.5", (0.5, 0.5)),
        ("0-2", (0.0, 2.0)),
        ("-2--1", (-2.0, -1.0)),
        ("-1-0", (-1.0, 0.0)),
        ("B1", None),
        (LEVEL_UNKNOWN, None),
    ],
)
def test_parse_level(raw, expected):
    assert parse_level(raw) == expected


def test_levels_overlap():
    assert not levels_overlap((-2.0, -1.0), (0.0, 0.0))
    assert levels_overlap((-2.0, -1.0), (-1.0, -1.0))
    assert levels_overlap((-1.0, 0.0), (0.0, 0.0))


@pytest.mark.parametrize(
    "level, tunnel, indoor, location, expected",
    [
        (None, None, None, None, ""),
        ("-2;-1", None, None, None, "-2;-1"),
        (None, "yes", None, None, LEVEL_UNKNOWN),
        (None, "building_passage", None, None, ""),
        (None, None, "yes", None, LEVEL_UNKNOWN),
        (None, None, None, "underground", LEVEL_UNKNOWN),
        (["-1", "0"], None, None, None, LEVEL_UNKNOWN),
        (["-1", float("nan")], None, None, None, LEVEL_UNKNOWN),
        (["-1", "-1"], None, None, None, "-1"),
    ],
)
def test_edge_level(level, tunnel, indoor, location, expected):
    assert _edge_level(level, tunnel, indoor, location) == expected


_TEST_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.8500" lon="4.3500" version="1"/>
  <node id="2" lat="50.8501" lon="4.3501" version="1"/>
  <node id="3" lat="50.8502" lon="4.3502" version="1"/>
  <node id="4" lat="50.8503" lon="4.3503" version="1"/>
  <way id="101" version="1">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="footway"/>
  </way>
  <way id="496286153" version="3">
    <nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="steps"/>
    <tag k="level" v="-2;-1"/>
  </way>
  <way id="103" version="1">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="footway"/>
    <tag k="indoor" v="corridor"/>
    <tag k="level" v="-1"/>
  </way>

  <node id="11" lat="50.8600" lon="4.3600" version="1"/>
  <node id="12" lat="50.8601" lon="4.3601" version="1"/>
  <node id="13" lat="50.8602" lon="4.3602" version="1"/>
  <node id="14" lat="50.8603" lon="4.3603" version="1"/>
  <way id="201" version="1">
    <nd ref="11"/><nd ref="12"/>
    <tag k="highway" v="footway"/>
  </way>
  <way id="202" version="1">
    <nd ref="12"/><nd ref="13"/>
    <tag k="highway" v="steps"/>
    <tag k="level" v="-1;0"/>
  </way>
  <way id="203" version="1">
    <nd ref="13"/><nd ref="14"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="-1"/>
  </way>

  <node id="21" lat="50.8700" lon="4.3700" version="1"/>
  <node id="22" lat="50.8701" lon="4.3701" version="1">
    <tag k="highway" v="elevator"/>
  </node>
  <node id="23" lat="50.8702" lon="4.3702" version="1"/>
  <way id="301" version="1">
    <nd ref="21"/><nd ref="22"/>
    <tag k="highway" v="footway"/>
  </way>
  <way id="302" version="1">
    <nd ref="22"/><nd ref="23"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="-1"/>
  </way>

  <node id="31" lat="50.8800" lon="4.3800" version="1"/>
  <node id="32" lat="50.8801" lon="4.3801" version="1"/>
  <node id="33" lat="50.8802" lon="4.3802" version="1"/>
  <way id="401" version="1">
    <nd ref="31"/><nd ref="32"/>
    <tag k="highway" v="footway"/>
    <tag k="tunnel" v="yes"/>
  </way>
  <way id="402" version="1">
    <nd ref="32"/><nd ref="33"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="-1"/>
  </way>
</osm>
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    path = tmp_path_factory.mktemp("osm") / "levels.osm"
    path.write_text(_TEST_OSM)
    return build_graph(str(path))


@pytest.fixture(scope="module")
def groups(bundle):
    return undirected_edge_groups(bundle.edge_tuples, bundle.edge_geoms, bundle.edge_lengths)


def _flagged_nodes(bundle, groups):
    found = find_level_discontinuities(
        groups, bundle.edge_tuples, bundle.edge_highways,
        bundle.edge_levels, bundle.elevator_vertices,
    )
    return {bundle.node_list[v]: g for v, g in found}


def test_levels_survive_simplification(bundle):
    assert "-2;-1" in bundle.edge_levels
    assert "-1;0" in bundle.edge_levels


def test_elevator_node_detected(bundle):
    osmid_to_idx = {osmid: i for i, osmid in enumerate(bundle.node_list)}
    assert osmid_to_idx[22] in bundle.elevator_vertices


def test_issue_50_steps_not_reaching_ground_are_flagged(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 2 in flagged
    ways = {w for g in flagged[2] for w in bundle.edge_osm_ids[groups[g][0]]}
    assert ways == {101, 496286153}
    assert 3 not in flagged


def test_consistent_steps_are_not_flagged(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 12 not in flagged
    assert 13 not in flagged


def test_elevator_and_unknown_levels_are_not_flagged(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 22 not in flagged
    assert 32 not in flagged
    assert set(flagged) == {2}


def test_level_rows_written_to_islands_layer(bundle, groups, tmp_path):
    out = tmp_path / "graph_islands.geojson"
    _, stats = detect_graph_islands(
        bundle.graph, groups,
        bundle.edge_tuples, bundle.edge_geoms, bundle.edge_lengths,
        bundle.edge_highways, bundle.edge_osm_ids,
        output_path=str(out),
        platforms_path=str(tmp_path / "missing.geojson"),
        edge_levels=bundle.edge_levels,
        elevator_vertices=bundle.elevator_vertices,
        node_list=bundle.node_list,
    )
    assert stats["level_discontinuities"] == 1
    features = json.loads(out.read_text())["features"]
    level = [f for f in features if f["properties"]["type"] == "level"]
    assert len(level) == 1
    props = level[0]["properties"]
    assert props["node_id"] == 2
    assert props["levels"] == "0 (non tagué) ≠ -2;-1"
    assert set(props["way_ids"].split(",")) == {"101", "496286153"}
