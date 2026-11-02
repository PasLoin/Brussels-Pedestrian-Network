import xml.etree.ElementTree as ET

import pytest

from clean_osm import clean_osm

_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.850" lon="4.350"/>
  <node id="2" lat="50.851" lon="4.351"/>
  <node id="3" lat="50.852" lon="4.352">
    <tag k="barrier" v="gate"/>
    <tag k="access" v="private"/>
  </node>
  <node id="4" lat="50.853" lon="4.353"/>
  <node id="5" lat="50.854" lon="4.354"/>
  <!-- way through a blocked gate: must be split into [1,2] and [4,5] -->
  <way id="10">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/>
    <tag k="highway" v="footway"/>
    <tag k="name" v="Allée Test"/>
  </way>
  <!-- way referencing a node absent from the extract: must be removed -->
  <way id="11">
    <nd ref="1"/><nd ref="999"/>
    <tag k="highway" v="footway"/>
  </way>
</osm>
"""


@pytest.fixture()
def cleaned_root(tmp_path):
    src = tmp_path / "in.osm"
    dst = tmp_path / "out.osm"
    src.write_text(_OSM)
    clean_osm(str(src), str(dst))
    return ET.parse(dst).getroot()


def test_way_is_split_at_blocked_gate(cleaned_root):
    ways = cleaned_root.findall("way")
    segments = sorted(
        [nd.get("ref") for nd in way.findall("nd")] for way in ways
    )
    assert segments == [["1", "2"], ["4", "5"]]
    for seg in segments:
        assert "3" not in seg


def test_split_segments_keep_original_tags(cleaned_root):
    for way in cleaned_root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        assert tags.get("highway") == "footway"
        assert tags.get("name") == "Allée Test"


def test_clean_osm_without_barriers_is_noop(tmp_path):
    osm = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.850" lon="4.350"/>
  <node id="2" lat="50.851" lon="4.351"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="footway"/>
  </way>
</osm>
"""
    src = tmp_path / "in.osm"
    dst = tmp_path / "out.osm"
    src.write_text(osm)

    clean_osm(str(src), str(dst))

    root = ET.parse(dst).getroot()
    ways = root.findall("way")
    assert len(ways) == 1
    assert [nd.get("ref") for nd in ways[0].findall("nd")] == ["1", "2"]


def _clean(tmp_path, ways_xml):
    osm = f"""<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.850" lon="4.350"/>
  <node id="2" lat="50.851" lon="4.351"/>
  <node id="3" lat="50.852" lon="4.350"/>
  {ways_xml}
</osm>
"""
    src = tmp_path / "in.osm"
    dst = tmp_path / "out.osm"
    src.write_text(osm)
    clean_osm(str(src), str(dst))
    root = ET.parse(dst).getroot()
    return {
        way.get("id"): [(t.get("k"), t.get("v")) for t in way.findall("tag")]
        for way in root.findall("way")
    }


def _highways(tags):
    return [v for k, v in tags if k == "highway"]


@pytest.mark.parametrize("tags", [
    [("railway", "platform")],
    [("public_transport", "platform")],
    [("railway", "platform"), ("public_transport", "platform"), ("area", "yes")],
])
def test_platform_without_highway_gets_highway_platform(tmp_path, tags):
    tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags)
    ways = _clean(tmp_path, f'<way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/>{tag_xml}</way>')
    assert _highways(ways["10"]) == ["platform"]
    for tag in tags:
        assert tag in ways["10"]


@pytest.mark.parametrize("highway", ["platform", "footway", "pedestrian"])
def test_platform_with_existing_highway_is_left_alone(tmp_path, highway):
    ways = _clean(tmp_path, (
        f'<way id="10"><nd ref="1"/><nd ref="2"/>'
        f'<tag k="highway" v="{highway}"/><tag k="railway" v="platform"/></way>'
    ))
    assert _highways(ways["10"]) == [highway]


@pytest.mark.parametrize("tags", [
    [("railway", "rail")],
    [("public_transport", "stop_position")],
    [("railway", "platform_edge")],
    [("building", "train_station")],
])
def test_other_ways_are_not_turned_into_platforms(tmp_path, tags):
    tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags)
    ways = _clean(tmp_path, f'<way id="10"><nd ref="1"/><nd ref="2"/>{tag_xml}</way>')
    assert _highways(ways["10"]) == []


def test_normalized_platform_keeps_its_tag_when_split_at_a_barrier(tmp_path):
    osm = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.850" lon="4.350"/>
  <node id="2" lat="50.851" lon="4.351"/>
  <node id="3" lat="50.852" lon="4.352"><tag k="barrier" v="gate"/><tag k="access" v="no"/></node>
  <node id="4" lat="50.853" lon="4.353"/>
  <node id="5" lat="50.854" lon="4.354"/>
  <way id="10">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/>
    <tag k="railway" v="platform"/>
  </way>
</osm>
"""
    src = tmp_path / "in.osm"
    dst = tmp_path / "out.osm"
    src.write_text(osm)
    clean_osm(str(src), str(dst))
    ways = ET.parse(dst).getroot().findall("way")
    assert len(ways) == 2
    for way in ways:
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        assert tags["highway"] == "platform"


_SQUARE_OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="50.8500" lon="4.3500"/>
  <node id="2" lat="50.8500" lon="4.3510"/>
  <node id="3" lat="50.8506" lon="4.3510"/>
  <node id="4" lat="50.8506" lon="4.3500"/>
  <node id="5" lat="50.8494" lon="4.3500"/>
  <node id="6" lat="50.8512" lon="4.3510"/>
  <way id="20">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
    <tag k="highway" v="pedestrian"/>
    <tag k="area" v="yes"/>
    <tag k="name" v="Place Test"/>
  </way>
  <way id="21">
    <nd ref="5"/><nd ref="1"/>
    <tag k="highway" v="footway"/>
    <tag k="name" v="Accès sud"/>
  </way>
  <way id="22">
    <nd ref="3"/><nd ref="6"/>
    <tag k="highway" v="footway"/>
    <tag k="name" v="Accès nord"/>
  </way>
</osm>
"""


@pytest.fixture()
def square_paths(tmp_path):
    src = tmp_path / "in.osm"
    dst = tmp_path / "out.osm"
    src.write_text(_SQUARE_OSM)
    clean_osm(str(src), str(dst))
    return dst


def test_pedestrian_area_is_removed(square_paths):
    root = ET.parse(square_paths).getroot()
    assert sorted(w.get("id") for w in root.findall("way")) == ["21", "22"]
    assert sorted(n.get("id") for n in root.findall("node")) == ["1", "3", "5", "6"]


def test_pedestrian_area_breaks_connectivity(square_paths):
    from build_graph import build_graph

    gb = build_graph(str(square_paths))
    assert "Place Test" not in gb.edge_names
    assert sorted(gb.edge_names) == ["Accès nord", "Accès nord", "Accès sud", "Accès sud"]
    assert gb.graph.vcount() == 4
    assert min(gb.graph.degree()) > 0
    assert len(gb.graph.connected_components(mode="weak")) == 2
