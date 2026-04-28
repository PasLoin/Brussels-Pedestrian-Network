// ══════════════════════════════════════════════════════════════════════════════
//  LEGEND TOGGLE
// ══════════════════════════════════════════════════════════════════════════════

function toggleLegend() {
  const el = document.getElementById("legend");
  el.classList.toggle("open");
  el.classList.toggle("closed");
}

// Auto-close legend on narrow screens
(function () {
  if (window.innerWidth <= 600) {
    const el = document.getElementById("legend");
    el.classList.remove("open");
    el.classList.add("closed");
  }
})();

// ══════════════════════════════════════════════════════════════════════════════
//  CLIENT-SIDE DIJKSTRA ROUTING
// ══════════════════════════════════════════════════════════════════════════════

// ── Min-heap (binary heap) ───────────────────────────────────────────────────
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

// ── Graph state ──────────────────────────────────────────────────────────────
let graphData = null;   // { hw, n, e }
let adjList = null;     // adjList[nodeIdx] = [[neighborIdx, edgeIdx], ...]
let graphReady = false;

// ── Load graph.json ──────────────────────────────────────────────────────────
fetch("./graph.json")
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(data => {
    graphData = data;
    const nNodes = data.n.length;
    adjList = new Array(nNodes);
    for (let i = 0; i < nNodes; i++) adjList[i] = [];
    data.e.forEach((e, idx) => {
      adjList[e[0]].push([e[1], idx]);
    });
    graphReady = true;
    const btn = document.getElementById("nav-btn");
    btn.classList.remove("loading");
    document.getElementById("nav-btn-label").textContent = "Navigation";
    console.log(`Graph loaded: ${data.n.length} nodes, ${data.e.length} edges`);
  })
  .catch(err => {
    console.warn("graph.json not available:", err);
    document.getElementById("nav-btn-label").textContent = "Navigation (indisponible)";
    document.getElementById("nav-btn").classList.add("disabled");
  });

// ── Nearest node (brute force – fine for <100k nodes) ────────────────────────
function nearestNode(lat, lng) {
  const nodes = graphData.n;
  let minD = Infinity, minI = 0;
  for (let i = 0; i < nodes.length; i++) {
    const dlat = nodes[i][0] - lat, dlng = nodes[i][1] - lng;
    const d = dlat * dlat + dlng * dlng;
    if (d < minD) { minD = d; minI = i; }
  }
  return minI;
}

// ── Dijkstra shortest path ───────────────────────────────────────────────────
function dijkstra(src, tgt) {
  const n = graphData.n.length;
  const dist = new Float64Array(n).fill(Infinity);
  const prev = new Int32Array(n).fill(-1);
  const prevEdge = new Int32Array(n).fill(-1);
  dist[src] = 0;

  const heap = new MinHeap();
  heap.push([0, src]);

  while (heap.size > 0) {
    const [d, u] = heap.pop();
    if (d > dist[u]) continue;
    if (u === tgt) break;
    const neighbors = adjList[u];
    for (let i = 0; i < neighbors.length; i++) {
      const [v, eidx] = neighbors[i];
      const nd = d + graphData.e[eidx][2];
      if (nd < dist[v]) {
        dist[v] = nd;
        prev[v] = u;
        prevEdge[v] = eidx;
        heap.push([nd, v]);
      }
    }
  }

  if (dist[tgt] === Infinity) return null;

  const path = [];
  let cur = tgt;
  while (cur !== src) {
    path.push(prevEdge[cur]);
    cur = prev[cur];
  }
  path.reverse();
  return path;
}

