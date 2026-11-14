import itertools
import json
import subprocess
from pathlib import Path

from config import ROAD_TYPES_SIDEWALK_EXPECTED
from export_sidewalk_roads import _MIN_LENGTH, _classify_edge_sidewalk, _safe_str

ROOT = Path(__file__).resolve().parent.parent
VALUES = ["", "separate", "yes", "both", "no", "left", "right", " Separate ", "lane"]
KEYS = ["sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both"]

NODE = """
import(process.argv[1]).then(m => {
  const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
  process.stdout.write(JSON.stringify({
    statuses: input.map(tags => m.sidewalkStatus(tags)),
    roadTypes: [...m.ROAD_TYPES].sort(),
    minLength: m.MIN_LENGTH_M,
  }));
});
"""


def run_js(payload):
    module = (ROOT / "edit" / "dev-data.js").as_uri()
    out = subprocess.run(["node", "-e", NODE, module], input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_page_classifies_sidewalks_exactly_like_the_pipeline():
    combos = [dict((k, v) for k, v in zip(KEYS, values) if v) for values in itertools.product(VALUES, repeat=4)]
    js = run_js(combos)
    expected = [_classify_edge_sidewalk(*(_safe_str(tags.get(k)) for k in KEYS)) for tags in combos]
    mismatches = [(tags, py, got) for tags, py, got in zip(combos, expected, js["statuses"]) if py != got]
    assert not mismatches, mismatches[:5]


def test_the_page_keeps_the_same_roads_as_the_pipeline():
    js = run_js([])
    assert js["roadTypes"] == sorted(ROAD_TYPES_SIDEWALK_EXPECTED - {"service"})
    assert js["minLength"] == _MIN_LENGTH
