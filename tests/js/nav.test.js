const test = require("node:test");
const assert = require("node:assert/strict");
const nav = require("../../nav.js");

const LAT0 = 50.85, LNG0 = 4.35;
const KY = 111320, KX = 111320 * Math.cos(LAT0 * Math.PI / 180);
const ll = (x, y) => [LAT0 + y / KY, LNG0 + x / KX];
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg ?? ""} ${a} vs ${b} (±${tol})`);

function makeGraph(nodesXY, segments) {
  const n = nodesXY.map(([x, y]) => ll(x, y));
  const hw = ["footway", "primary", "cycleway"];
  const sc = { footway: 0, primary: 1, cycleway: 2 };
  const e = [];
  for (const seg of segments) {
    const { a, b, cost = 1, highway = "footway", via = [], oneway = false } = seg;
    const pts = [nodesXY[a], ...via, nodesXY[b]];
    let len = 0;
    for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    const coords = pts.map(([x, y]) => ll(x, y));
    e.push([a, b, len * cost, len, hw.indexOf(highway), sc[highway], coords]);
    if (!oneway) e.push([b, a, len * cost, len, hw.indexOf(highway), sc[highway], [...coords].reverse()]);
  }
  const graph = { hw, n, e };
  return { graph, adj: nav.buildAdjacency(graph) };
}

const clickAt = (graph, x, y, mask = null) => nav.snapToNetwork(graph, ...ll(x, y), mask);
const legEdges = (graph, legs) => legs.map(l => [graph.e[l.edge][0], graph.e[l.edge][1], +l.from.toFixed(3), +l.to.toFixed(3)]);

test("click in the middle of an edge snaps to the projected point, not a node", () => {
  const { graph } = makeGraph([[0, 0], [200, 0]], [{ a: 0, b: 1 }]);
  const snap = clickAt(graph, 80, 6);
  near(snap.t, 0.4, 1e-6, "fraction");
  near(snap.distM, 6, 1e-6, "distance");
  const [lat, lng] = ll(80, 0);
  near(snap.lat, lat, 1e-9, "lat");
  near(snap.lng, lng, 1e-9, "lng");
});

test("fraction follows the edge geometry, not the straight line", () => {
  const { graph } = makeGraph([[0, 0], [100, 0]], [{ a: 0, b: 1, via: [[0, 100], [100, 100]] }]);
  const snap = clickAt(graph, 50, 103);
  near(snap.t, 150 / 300, 1e-6);
});

test("distances use metres, with the latitude correction", () => {
  const { graph } = makeGraph(
    [[30, -100], [30, 100], [-100, 40], [100, 40]],
    [{ a: 0, b: 1 }, { a: 2, b: 3 }],
  );
  const snap = clickAt(graph, 0, 0);
  assert.equal(graph.e[snap.edge][0] === 0 || graph.e[snap.edge][0] === 1, true);
  near(snap.distM, 30, 1e-6);
});

test("edges outside the main component are never snap targets", () => {
  const { graph } = makeGraph([[0, 0], [200, 0], [0, 10], [200, 10]], [{ a: 0, b: 1 }, { a: 2, b: 3 }]);
  const mask = Uint8Array.from([1, 1, 0, 0]);
  const snap = clickAt(graph, 50, 9, mask);
  assert.ok([0, 1].includes(graph.e[snap.edge][0]));
  near(snap.distM, 9, 1e-6);
});

test("snappable filter excludes edges", () => {
  const { graph } = makeGraph([[0, 0], [200, 0], [0, 10], [200, 10]], [{ a: 0, b: 1 }, { a: 2, b: 3 }]);
  const snappable = graph.e.map(e => e[0] <= 1);
  const snap = nav.snapToNetwork(graph, ...ll(50, 9), null, snappable);
  near(snap.distM, 9, 1e-6);
});

test("no candidate edge gives null", () => {
  const { graph } = makeGraph([[0, 0], [200, 0]], [{ a: 0, b: 1 }]);
  assert.equal(clickAt(graph, 10, 10, Uint8Array.from([0, 0])), null);
});

test("reverseEdge finds the opposite direction of the same segment", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0]], [{ a: 0, b: 1 }]);
  assert.equal(nav.reverseEdge(graph, adj, 0), 1);
  assert.equal(nav.reverseEdge(graph, adj, 1), 0);
});

test("reverseEdge ignores a parallel edge of a different length", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0]], [
    { a: 0, b: 1, oneway: true },
    { a: 1, b: 0, via: [[50, 40]], oneway: true },
  ]);
  assert.equal(nav.reverseEdge(graph, adj, 0), -1);
});

test("route starts and ends at the projected points, with partial edges", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0], [300, 0]], [{ a: 0, b: 1 }, { a: 1, b: 2 }]);
  const start = clickAt(graph, 50, 5), end = clickAt(graph, 250, -5);
  const route = nav.routeBetween(graph, adj, start, end);
  assert.deepEqual(legEdges(graph, route.legs), [[0, 1, 0.5, 1], [1, 2, 0, 0.75]]);
  near(route.cost, 50 + 150, 1e-6);
  const built = nav.buildRoute(graph, route.legs);
  assert.equal(built.totalM, 200);
  const first = built.geojson.features[0].geometry.coordinates[0];
  const [lat, lng] = ll(50, 0);
  near(first[0], lng, 1e-9);
  near(first[1], lat, 1e-9);
});

test("route can leave the start edge backwards", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0], [0, 200]], [{ a: 0, b: 1 }, { a: 0, b: 2 }]);
  const start = clickAt(graph, 20, 3), end = clickAt(graph, 0, 150);
  const route = nav.routeBetween(graph, adj, start, end);
  near(route.cost, 20 + 150, 1e-6);
  assert.deepEqual(legEdges(graph, route.legs), [[1, 0, 0.8, 1], [0, 2, 0, 0.75]]);
});

test("start and end on the same edge give a single partial leg, in both directions", () => {
  const { graph, adj } = makeGraph([[0, 0], [400, 0]], [{ a: 0, b: 1 }]);
  const a = clickAt(graph, 100, 4), b = clickAt(graph, 300, -4);
  const forward = nav.routeBetween(graph, adj, a, b);
  near(forward.cost, 200, 1e-6);
  assert.equal(forward.legs.length, 1);
  const backward = nav.routeBetween(graph, adj, b, a);
  near(backward.cost, 200, 1e-6);
  assert.equal(backward.legs.length, 1);
  assert.equal(nav.buildRoute(graph, backward.legs).totalM, 200);
});

test("a shorter way round beats the same-edge leg when it is cheaper", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0]], [
    { a: 0, b: 1, cost: 10 },
    { a: 0, b: 1, via: [[50, 10]], cost: 1 },
  ]);
  const start = nav.snapToNetwork(graph, ...ll(10, -2), null, graph.e.map((_, i) => i < 2));
  const end = nav.snapToNetwork(graph, ...ll(90, -2), null, graph.e.map((_, i) => i < 2));
  const route = nav.routeBetween(graph, adj, start, end);
  assert.ok(route.cost < 800);
  assert.ok(route.legs.some(l => l.edge >= 2));
});

test("weights decide the route, not lengths", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0], [200, 0], [100, 80]], [
    { a: 0, b: 1 }, { a: 1, b: 2, highway: "primary", cost: 8 },
    { a: 1, b: 3 }, { a: 3, b: 2 },
  ]);
  const route = nav.routeBetween(graph, adj, clickAt(graph, 50, 2), clickAt(graph, 199, 1));
  const used = route.legs.map(l => graph.hw[graph.e[l.edge][4]]);
  assert.ok(!used.includes("primary"));
});

test("unreachable destination gives null", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0], [0, 500], [100, 500]], [{ a: 0, b: 1 }, { a: 2, b: 3 }]);
  assert.equal(nav.routeBetween(graph, adj, clickAt(graph, 50, 1), clickAt(graph, 50, 499)), null);
});

test("partialCoords cuts a polyline by length", () => {
  const coords = [ll(0, 0), ll(100, 0), ll(100, 100)];
  const mid = nav.partialCoords(coords, 0.25, 0.75);
  assert.equal(mid.length, 3);
  near(mid[0][1], ll(50, 0)[1], 1e-9);
  near(mid[1][1], ll(100, 0)[1], 1e-12);
  near(mid[2][0], ll(100, 50)[0], 1e-9);
  assert.deepEqual(nav.partialCoords(coords, 0, 1), coords);
});

test("buildRoute splits lengths by infrastructure with partial legs", () => {
  const { graph, adj } = makeGraph([[0, 0], [100, 0], [300, 0]], [
    { a: 0, b: 1, highway: "footway" }, { a: 1, b: 2, highway: "primary" },
  ]);
  const built = nav.buildRoute(graph, [{ edge: 0, from: 0.5, to: 1 }, { edge: 2, from: 0, to: 0.5 }]);
  assert.equal(built.totalM, 150);
  assert.equal(built.pedM, 50);
  assert.equal(built.roadM, 100);
  near(built.roadPct, 100 * 100 / 150, 1e-9);
  assert.deepEqual(built.geojson.features.map(f => f.properties.highway), ["footway", "primary"]);
});

test("computeMainComponent keeps the largest connected part", () => {
  const mask = nav.computeMainComponent(5, [[0, 1], [1, 2], [3, 4]]);
  assert.deepEqual(Array.from(mask), [1, 1, 1, 0, 0]);
});

test("MinHeap pops in increasing order", () => {
  const h = new nav.MinHeap();
  for (const v of [5, 1, 4, 2, 3]) h.push([v, v]);
  const out = [];
  while (h.size) out.push(h.pop()[0]);
  assert.deepEqual(out, [1, 2, 3, 4, 5]);
});

test("end snapped on the opposite direction of the start edge is still a single leg", () => {
  const { graph, adj } = makeGraph([[0, 0], [400, 0]], [{ a: 0, b: 1 }]);
  assert.equal(graph.e[1][0], 1);
  const start = { edge: 0, t: 0.25 }, end = { edge: 1, t: 0.25 };
  const route = nav.routeBetween(graph, adj, start, end);
  near(route.cost, 200, 1e-6);
  assert.deepEqual(legEdges(graph, route.legs), [[0, 1, 0.25, 0.75]]);
});

test("the first destination end reached is not always the best one", () => {
  const { graph, adj } = makeGraph([[0, 0], [1000, 0], [0, 150], [1000, 150]], [
    { a: 0, b: 1, via: [[0, -500], [1000, -500]] },
    { a: 0, b: 2 }, { a: 2, b: 3 }, { a: 3, b: 1 },
  ]);
  const onSide = graph.e.map(e => e[0] === 0 && e[1] === 2);
  const onMain = graph.e.map(e => e[0] === 0 && e[1] === 1);
  const start = nav.snapToNetwork(graph, ...ll(-3, 10), null, onSide);
  const end = nav.snapToNetwork(graph, ...ll(1003, -50), null, onMain);
  near(end.t, 1950 / 2000, 1e-6);
  const route = nav.routeBetween(graph, adj, start, end);
  near(route.cost, 140 + 1000 + 150 + 50, 1e-3);
  const last = route.legs.at(-1);
  assert.deepEqual([graph.e[last.edge][0], graph.e[last.edge][1]], [1, 0]);
});

test("buildRoute counts cycleway metres separately", () => {
  const { graph } = makeGraph([[0, 0], [100, 0], [300, 0]], [
    { a: 0, b: 1, highway: "cycleway" }, { a: 1, b: 2, highway: "footway" },
  ]);
  const built = nav.buildRoute(graph, [{ edge: 0, from: 0, to: 1 }, { edge: 2, from: 0, to: 1 }]);
  assert.equal(built.cycM, 100);
  assert.equal(built.pedM, 200);
  assert.equal(built.geojson.features[0].properties.color, "#7c3aed");
});

test("groundSnappable reads the ground flag, missing flag counts as ground", () => {
  const graph = { e: [[0, 1, 1, 1, 0, 0, [], 1], [1, 0, 1, 1, 0, 0, [], 0], [0, 1, 1, 1, 0, 0, []]] };
  assert.deepEqual(nav.groundSnappable(graph), [true, false, true]);
});

test("a click above an underground edge snaps to the street", () => {
  const { graph } = makeGraph([[0, 0], [200, 0], [0, 10], [200, 10]], [{ a: 0, b: 1 }, { a: 2, b: 3 }]);
  graph.e.forEach(e => e.push(e[0] >= 2 ? 0 : 1));
  const snap = nav.snapToNetwork(graph, ...ll(50, 9), null, nav.groundSnappable(graph));
  assert.ok([0, 1].includes(graph.e[snap.edge][0]));
  near(snap.distM, 9, 1e-6);
});