// ── Build route GeoJSON + compute stats ──────────────────────────────────────
function buildRoute(edgePath) {
  let totalM = 0, pedM = 0, roadM = 0, cycM = 0;
  const features = [];

  for (const eidx of edgePath) {
    const e = graphData.e[eidx];
    const len = e[3], sc = e[5], coords = e[6];
    const hw = graphData.hw[e[4]];
    totalM += len;
    if (sc === 0) pedM += len;
    else if (sc === 1) roadM += len;
    else if (sc === 2) cycM += len;
    else pedM += len;

    const color = sc === 0 ? "#22c55e" : sc === 3 ? "#2563eb" : sc === 2 ? "#7c3aed" : "#ef4444";
    features.push({
      type: "Feature",
      properties: { infra_type: sc, highway: hw, length: len, color },
      geometry: {
        type: "LineString",
        coordinates: coords.map(c => [c[1], c[0]])
      }
    });
  }

  const geojson = { type: "FeatureCollection", features };
  const pedPct = totalM > 0 ? pedM / totalM * 100 : 0;
  const roadPct = totalM > 0 ? roadM / totalM * 100 : 0;
  const cycPct = totalM > 0 ? cycM / totalM * 100 : 0;
  const walkMin = Math.round(totalM / 80);

  return {
    geojson, totalM: Math.round(totalM),
    pedM: Math.round(pedM), roadM: Math.round(roadM), cycM: Math.round(cycM),
    pedPct, roadPct, cycPct, walkMin
  };
}

// ── Navigation UI state ──────────────────────────────────────────────────────
let navMode = false;
let navStep = 0;
let startMarker = null, endMarker = null;
let startNode = -1, endNode = -1;
let mapRef = null;

function toggleNavMode() {
  if (!graphReady) return;
  navMode = !navMode;
  const btn = document.getElementById("nav-btn");
  const hint = document.getElementById("nav-hint");

  if (navMode) {
    btn.classList.add("active");
    document.getElementById("nav-btn-label").textContent = "Navigation (actif)";
    hint.textContent = "Cliquez sur la carte pour le départ";
    navStep = 0;
    document.getElementById("map").classList.add("nav-mode-cursor");
  } else {
    btn.classList.remove("active");
    document.getElementById("nav-btn-label").textContent = "Navigation";
    hint.textContent = "";
    clearRoute();
    document.getElementById("map").classList.remove("nav-mode-cursor");
  }
}

function clearRoute() {
  navStep = 0;
  if (startMarker) { startMarker.remove(); startMarker = null; }
  if (endMarker) { endMarker.remove(); endMarker = null; }
  document.getElementById("route-panel").classList.remove("visible");

  if (mapRef) {
    const src = mapRef.getSource("nav-route");
    if (src) src.setData({ type: "FeatureCollection", features: [] });
  }

  if (navMode) {
    document.getElementById("nav-hint").textContent = "Cliquez sur la carte pour le départ";
  }
}

function handleNavClick(e) {
  if (!navMode || !graphReady) return;
  const { lat, lng } = e.lngLat;

  if (navStep === 0) {
    startNode = nearestNode(lat, lng);
    const sn = graphData.n[startNode];
    if (startMarker) startMarker.remove();
    startMarker = new maplibregl.Marker({ color: "#22c55e" })
      .setLngLat([sn[1], sn[0]])
      .addTo(mapRef);
    navStep = 1;
    document.getElementById("nav-hint").textContent = "Cliquez pour la destination";

  } else if (navStep === 1) {
    endNode = nearestNode(lat, lng);
    const en = graphData.n[endNode];
    if (endMarker) endMarker.remove();
    endMarker = new maplibregl.Marker({ color: "#ef4444" })
      .setLngLat([en[1], en[0]])
      .addTo(mapRef);

    document.getElementById("nav-hint").textContent = "Calcul…";

    requestAnimationFrame(() => {
      const t0 = performance.now();
      const path = dijkstra(startNode, endNode);
      const dt = (performance.now() - t0).toFixed(0);

      if (!path || path.length === 0) {
        document.getElementById("nav-hint").textContent = "Aucun itinéraire trouvé";
        navStep = 2;
        return;
      }

      const route = buildRoute(path);
      console.log(`Route: ${route.totalM}m, ${path.length} edges, ${dt}ms`);

      const src = mapRef.getSource("nav-route");
      if (src) src.setData(route.geojson);

      document.getElementById("route-dist").textContent = route.totalM >= 1000
        ? `${(route.totalM / 1000).toFixed(2)} km`
        : `${route.totalM} m`;
      document.getElementById("route-time").textContent = `≈ ${route.walkMin} min à pied`;

      document.getElementById("bar-ped").style.width = route.pedPct + "%";
      document.getElementById("bar-road").style.width = route.roadPct + "%";
      document.getElementById("bar-cyc").style.width = route.cycPct + "%";

      document.getElementById("stat-ped-m").textContent = `${route.pedM} m`;
      document.getElementById("stat-road-m").textContent = `${route.roadM} m`;
      document.getElementById("stat-cyc-m").textContent = `${route.cycM} m`;

      document.getElementById("stat-ped-pct").textContent = `${route.pedPct.toFixed(0)}%`;
      document.getElementById("stat-road-pct").textContent = `${route.roadPct.toFixed(0)}%`;
      document.getElementById("stat-cyc-pct").textContent = `${route.cycPct.toFixed(0)}%`;

      document.getElementById("route-panel").classList.add("visible");
      document.getElementById("nav-hint").textContent = `Calculé en ${dt} ms`;
      navStep = 2;
    });

  } else {
    clearRoute();
    handleNavClick(e);
  }
}


