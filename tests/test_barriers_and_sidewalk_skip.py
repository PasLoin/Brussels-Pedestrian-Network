import xml.etree.ElementTree as ET

import pytest

from clean_osm import _find_blocked_nodes
from sidewalk_gap import _should_skip_road


def _root(*nodes):
    xml = "<osm>" + "".join(
        f'<node id="{nid}" lat="50.85" lon="4.35">'
        + "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        + "</node>"
        for nid, tags in nodes
    ) + "</osm>"
    return ET.fromstring(xml)


@pytest.mark.parametrize("tags, blocked", [
    ({"barrier": "gate", "access": "private"}, True),
    ({"barrier": "gate", "access": "no"}, True),
    ({"barrier": "gate", "access": "private", "foot": "yes"}, False),
    ({"barrier": "gate", "access": "no", "foot": "permissive"}, False),
    ({"barrier": "gate", "access": "private", "foot": "designated"}, False),
    ({"barrier": "gate", "access": "private", "foot": "private"}, True),
    ({"barrier": "gate", "foot": "no"}, True),
    ({"barrier": "lift_gate", "foot": "no"}, True),
    ({"barrier": "gate"}, False),
    ({"barrier": "lift_gate", "access": "no"}, False),
    ({"highway": "crossing", "foot": "no"}, False),
])
def test_find_blocked_nodes(tags, blocked):
    assert (_find_blocked_nodes(_root(("1", tags))) == {"1"}) is blocked


@pytest.mark.parametrize("sw, left, right, both, skip", [
    ("", "", "", "", False),
    ("both", "", "", "", False),
    ("separate", "", "", "", False),
    ("yes", "", "", "", False),
    ("no", "", "", "", True),
    ("none", "", "", "", True),
    ("left", "", "", "", True),
    ("right", "", "", "", True),
    ("", "", "", "no", True),
    ("", "no", "", "", True),
    ("", "", "no", "", True),
    ("", "separate", "separate", "", False),
    ("no", "separate", "separate", "", False),
    ("left", "", "separate", "", False),
    ("", "", "", "separate", False),
])
def test_should_skip_road(sw, left, right, both, skip):
    assert _should_skip_road(sw, left, right, both) is skip
