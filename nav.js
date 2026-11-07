const NAV_M_PER_DEG_LAT = 111320;
const NAV_REVERSE_LENGTH_TOLERANCE_M = 0.11;
const NAV_INFRA_COLORS = { 0: "#22c55e", 1: "#ef4444", 2: "#7c3aed", 3: "#2563eb" };

class MinHeap {
  constructor() { this.d = []; }
  get size() { return this.d.length; }
  push(item) { this.d.push(item); this._up(this.d.length - 1); }
  pop() {
    const top = this.d[0], last = this.d.pop();
    if (this.d.length > 0) { this.d[0] = last; this._down(0); }
    return top;
  }
  _up(i) {
    const d = this.d;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (d[p][0] <= d[i][0]) break;
      [d[p], d[i]] = [d[i], d[p]]; i = p;
    }
  }
  _down(i) {
    const d = this.d, n = d.length;
    while (true) {
      let m = i, l = 2 * i + 1, r = 2 * i + 2;
      if (l < n && d[l][0] < d[m][0]) m = l;
      if (r < n && d[r][0] < d[m][0]) m = r;
      if (m === i) break;
      [d[m], d[i]] = [d[i], d[m]]; i = m;
    }
  }
}

function computeMainComponent(nNodes, edges) {
  const parent = new Int32Array(nNodes);
  for (let i = 0; i < nNodes; i++) parent[i] = i;
  const find = (x) => {
    while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; }
    return x;
  };
  for (const e of edges) {
    const a = find(e[0]), b = find(e[1]);
    if (a !== b) parent[a] = b;
  }
  const size = new Int32Array(nNodes);
  let bestRoot = 0;
  for (let i = 0; i < nNodes; i++) {
    const r = find(i);
    size[r]++;
    if (size[r] > size[bestRoot]) bestRoot = r;
  }
  const mask = new Uint8Array(nNodes);
  for (let i = 0; i < nNodes; i++) if (find(i) === bestRoot) mask[i] = 1;
  return mask;
}

function buildAdjacency(graph) {
  const adj = new Array(graph.n.length);
  for (let i = 0; i < adj.length; i++) adj[i] = [];
  graph.e.forEach((e, idx) => { adj[e[0]].push([e[1], idx]); });
  return adj;
}

function groundSnappable(graph) {
  return graph.e.map(e => e[7] !== 0);
}

function metresPerDegree(lat) {
  return { kx: NAV_M_PER_DEG_LAT * Math.cos(lat * Math.PI / 180), ky: NAV_M_PER_DEG_LAT };
}

function edgeCoords(graph, eidx) {
  const e = graph.e[eidx];
  if (e[6] && e[6].length >= 2) return e[6];
  return [graph.n[e[0]], graph.n[e[1]]];
}

function polylineLengths(coords, kx, ky) {
  const cum = [0];
  for (let i = 1; i < coords.length; i++) {
    const dx = (coords[i][1] - coords[i - 1][1]) * kx;
    const dy = (coords[i][0] - coords[i - 1][0]) * ky;
    cum.push(cum[i - 1] + Math.hypot(dx, dy));
  }
  return cum;
}

function snapToNetwork(graph, lat, lng, mask = null, snappable = null) {
  const { kx, ky } = metresPerDegree(lat);
  let best = null;
  for (let eidx = 0; eidx < graph.e.length; eidx++) {
    const e = graph.e[eidx];
    if (mask && (!mask[e[0]] || !mask[e[1]])) continue;
    if (snappable && !snappable[eidx]) continue;
    const coords = edgeCoords(graph, eidx);
    let along = 0;
    for (let i = 1; i < coords.length; i++) {
      const ax = (coords[i - 1][1] - lng) * kx, ay = (coords[i - 1][0] - lat) * ky;
      const bx = (coords[i][1] - lng) * kx, by = (coords[i][0] - lat) * ky;
      const dx = bx - ax, dy = by - ay;
      const seg2 = dx * dx + dy * dy;
      const t = seg2 > 0 ? Math.min(1, Math.max(0, -(ax * dx + ay * dy) / seg2)) : 0;
      const px = ax + t * dx, py = ay + t * dy;
      const d2 = px * px + py * py;
      const segLen = Math.sqrt(seg2);
      if (best === null || d2 < best.d2) {
        best = { edge: eidx, d2, along: along + t * segLen, px, py };
      }
      along += segLen;
    }
  }
  if (best === null) return null;
  const total = polylineLengths(edgeCoords(graph, best.edge), kx, ky).at(-1);
  return {
    edge: best.edge,
    t: total > 0 ? best.along / total : 0,
    lat: lat + best.py / ky,
    lng: lng + best.px / kx,
    distM: Math.sqrt(best.d2),
  };
}

function reverseEdge(graph, adj, eidx) {
  const [u, v, , lm] = graph.e[eidx];
  let found = -1, bestDiff = Infinity;
  for (const [nbr, idx] of adj[v]) {
    if (nbr !== u || idx === eidx) continue;
    const diff = Math.abs(graph.e[idx][3] - lm);
    if (diff <= NAV_REVERSE_LENGTH_TOLERANCE_M && diff < bestDiff) { found = idx; bestDiff = diff; }
  }
  return found;
}