// ══════════════════════════════════════════════════════════════════════════════
//  MAP INITIALISATION
// ══════════════════════════════════════════════════════════════════════════════

// ── State.txt timestamp ──────────────────────────────────────────────────────
fetch("./state.txt")
  .then(r => r.text())
  .then(txt => {
    const fmtOpts = { dateStyle: "short", timeStyle: "short" };

    const osmMatch = txt.match(/timestamp=(.+)/);
    if (osmMatch) {
      const osmDate = new Date(osmMatch[1].trim().replace(/\\:/g, ":"));
      document.getElementById("osm-date").textContent = `OSM : ${osmDate.toLocaleString("fr-BE", fmtOpts)}`;
    }

    const buildMatch = txt.match(/build_timestamp=(.+)/);
    if (buildMatch) {
      const buildDate = new Date(buildMatch[1].trim());
      document.getElementById("build-date").textContent = `MAJ : ${buildDate.toLocaleString("fr-BE", fmtOpts)}`;
    }
  })
  .catch(() => {
    document.getElementById("osm-date").textContent = "OSM : inconnue";
  });

// ── Stats.json ───────────────────────────────────────────────────────────────
fetch("./stats.json")
  .then(r => r.json())
  .then(s => {
    const avgKm = (s.avg_distance_m / 1000).toFixed(2);
    const trips = s.routed_trips.toLocaleString("fr-BE");
    document.getElementById("routing-stats").innerHTML =
      `Trajets simulés : <span>${trips}</span><br>` +
      `Distance moy. : <span>${avgKm} km</span>`;
  })
  .catch(() => { });

// ── Map setup ────────────────────────────────────────────────────────────────
const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile.bind(protocol));
const PMTILES_URL = new URL("./pedestrian.pmtiles.gz", window.location.href).href;
const EDIT_MIN_ZOOM = 16;

const ROAD_GRAY = "#d5d5d5";
const ROAD_BORDER = "#aaaaaa";

