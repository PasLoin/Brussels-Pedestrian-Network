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

  <node id="41" lat="50.8900" lon="4.3900" version="1"/>
  <node id="42" lat="50.8901" lon="4.3901" version="1"/>
  <node id="43" lat="50.8902" lon="4.3902" version="1"/>
  <way id="182174380" version="1">
    <nd ref="41"/><nd ref="42"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="1"/>
  </way>
  <way id="182174379" version="1">
    <nd ref="42"/><nd ref="43"/>
    <tag k="highway" v="footway"/>
    <tag k="bridge" v="covered"/>
    <tag k="layer" v="1"/>
  </way>

  <node id="51" lat="50.9000" lon="4.4000" version="1"/>
  <node id="52" lat="50.9001" lon="4.4001" version="1"/>
  <node id="53" lat="50.9002" lon="4.4002" version="1"/>
  <way id="501" version="1">
    <nd ref="51"/><nd ref="52"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="0"/>
  </way>
  <way id="502" version="1">
    <nd ref="52"/><nd ref="53"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="-1"/>
  </way>

  <node id="61" lat="50.9100" lon="4.4100" version="1"/>
  <node id="62" lat="50.9101" lon="4.4101" version="1"/>
  <node id="63" lat="50.9102" lon="4.4102" version="1"/>
  <node id="64" lat="50.9103" lon="4.4103" version="1"/>
  <way id="601" version="1">
    <nd ref="61"/><nd ref="62"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="0"/>
  </way>
  <way id="602" version="1">
    <nd ref="62"/><nd ref="63"/>
    <tag k="highway" v="steps"/>
    <tag k="level" v="1;2"/>
  </way>
  <way id="603" version="1">
    <nd ref="63"/><nd ref="64"/>
    <tag k="highway" v="footway"/>
    <tag k="level" v="2"/>
  </way>

  <node id="71" lat="50.9200" lon="4.4200" version="1"/>
  <node id="72" lat="50.9201" lon="4.4201" version="1"/>
  <node id="73" lat="50.9202" lon="4.4202" version="1"/>
  <node id="74" lat="50.9203" lon="4.4203" version="1"/>
  <way id="701" version="1">
    <nd ref="71"/><nd ref="72"/>
    <tag k="highway" v="residential"/>
  </way>
  <way id="702" version="1">
    <nd ref="72"/><nd ref="73"/>
    <tag k="highway" v="steps"/>
    <tag k="level" v="-1;0"/>
  </way>
  <way id="703" version="1">
    <nd ref="73"/><nd ref="74"/>
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


def _flagged_nodes(bundle, groups, untagged_as_ground=False):
    found = find_level_discontinuities(
        groups, bundle.edge_tuples, bundle.edge_highways,
        bundle.edge_levels, bundle.elevator_vertices,
        untagged_as_ground=untagged_as_ground,
    )
    return {bundle.node_list[v]: (g, m) for v, g, m in found}


def _ways(bundle, groups, group_ids):
    return {w for g in group_ids for w in bundle.edge_osm_ids[groups[g][0]]}


def test_levels_survive_simplification(bundle):
    assert "-2;-1" in bundle.edge_levels
    assert "-1;0" in bundle.edge_levels


def test_elevator_node_detected(bundle):
    osmid_to_idx = {osmid: i for i, osmid in enumerate(bundle.node_list)}
    assert osmid_to_idx[22] in bundle.elevator_vertices


def test_steps_with_incompatible_tagged_neighbour_are_flagged(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 62 in flagged
    assert _ways(bundle, groups, flagged[62][0]) == {601, 602}
    assert 63 not in flagged


def test_only_steps_are_checked(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert set(flagged) == {2, 62}


def test_untagged_non_steps_neighbour_is_ignored(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 42 not in flagged


def test_issue_50_unreached_bottom_level_is_flagged(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 2 in flagged
    group_ids, missing = flagged[2]
    assert missing == -2.0
    assert _ways(bundle, groups, group_ids) == {101, 496286153}
    assert 3 not in flagged


def test_untagged_end_accepted_when_missing_level_is_ground(bundle, groups):
    flagged = _flagged_nodes(bundle, groups)
    assert 72 not in flagged


def test_issue_50_with_untagged_as_ground(bundle, groups):
    flagged = _flagged_nodes(bundle, groups, untagged_as_ground=True)
    assert set(flagged) == {2, 62}
    assert _ways(bundle, groups, flagged[2][0]) == {101, 496286153}


def test_consistent_steps_are_not_flagged(bundle, groups):
    flagged = _flagged_nodes(bundle, groups, untagged_as_ground=True)
    assert 12 not in flagged
    assert 13 not in flagged
    assert 3 not in flagged


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
    assert stats["level_discontinuities"] == 2
    features = json.loads(out.read_text())["features"]
    level = {
        f["properties"]["node_id"]: f["properties"]
        for f in features if f["properties"]["type"] == "level"
    }
    assert set(level) == {2, 62}
    assert level[62]["levels"] == "1;2 : niveau 1 non raccordé"
    assert set(level[62]["way_ids"].split(",")) == {"601", "602"}
    assert level[2]["levels"] == "-2;-1 : niveau -2 non raccordé"
    assert set(level[2]["way_ids"].split(",")) == {"101", "496286153"}
