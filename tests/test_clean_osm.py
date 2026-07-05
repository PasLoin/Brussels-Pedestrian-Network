"""Tests for scripts/clean_osm.py — barrier splitting and dangling ways."""

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
    # dangling way 11 removed; way 10 split around the gate node 3
    assert segments == [["1", "2"], ["4", "5"]]
    # the blocked node itself never appears in a segment
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