const BASE_STYLE_OVERRIDES = {
  "road_motorway":                    { "line-color": ROAD_GRAY },
  "road_motorway_casing":             { "line-color": ROAD_BORDER },
  "road_motorway_link":               { "line-color": ROAD_GRAY },
  "road_motorway_link_casing":        { "line-color": ROAD_BORDER },
  "road_trunk_primary":               { "line-color": ROAD_GRAY },
  "road_trunk_primary_casing":        { "line-color": ROAD_BORDER },
  "road_trunk_primary_link":          { "line-color": ROAD_GRAY },
  "road_secondary_tertiary":          { "line-color": ROAD_GRAY },
  "road_secondary_tertiary_casing":   { "line-color": ROAD_BORDER },
  "road_major_rail":                  { "line-color": ROAD_BORDER },
  "road_path_pedestrian":             { "line-color": ROAD_GRAY },
  "road_service_track":               { "line-color": ROAD_GRAY },
  "road_service_track_casing":        { "line-color": ROAD_BORDER },
  "road_minor":                       { "line-color": ROAD_GRAY },
  "road_minor_casing":                { "line-color": ROAD_BORDER },
  "road_link":                        { "line-color": ROAD_GRAY },
  "road_link_casing":                 { "line-color": ROAD_BORDER },

  "tunnel_path_pedestrian":           { "line-color": ROAD_GRAY },
  "tunnel_motorway":                  { "line-color": ROAD_GRAY },
  "tunnel_motorway_casing":           { "line-color": ROAD_BORDER },
  "tunnel_motorway_link":             { "line-color": ROAD_GRAY },
  "tunnel_motorway_link_casing":      { "line-color": ROAD_BORDER },
  "tunnel_trunk_primary":             { "line-color": ROAD_GRAY },
  "tunnel_trunk_primary_casing":      { "line-color": ROAD_BORDER },
  "tunnel_secondary_tertiary":        { "line-color": ROAD_GRAY },
  "tunnel_secondary_tertiary_casing": { "line-color": ROAD_BORDER },
  "tunnel_service_track":             { "line-color": ROAD_GRAY },
  "tunnel_service_track_casing":      { "line-color": ROAD_BORDER },
  "tunnel_minor":                     { "line-color": ROAD_GRAY },
  "tunnel_street_casing":             { "line-color": ROAD_BORDER },
  "tunnel_link":                      { "line-color": ROAD_GRAY },
  "tunnel_link_casing":               { "line-color": ROAD_BORDER },

  "bridge_path_pedestrian":           { "line-color": ROAD_GRAY },
  "bridge_path_pedestrian_casing":    { "line-color": ROAD_BORDER },
  "bridge_motorway":                  { "line-color": ROAD_GRAY },
  "bridge_motorway_casing":           { "line-color": ROAD_BORDER },
  "bridge_motorway_link":             { "line-color": ROAD_GRAY },
  "bridge_motorway_link_casing":      { "line-color": ROAD_BORDER },
  "bridge_trunk_primary":             { "line-color": ROAD_GRAY },
  "bridge_trunk_primary_casing":      { "line-color": ROAD_BORDER },
  "bridge_secondary_tertiary":        { "line-color": ROAD_GRAY },
  "bridge_secondary_tertiary_casing": { "line-color": ROAD_BORDER },
  "bridge_service_track":             { "line-color": ROAD_GRAY },
  "bridge_service_track_casing":      { "line-color": ROAD_BORDER },
  "bridge_street":                    { "line-color": ROAD_GRAY },
  "bridge_street_casing":             { "line-color": ROAD_BORDER },
  "bridge_link":                      { "line-color": ROAD_GRAY },
  "bridge_link_casing":               { "line-color": ROAD_BORDER },
};

// ── Réseau de base (masqué au démarrage) ─────────────────────────────────────
const HIGHWAY_LAYERS = [
  { id: "living_street", label: "Rue partagée",     color: "#16a34a", width: 3,   dash: false, hidden: true },
  { id: "pedestrian",    label: "Zone piétonne",     color: "#15803d", width: 3,   dash: false, hidden: true },
  { id: "footway",       label: "Trottoir / allée",  color: "#22c55e", width: 2,   dash: false, hidden: true },
  { id: "cycleway",      label: "Piste cyclable",    color: "#0000ff", width: 2.5, dash: false, hidden: true },
  { id: "path",          label: "Sentier",           color: "#86efac", width: 1.5, dash: true,  hidden: true },
  { id: "steps",         label: "Escaliers",         color: "#166534", width: 2,   dash: true,  hidden: true },
];

// Helper: null-safe flow_pct getter
const FLOW_PCT = ["to-number", ["get", "flow_pct"], 0];

