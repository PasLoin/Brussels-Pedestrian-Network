import json
import os
import random
import shutil
import subprocess
from pathlib import Path

import igraph as ig
import pytest

from build_graph import build_graph
from clean_osm import clean_osm
from export import export_routing_graph

_ROOT = Path(__file__).resolve().parent.parent
_NODE = shutil.which("node")

if _NODE is None:
    if os.environ.get("REQUIRE_NODE_TESTS") == "1":
        raise RuntimeError("REQUIRE_NODE_TESTS=1 but node is not installed")
    pytest.skip("node not installed", allow_module_level=True)

_TYPES = [
    {"highway": "footway"}, {"highway": "residential"}, {"highway": "primary"},
    {"highway": "steps"}, {"highway": "cycleway"}, {"highway": "cycleway", "foot": "yes"},
    {"highway": "platform"}, {"highway": "path"}, {"highway": "tertiary"},
    {"highway": "footway", "level": "-1"}, {"highway": "footway", "foot": "private"},
]

_JS = """
const nav = require(process.argv[1]);
const fs = require("fs");
const graph = JSON.parse(fs.readFileSync(process.argv[2]));
const pairs = JSON.parse(fs.readFileSync(process.argv[3]));
const adj = nav.buildAdjacency(graph);
const out = pairs.map(([a, b]) => {
  const ei = graph.e.findIndex(e => e[0] === a);
  const fi = graph.e.findIndex(e => e[1] === b);
  if (ei < 0 || fi < 0) return null;
  const r = nav.routeBetween(graph, adj, { edge: ei, t: 0 }, { edge: fi, t: 1 });
  if (!r) return null;
  const legsCost = r.legs.reduce((sum, l) => sum + (l.to - l.from) * graph.e[l.edge][2], 0);
  let chained = true;
  for (let i = 1; i < r.legs.length; i++) {
    if (graph.e[r.legs[i - 1].edge][1] !== graph.e[r.legs[i].edge][0]) chained = false;
  }
  return [r.cost, r.legs.length, legsCost, chained];
});
process.stdout.write(JSON.stringify(out));
"""


def _grid_xml(size, rng):
    nodes, ways, ids = [], [], {}
    for i in range(size):
        for j in range(size):
            nid = len(ids) + 1
            ids[(i, j)] = nid
            lat, lon = 50.84 + i * 0.0009 + rng.uniform(-1e-4, 1e-4), 4.35 + j * 0.0013 + rng.uniform(-1e-4, 1e-4)
            nodes.append(f'<node id="{nid}" lat="{lat:.7f}" lon="{lon:.7f}" version="1"/>')
    wid = 1000
    for (i, j), a in ids.items():
        for di, dj in ((0, 1), (1, 0), (1, 1)):
            b = ids.get((i + di, j + dj))
            if b is None or (di, dj) == (1, 1) and rng.random() < 0.6:
                continue
            tags = dict(rng.choice(_TYPES), name=f"w{wid}")
            tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
            ways.append(f'<way id="{wid}" version="1"><nd ref="{a}"/><nd ref="{b}"/>{tag_xml}</way>')
            wid += 1
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"test\">\n"
        + "\n".join(nodes) + "\n" + "\n".join(ways) + "\n</osm>\n"
    )


@pytest.fixture(scope="module", params=[1, 2, 3], ids=["seed1", "seed2", "seed3"])
def exported(request, tmp_path_factory):
    rng = random.Random(request.param)
    folder = tmp_path_factory.mktemp(f"coherence{request.param}")
    raw, clean = folder / "raw.osm", folder / "clean.osm"
    raw.write_text(_grid_xml(7, rng))
    clean_osm(str(raw), str(clean))
    gb = build_graph(str(clean))
    cwd = os.getcwd()
    os.chdir(folder)
    try:
        export_routing_graph(
            gb.node_list, gb.nodes_gdf, gb.edge_tuples, gb.edge_weights, gb.edge_lengths,
            gb.edge_highways, gb.edge_geoms, gb.edge_cycleway_nf, gb.edge_foot_tags,
            edge_levels=gb.edge_levels,
        )
    finally:
        os.chdir(cwd)
    graph_path = folder / "graph.json"
    data = json.loads(graph_path.read_text())
    n = len(data["n"])
    pairs = [(a, b) for a in range(n) for b in range(n) if a != b]
    rng.shuffle(pairs)
    pairs = pairs[:300]
    pairs_path = folder / "pairs.json"
    pairs_path.write_text(json.dumps(pairs))
    proc = subprocess.run(
        [_NODE, "-e", _JS, str(_ROOT / "nav.js"), str(graph_path), str(pairs_path)],
        capture_output=True, text=True, check=True,
    )
    return gb, data, pairs, json.loads(proc.stdout)


def _graph_from_json(data):
    g = ig.Graph(n=len(data["n"]), edges=[(e[0], e[1]) for e in data["e"]], directed=True)
    g.es["weight"] = [e[2] for e in data["e"]]
    return g


def test_graph_json_keeps_the_igraph_structure(exported):
    gb, data, _, _ = exported
    assert [(e[0], e[1]) for e in data["e"]] == gb.edge_tuples
    assert len(data["n"]) == gb.graph.vcount()


def test_js_dijkstra_matches_igraph_on_the_exported_weights(exported):
    _, data, pairs, js = exported
    g = _graph_from_json(data)
    reachable = 0
    for (a, b), got in zip(pairs, js):
        expected = g.distances(source=a, target=b, weights="weight")[0][0]
        if expected == float("inf"):
            assert got is None, (a, b)
            continue
        assert got is not None, (a, b)
        assert got[0] == pytest.approx(expected, abs=1e-6), (a, b)
        reachable += 1
    assert reachable >= 100


def test_js_costs_stay_within_rounding_of_the_python_graph(exported):
    gb, _, pairs, js = exported
    for (a, b), got in zip(pairs, js):
        if got is None:
            continue
        expected = gb.graph.distances(source=a, target=b, weights="weight")[0][0]
        path = gb.graph.get_shortest_paths(a, to=b, weights="weight", output="epath")[0]
        tolerance = 0.05 * max(len(path), got[1]) + 1e-6
        assert abs(got[0] - expected) <= tolerance, (a, b, got, expected)


def test_scenario_contains_the_tricky_edges(exported):
    _, data, _, _ = exported
    assert 0 in {e[7] for e in data["e"]}
    assert {0, 1, 2, 3} <= {e[5] for e in data["e"]}


def test_js_drawn_legs_add_up_to_the_announced_cost(exported):
    _, _, pairs, js = exported
    checked = 0
    for (a, b), got in zip(pairs, js):
        if got is None:
            continue
        cost, _, legs_cost, chained = got
        assert legs_cost == pytest.approx(cost, abs=1e-6), (a, b)
        assert chained, (a, b)
        checked += 1
    assert checked >= 100