function routeBetween(graph, adj, start, end) {
  const w = (idx) => graph.e[idx][2];
  const e = start.edge, t = start.t;
  const er = reverseEdge(graph, adj, e);
  const f = end.edge, s = end.t;
  const fr = reverseEdge(graph, adj, f);

  let best = Infinity, bestLegs = null;

  const sameAsStart = f === e ? s : (f === er ? 1 - s : null);
  if (sameAsStart !== null) {
    if (sameAsStart >= t) {
      best = (sameAsStart - t) * w(e);
      bestLegs = [{ edge: e, from: t, to: sameAsStart }];
    } else if (er >= 0) {
      best = (t - sameAsStart) * w(er);
      bestLegs = [{ edge: er, from: 1 - t, to: 1 - sameAsStart }];
    }
  }

  const n = graph.n.length;
  const dist = new Float64Array(n).fill(Infinity);
  const prevNode = new Int32Array(n).fill(-1);
  const prevEdge = new Int32Array(n).fill(-1);
  const seedLeg = new Array(n).fill(null);
  const heap = new MinHeap();

  const seed = (node, cost, leg) => {
    if (cost < dist[node]) {
      dist[node] = cost; seedLeg[node] = leg; prevNode[node] = -1; prevEdge[node] = -1;
      heap.push([cost, node]);
    }
  };
  seed(graph.e[e][1], (1 - t) * w(e), { edge: e, from: t, to: 1 });
  if (er >= 0) seed(graph.e[e][0], t * w(er), { edge: er, from: 1 - t, to: 1 });

  const exits = new Map();
  const addExit = (node, cost, leg) => {
    const cur = exits.get(node);
    if (!cur || cost < cur.cost) exits.set(node, { cost, leg });
  };
  addExit(graph.e[f][0], s * w(f), { edge: f, from: 0, to: s });
  if (fr >= 0) addExit(graph.e[f][1], (1 - s) * w(fr), { edge: fr, from: 0, to: 1 - s });

  let bestExit = null;
  while (heap.size > 0) {
    const [d, u] = heap.pop();
    if (d > dist[u]) continue;
    if (d >= best) break;
    const exit = exits.get(u);
    if (exit && d + exit.cost < best) { best = d + exit.cost; bestExit = { node: u, leg: exit.leg }; }
    for (const [v, idx] of adj[u]) {
      const nd = d + w(idx);
      if (nd < dist[v]) {
        dist[v] = nd; prevNode[v] = u; prevEdge[v] = idx; seedLeg[v] = null;
        heap.push([nd, v]);
      }
    }
  }

  if (bestExit) {
    const middle = [];
    let cur = bestExit.node;
    while (prevNode[cur] !== -1) {
      middle.push({ edge: prevEdge[cur], from: 0, to: 1 });
      cur = prevNode[cur];
    }
    middle.reverse();
    bestLegs = [seedLeg[cur], ...middle, bestExit.leg];
  }

  if (bestLegs === null) return null;
  return { cost: best, legs: bestLegs.filter(l => l.to - l.from > 1e-9) };
}

function partialCoords(coords, from, to) {
  if (from <= 0 && to >= 1) return coords.map(c => [c[0], c[1]]);
  const { kx, ky } = metresPerDegree(coords[0][0]);
  const cum = polylineLengths(coords, kx, ky);
  const total = cum.at(-1);
  if (total === 0) return [[coords[0][0], coords[0][1]], [coords[0][0], coords[0][1]]];
  const at = (frac) => {
    const target = frac * total;
    let i = 1;
    while (i < cum.length - 1 && cum[i] < target) i++;
    const seg = cum[i] - cum[i - 1];
    const k = seg > 0 ? (target - cum[i - 1]) / seg : 0;
    return [
      coords[i - 1][0] + k * (coords[i][0] - coords[i - 1][0]),
      coords[i - 1][1] + k * (coords[i][1] - coords[i - 1][1]),
    ];
  };
  const out = [at(from)];
  for (let i = 1; i < coords.length - 1; i++) {
    if (cum[i] > from * total && cum[i] < to * total) out.push([coords[i][0], coords[i][1]]);
  }
  out.push(at(to));
  return out;
}

function buildRoute(graph, legs) {
  let totalM = 0, pedM = 0, roadM = 0, cycM = 0;
  const features = [];
  for (const leg of legs) {
    const e = graph.e[leg.edge];
    const len = e[3] * (leg.to - leg.from), sc = e[5];
    const hw = graph.hw[e[4]];
    totalM += len;
    if (sc === 1) roadM += len;
    else if (sc === 2) cycM += len;
    else pedM += len;
    const coords = partialCoords(edgeCoords(graph, leg.edge), leg.from, leg.to);
    features.push({
      type: "Feature",
      properties: { infra_type: sc, highway: hw, length: len, color: NAV_INFRA_COLORS[sc] || NAV_INFRA_COLORS[1] },
      geometry: { type: "LineString", coordinates: coords.map(c => [c[1], c[0]]) },
    });
  }
  const pct = (m) => totalM > 0 ? m / totalM * 100 : 0;
  return {
    geojson: { type: "FeatureCollection", features },
    totalM: Math.round(totalM),
    pedM: Math.round(pedM), roadM: Math.round(roadM), cycM: Math.round(cycM),
    pedPct: pct(pedM), roadPct: pct(roadM), cycPct: pct(cycM),
    walkMin: Math.round(totalM / 80),
  };
}

if (typeof module !== "undefined") {
  module.exports = {
    MinHeap, computeMainComponent, buildAdjacency, groundSnappable, metresPerDegree, snapToNetwork,
    reverseEdge, routeBetween, partialCoords, buildRoute,
  };
}