const PEDESTRIAN_LAYERS = [
  ...HIGHWAY_LAYERS.map(({ id, color, width, dash, hidden }) => ({
    id: `highway-${id}`, type: "line", source: "pedestrian", "source-layer": "highways",
    filter: ["==", ["get", "highway"], id],
    layout: { "line-cap": "round", "line-join": "round", visibility: hidden ? "none" : "visible" },
    paint: {
      "line-color": color,
      "line-width": ["interpolate", ["linear"], ["zoom"], 8, width * 0.4, 14, width, 18, width * 2.5],
      "line-opacity": 0.9,
      ...(dash ? { "line-dasharray": [3, 3] } : {})
    }
  })),
  {
    id: "highway-crossing", type: "circle", source: "pedestrian", "source-layer": "highways",
    filter: ["==", ["get", "highway"], "crossing"],
    layout: { visibility: "none" },
    paint: {
      "circle-color": "#15803d",
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4],
      "circle-stroke-color": "#15803d", "circle-stroke-width": 1
    }
  },
  {
    id: "forced-segments", type: "line", source: "pedestrian", "source-layer": "forced_segments",
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["match", ["get", "highway"], ["residential", "service"], "#f59e0b", ["unclassified"], "#f97316", ["tertiary", "tertiary_link"], "#ef4444", ["secondary", "secondary_link"], "#dc2626", ["primary", "primary_link"], "#991b1b", "#f97316"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["interpolate", ["linear"], FLOW_PCT, 0, 1, 100, 4], 16, ["interpolate", ["linear"], FLOW_PCT, 0, 2.5, 100, 12]],
      "line-opacity": 0.88
    }
  },
  {
    id: "forced-cycleway", type: "line", source: "pedestrian", "source-layer": "forced_cycleway",
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": "#7c3aed",
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["interpolate", ["linear"], FLOW_PCT, 0, 1, 100, 4], 16, ["interpolate", ["linear"], FLOW_PCT, 0, 2.5, 100, 12]],
      "line-opacity": 0.88
    }
  },
  {
    id: "flow-ped", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["==", ["get", "infra_type"], "pedestrian"],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["interpolate", ["linear"], FLOW_PCT, 0, "#bbf7d0", 50, "#16a34a", 100, "#14532d"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 3], 16, ["interpolate", ["linear"], FLOW_PCT, 0, 1, 100, 8]],
      "line-opacity": 0.85
    }
  },
  {
    id: "flow-cycleway", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["in", ["get", "infra_type"], ["literal", ["cycleway_no_foot", "cycleway_foot_yes"]]],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["match", ["get", "infra_type"],
        "cycleway_foot_yes", ["interpolate", ["linear"], FLOW_PCT, 0, "#bfdbfe", 50, "#2563eb", 100, "#1e3a5f"],
        ["interpolate", ["linear"], FLOW_PCT, 0, "#ede9fe", 50, "#7c3aed", 100, "#3b0764"]
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 3], 16, ["interpolate", ["linear"], FLOW_PCT, 0, 1, 100, 8]],
      "line-opacity": 0.85
    }
  },
  {
    id: "flow-road", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["==", ["get", "infra_type"], "road"],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["interpolate", ["linear"], FLOW_PCT, 0, "#fdba74", 50, "#ef4444", 100, "#7f1d1d"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.8, 100, 4], 16, ["interpolate", ["linear"], FLOW_PCT, 0, 1.2, 100, 8.5]],
      "line-opacity": 0.8
    }
  },
  {
    id: "street-scores", type: "circle", source: "pedestrian", "source-layer": "street_scores",
    minzoom: 13, layout: { visibility: "none" },
    paint: {
      "circle-color": ["interpolate", ["linear"], ["to-number", ["get", "walkability"], 0], 0, "#ef4444", 1, "#22c55e"],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 5, 16, 10],
      "circle-stroke-color": "#fff", "circle-stroke-width": 1.5
    }
  },
  {
    id: "sidewalk-gaps", type: "line", source: "pedestrian", "source-layer": "sidewalk_gaps",
    minzoom: 12, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": "#f59e0b",
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 6],
      "line-opacity": 0.85,
      "line-dasharray": [4, 3]
    }
  },
  {
    id: "sidewalk-roads", type: "line", source: "pedestrian", "source-layer": "sidewalk_roads",
    minzoom: 13, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ["match", ["get", "sw"],
        "separate",   "#22c55e",
        "yes",        "#06b6d4",
        "documented", "#22c55e",
        "partial",    "#f5700b",
        "unknown",    "#b587c7",
        "#9ca3af"
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"], 13, 2, 16, 5, 18, 8],
      "line-opacity": ["match", ["get", "sw"],
        "unknown", 0.45,
        0.85
      ]
    }
  }
];

// ── Hover popup config ───────────────────────────────────────────────────────
const HOVER_LAYERS = [
  {
    ids: ["sidewalk-gaps"],
    format: p => `
      <div class="popup-title">🚧 Trottoir un seul côté</div>
      <div class="popup-row"><span class="label">Rue</span><span class="value">${p.name || "—"}</span></div>
    `
  },
  {
    ids: ["sidewalk-roads"],
    format: p => {
      const swLabels = {
        separate:   "✅ sidewalk:both=separate",
        yes:        "✅ sidewalk=yes — mappable en separate",
        documented: "✅ Deux côtés documentés",
        partial:    "⚠️ Un seul côté documenté",
        unknown:    "— Aucun tag sidewalk"
      };
      return `
        <div class="popup-title">🏷 Tags trottoir</div>
        <div class="popup-row"><span class="label">Rue</span><span class="value">${p.name || "—"}</span></div>
        <div class="popup-row"><span class="label">Statut</span><span class="value">${swLabels[p.sw] || p.sw || "?"}</span></div>
      `;
    }
  },
  {
    ids: ["forced-segments", "forced-cycleway"],
    format: p => `
      <div class="popup-title">⚠ Segment forcé</div>
      <div class="popup-row"><span class="label">Type</span><span class="value">${p.highway || "—"}</span></div>
      <div class="popup-row"><span class="label">Infra</span><span class="value">${p.infra_type || "—"}</span></div>
      <div class="popup-row"><span class="label">Flux</span><span class="value">${p.flow || 0} trajets</span></div>
      <div class="popup-row"><span class="label">Flux relatif</span><span class="value">${p.flow_pct || 0}%</span></div>
      <div class="popup-row"><span class="label">Longueur</span><span class="value">${p.length_m || 0} m</span></div>
    `
  },
  {
    ids: ["flow-ped", "flow-cycleway", "flow-road"],
    format: p => `
      <div class="popup-title">📊 Flux simulé</div>
      <div class="popup-row"><span class="label">Infra</span><span class="value">${(p.infra_type || "—").replace("_", " ")}</span></div>
      <div class="popup-row"><span class="label">Flux relatif</span><span class="value">${p.flow_pct || 0}%</span></div>
    `
  },
  {
    ids: ["street-scores"],
    format: p => {
      const swLabels = { both: "✅ Deux côtés", partial: "⚠️ Un seul côté", none: "❌ Aucun", unknown: "❓ Non renseigné" };
      return `
        <div class="popup-title">🏙 ${p.street || "Rue inconnue"}</div>
        <div class="popup-row"><span class="label">Marchabilité</span><span class="value">${((p.walkability || 0) * 100).toFixed(0)}%</span></div>
        <div class="popup-row"><span class="label">Score brut</span><span class="value">${((p.walkability_raw || 0) * 100).toFixed(0)}%</span></div>
        <div class="popup-row"><span class="label">Trottoir</span><span class="value">${swLabels[p.sidewalk] || p.sidewalk || "?"}</span></div>
        <div class="popup-row"><span class="label">Infra piétonne</span><span class="value">${Math.round(p.ped_meters || 0)} m</span></div>
        <div class="popup-row"><span class="label">Cycleway (no foot)</span><span class="value">${Math.round(p.cycleway_meters || 0)} m</span></div>
        <div class="popup-row"><span class="label">Total routé</span><span class="value">${Math.round(p.total_meters || 0)} m</span></div>
      `;
    }
  },
  {
    ids: HIGHWAY_LAYERS.map(l => `highway-${l.id}`).concat(["highway-crossing"]),
    format: p => {
      const entries = Object.entries(p).filter(([k]) => !k.startsWith("@") && k !== "tippecanoe");
      return `
        <div class="popup-title">🛤 Infrastructure</div>
        ${entries.map(([k, v]) => `<div class="popup-row"><span class="label">${k}</span><span class="value">${v}</span></div>`).join("")}
      `;
    }
  },
];

// ── Load style & init ────────────────────────────────────────────────────────
fetch("https://tiles.openfreemap.org/styles/liberty")
  .then(r => r.json())
  .then(libertyStyle => {
    fetch("./style.json")
      .then(r => r.json())
      .then(localStyle => {
        const allowedIds = new Set(Object.keys(BASE_STYLE_OVERRIDES));
        const localPaintById = new Map(
          (localStyle.layers || []).filter(l => allowedIds.has(l.id)).map(l => [l.id, l.paint || {}])
        );
        libertyStyle.layers = (libertyStyle.layers || []).map(layer => {
          const localPaint = localPaintById.get(layer.id) || {};
          const overrides = BASE_STYLE_OVERRIDES[layer.id] || {};
          return { ...layer, paint: { ...(layer.paint || {}), ...localPaint, ...overrides } };
        });
        initMap(libertyStyle);
      })
      .catch(() => {
        libertyStyle.layers = (libertyStyle.layers || []).map(layer => {
          const ov = BASE_STYLE_OVERRIDES[layer.id];
          return ov ? { ...layer, paint: { ...(layer.paint || {}), ...ov } } : layer;
        });
        initMap(libertyStyle);
      });
  })
  .catch(() => initMap("https://tiles.openfreemap.org/styles/liberty"));

function initMap(style) {
  const map = new maplibregl.Map({
    container: "map", style,
    center: [4.3517, 50.8503], zoom: 12,
    attributionControl: false
  });
  mapRef = map;

  map.addControl(
    new maplibregl.AttributionControl({
      compact: false,
      customAttribution: ['<a href="https://github.com/PasLoin/Brussels-Pedestrian-Network" target="_blank" rel="noopener">PasLoin</a>']
    }),
    "bottom-right"
  );

  map.on("load", () => {
    map.addSource("pedestrian", { type: "vector", url: `pmtiles://${PMTILES_URL}` });
    PEDESTRIAN_LAYERS.forEach(layer => map.addLayer(layer));

    // ── Navigation route source + layers ─────────────────────────────────
    map.addSource("nav-route", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] }
    });

    map.addLayer({
      id: "nav-route-casing", type: "line", source: "nav-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#000",
        "line-width": ["interpolate", ["linear"], ["zoom"], 10, 6, 16, 14],
        "line-opacity": 0.4
      }
    });

    map.addLayer({
      id: "nav-route-line", type: "line", source: "nav-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": ["get", "color"],
        "line-width": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 10],
        "line-opacity": 0.92
      }
    });

    map.on("click", handleNavClick);

    // ── Légende ──────────────────────────────────────────────────────────
    const legendEl = document.getElementById("legend-content");
    const addSection = (txt) => { const s = document.createElement("div"); s.className = "legend-section"; s.textContent = txt; legendEl.appendChild(s); };

    const makeItem = ({ layerId, label, color, color2, swatchType = "line", dashed = false }) => {
      const item = document.createElement("div"); item.className = "legend-item";
      const swatch = document.createElement("div"); swatch.className = `legend-${swatchType}`;
      if (color2) { swatch.classList.add(swatchType === "dot" ? "gradient-dot" : "gradient"); swatch.style.setProperty("--c1", color); swatch.style.setProperty("--c2", color2); }
      else if (dashed) { swatch.classList.add("dashed"); swatch.style.setProperty("--c", color); }
      else { swatch.style.background = color; }
      const lbl = document.createElement("span"); lbl.className = "legend-label"; lbl.textContent = label;
      item.append(swatch, lbl);
      const updateState = () => item.classList.toggle("hidden", map.getLayoutProperty(layerId, "visibility") === "none");
      updateState();
      item.onclick = () => { const v = map.getLayoutProperty(layerId, "visibility") === "none" ? "visible" : "none"; map.setLayoutProperty(layerId, "visibility", v); updateState(); };
      return item;
    };

    addSection("Routage simulé");
    legendEl.appendChild(makeItem({ layerId: "forced-segments", label: "Forcé sur route", color: "#f59e0b", color2: "#991b1b" }));
    legendEl.appendChild(makeItem({ layerId: "forced-cycleway", label: "Forcé sur piste cyclable", color: "#c4b5fd", color2: "#3b0764" }));
    legendEl.appendChild(makeItem({ layerId: "flow-ped", label: "Flux piéton", color: "#bbf7d0", color2: "#14532d" }));
    legendEl.appendChild(makeItem({ layerId: "flow-cycleway", label: "Flux cycleway", color: "#bfdbfe", color2: "#3b0764" }));
    legendEl.appendChild(makeItem({ layerId: "flow-road", label: "Flux sur route", color: "#fed7aa", color2: "#7f1d1d" }));
    legendEl.appendChild(makeItem({ layerId: "street-scores", label: "Score marchabilité", color: "#ef4444", color2: "#22c55e", swatchType: "dot" }));

    addSection("Analyse spatiale (Désactivé)");
    legendEl.appendChild(makeItem({ layerId: "sidewalk-gaps", label: "Trottoir un seul côté", color: "#f59e0b", dashed: true }));
    legendEl.appendChild(makeItem({ layerId: "sidewalk-roads", label: "Tags sidewalk", color: "#9ca3af", color2: "#15803d" }));

    addSection("Réseau de base (Désactivé)");
    HIGHWAY_LAYERS.forEach(l => legendEl.appendChild(makeItem({ layerId: `highway-${l.id}`, label: l.label, color: l.color, dashed: l.dash })));

    // ── Hover popups ─────────────────────────────────────────────────────
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: "280px" });
    const allHoverIds = HOVER_LAYERS.flatMap(h => h.ids);

    map.on("mousemove", (e) => {
      if (navMode && navStep < 2) { popup.remove(); return; }

      const visibleIds = allHoverIds.filter(id => {
        try { return map.getLayoutProperty(id, "visibility") !== "none"; }
        catch { return false; }
      });
      if (!visibleIds.length) { popup.remove(); map.getCanvas().style.cursor = navMode ? "" : ""; return; }

      const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
      if (!features.length) { popup.remove(); if (!navMode) map.getCanvas().style.cursor = ""; return; }

      if (!navMode) map.getCanvas().style.cursor = "pointer";
      const f = features[0];
      const hoverConf = HOVER_LAYERS.find(h => h.ids.includes(f.layer.id));
      if (!hoverConf) return;

      popup.setLngLat(e.lngLat).setHTML(hoverConf.format(f.properties)).addTo(map);
    });

    map.on("mouseleave", allHoverIds, () => { popup.remove(); if (!navMode) map.getCanvas().style.cursor = ""; });
  });

  map.on("moveend", () => {
    const z = map.getZoom(); const c = map.getCenter();
    document.getElementById("zoom-val").textContent = z.toFixed(1);
    const btn = document.getElementById("edit-btn");
    if (z >= EDIT_MIN_ZOOM) { btn.href = `https://www.openstreetmap.org/edit#map=${Math.round(z)}/${c.lat.toFixed(5)}/${c.lng.toFixed(5)}`; btn.classList.remove("disabled"); }
    else btn.classList.add("disabled");
  });
}
