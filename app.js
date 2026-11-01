const SMALL_SCREEN_QUERY = "(max-width: 600px)";
let legendAutoCollapsed = false;

function toggleHeader() {
  const el = document.getElementById("header");
  const isOpen = el.classList.toggle("open");
  el.classList.toggle("closed");
  document.getElementById("header-toggle").setAttribute("aria-expanded", isOpen);
}

function setLegendOpen(open) {
  const el = document.getElementById("legend");
  el.classList.toggle("open", open);
  el.classList.toggle("closed", !open);
  document.getElementById("legend-toggle").setAttribute("aria-expanded", open);
}

function toggleLegend() {
  legendAutoCollapsed = false;
  setLegendOpen(!document.getElementById("legend").classList.contains("open"));
}

function showRoutePanel() {
  document.getElementById("route-panel").classList.add("visible");
  const legendOpen = document.getElementById("legend").classList.contains("open");
  if (legendOpen && window.matchMedia(SMALL_SCREEN_QUERY).matches) {
    setLegendOpen(false);
    legendAutoCollapsed = true;
  }
}

function hideRoutePanel() {
  document.getElementById("route-panel").classList.remove("visible");
  if (legendAutoCollapsed) {
    legendAutoCollapsed = false;
    setLegendOpen(true);
  }
}

(function () {
  if (window.innerWidth <= 600) {
    const legend = document.getElementById("legend");
    legend.classList.remove("open");
    legend.classList.add("closed");
    document.getElementById("legend-toggle").setAttribute("aria-expanded", "false");

    const header = document.getElementById("header");
    header.classList.remove("open");
    header.classList.add("closed");
    document.getElementById("header-toggle").setAttribute("aria-expanded", "false");
  }
})();

function popupTitle(color, text) {
  const sw = color ? `<span class="popup-swatch" style="--c:${color}"></span>` : "";
  return `<div class="popup-title">${sw}${text}</div>`;
}

function escapeHTML(str) {
  if (!str) return str;
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function updateFlowFilter(rawValue) {
  const minPct = parseInt(rawValue, 10);
  document.getElementById("flow-threshold-val").textContent = minPct + " %";
  if (!mapRef) return;
  const baseFilter = ["==", ["get", "infra_type"], "road"];
  const filter = minPct > 0
    ? ["all", baseFilter, [">=", ["to-number", ["get", "flow_pct"], 0], minPct]]
    : baseFilter;
  setFilterIfLayer(mapRef, "flow-road", filter);
}

const SIDEWALK_STATUSES = [
  { value: "separate",   label: "separate",          color: "#22c55e" },
  { value: "yes",        label: "yes",               color: "#06b6d4" },
  { value: "documented", label: "documenté (both)",  color: "#22c55e" },
  { value: "partial",    label: "partial (1 côté)",  color: "#f5700b" },
  { value: "unknown",    label: "aucun tag",         color: "#b587c7" },
];
const activeSidewalkStatuses = new Set(SIDEWALK_STATUSES.map(s => s.value));

const updateSidewalkFilter = makeMembershipFilterUpdater(() => mapRef, "sidewalk-roads", "sw", activeSidewalkStatuses, SIDEWALK_STATUSES);

const MISSING_CROSSING_TYPES = [
  { value: "missing_way", label: "Way non mappé",               color: "#f97316" },
  { value: "missing_tag", label: "Tag footway=crossing absent",  color: "#eab308" },
  { value: "wrong_tag",   label: "Taguée footway=sidewalk",      color: "#dc2626" },
];
const activeMissingTypes = new Set(MISSING_CROSSING_TYPES.map(t => t.value));

const updateMissingCrossingsFilter = makeMembershipFilterUpdater(() => mapRef, "missing-crossings", "type", activeMissingTypes, MISSING_CROSSING_TYPES);

const KERB_ISSUE_TYPES = [
  { value: "kerb_missing",  label: "Kerb absent",             color: "#1e3a8a" },
  { value: "kerb_untagged", label: "Kerb sans tactile_paving", color: "#7c2d12" },
];
const activeKerbIssueTypes = new Set();

const updateKerbIssuesFilter = makeMembershipFilterUpdater(() => mapRef, "kerb-issues", "type", activeKerbIssueTypes, KERB_ISSUE_TYPES);

const ISLAND_TYPES = [
  { value: "unjoined", label: "Jonction manquante (≤ 2 m)", color: "#db2777" },
  { value: "isolated", label: "Îlot isolé",                 color: "#0d9488" },
  { value: "level",    label: "Discontinuité de niveau",    color: "#ea580c" },
];
const activeIslandTypes = new Set(ISLAND_TYPES.map(t => t.value));

const updateIslandsFilter = makeMembershipFilterUpdater(() => mapRef, "graph-islands", "type", activeIslandTypes, ISLAND_TYPES);

let graphData = null;
let adjList   = null;
let mainComponent = null;
let groundEdges = null;
let graphReady = false;

fetch("./graph.json")
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(data => {
    graphData = data;
    adjList = buildAdjacency(data);
    groundEdges = groundSnappable(data);
    mainComponent = computeMainComponent(data.n.length, data.e);
    graphReady = true;
    const btn = document.getElementById("nav-btn");
    btn.classList.remove("loading");
    btn.setAttribute("aria-busy", "false");
    document.getElementById("nav-btn-label").textContent = "Navigation";
    console.log(`Graph loaded: ${data.n.length} nodes, ${data.e.length} edges`);
  })
  .catch(err => {
    console.warn("graph.json not available:", err);
    document.getElementById("nav-btn-label").textContent = "Navigation (indisponible)";
    document.getElementById("nav-btn").classList.add("disabled");
    document.getElementById("nav-btn").setAttribute("aria-busy", "false");
  });

let navMode = false, navStep = 0;
let startMarker = null, endMarker = null;
let startSnap = null, endSnap = null;
let mapRef = null;

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && navMode) toggleNavMode(); });

function toggleNavMode() {
  if (!graphReady) return;
  navMode = !navMode;
  const btn  = document.getElementById("nav-btn");
  const hint = document.getElementById("nav-hint");
  btn.setAttribute("aria-pressed", navMode);
  if (navMode) {
    btn.classList.add("active");
    document.getElementById("nav-btn-label").textContent = "Quitter la navigation";
    hint.textContent = "Cliquez sur la carte pour placer le départ";
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
  if (endMarker)   { endMarker.remove();   endMarker   = null; }
  hideRoutePanel();
  if (mapRef) {
    const src = mapRef.getSource("nav-route");
    if (src) src.setData({ type: "FeatureCollection", features: [] });
  }
  if (navMode) document.getElementById("nav-hint").textContent = "Cliquez sur la carte pour placer le départ";
}

function handleNavClick(e) {
  if (!navMode || !graphReady) return;
  const { lat, lng } = e.lngLat;
  if (navStep === 0) {
    startSnap = snapToNetwork(graphData, lat, lng, mainComponent, groundEdges);
    if (startMarker) startMarker.remove();
    startMarker = new maplibregl.Marker({ color: "#22c55e" }).setLngLat([lng, lat]).addTo(mapRef);
    navStep = 1;
    document.getElementById("nav-hint").textContent = "Cliquez pour placer l'arrivée";
  } else if (navStep === 1) {
    endSnap = snapToNetwork(graphData, lat, lng, mainComponent, groundEdges);
    if (endMarker) endMarker.remove();
    endMarker = new maplibregl.Marker({ color: "#ef4444" }).setLngLat([lng, lat]).addTo(mapRef);
    document.getElementById("nav-hint").textContent = "Calcul…";
    requestAnimationFrame(() => {
      const t0 = performance.now();
      const found = startSnap && endSnap ? routeBetween(graphData, adjList, startSnap, endSnap) : null;
      const dt = (performance.now() - t0).toFixed(0);
      if (!found || found.legs.length === 0) {
        document.getElementById("nav-hint").textContent = "Aucun itinéraire trouvé";
        navStep = 2; return;
      }
      const route = buildRoute(graphData, found.legs);
      const src = mapRef.getSource("nav-route");
      if (src) src.setData(route.geojson);
      document.getElementById("route-dist").textContent = route.totalM >= 1000
        ? `${(route.totalM / 1000).toLocaleString("fr-BE", { maximumFractionDigits: 2 })} km` : `${route.totalM} m`;
      document.getElementById("route-time").textContent = `≈ ${route.walkMin} min à pied`;
      document.getElementById("bar-ped").style.width  = route.pedPct  + "%";
      document.getElementById("bar-road").style.width = route.roadPct + "%";
      document.getElementById("bar-cyc").style.width  = route.cycPct  + "%";
      document.getElementById("stat-ped-m").textContent   = `${route.pedM} m`;
      document.getElementById("stat-road-m").textContent  = `${route.roadM} m`;
      document.getElementById("stat-cyc-m").textContent   = `${route.cycM} m`;
      document.getElementById("stat-ped-pct").textContent  = `${route.pedPct.toFixed(0)}%`;
      document.getElementById("stat-road-pct").textContent = `${route.roadPct.toFixed(0)}%`;
      document.getElementById("stat-cyc-pct").textContent  = `${route.cycPct.toFixed(0)}%`;
      showRoutePanel();
      document.getElementById("nav-hint").textContent = `Calculé en ${dt} ms`;
      navStep = 2;
    });
  } else {
    clearRoute();
    handleNavClick(e);
  }
}

fetch("./state.txt")
  .then(r => r.text())
  .then(txt => {
    const fmtOpts = { dateStyle: "short", timeStyle: "short" };
    const jsonMatch = txt.match(/\{[\s\S]*?\}/);
    if (jsonMatch) {
      try {
        const state = JSON.parse(jsonMatch[0]);
        if (state.timestamp) {
          document.getElementById("osm-date").textContent =
            `Données OSM : ${new Date(state.timestamp).toLocaleString("fr-BE", fmtOpts)}`;
        }
      } catch (e) { console.warn("state.txt JSON parse error:", e); }
    }
    const buildMatch = txt.match(/build_timestamp=(.+)/);
    if (buildMatch) {
      document.getElementById("build-date").textContent =
        `Calcul : ${new Date(buildMatch[1].trim()).toLocaleString("fr-BE", fmtOpts)}`;
    }
  })
  .catch(() => { document.getElementById("osm-date").textContent = "Données OSM : date inconnue"; });

fetch("./stats.json")
  .then(r => r.json())
  .then(s => {
    const avgKm = (s.avg_distance_m / 1000).toFixed(2);
    const trips = s.routed_trips.toLocaleString("fr-BE");
    document.getElementById("routing-stats").innerHTML =
      `Trajets simulés : <span>${escapeHTML(trips)}</span><br>` +
      `Distance moyenne : <span>${escapeHTML(avgKm)} km</span>`;
  })
  .catch(() => { });

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile.bind(protocol));
const PMTILES_URL = new URL("./pedestrian.pmtiles", window.location.href).href;
const EDIT_MIN_ZOOM = 16;

const ROAD_GRAY   = "#d5d5d5";
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

const HIGHWAY_LAYERS = [
  { id: "living_street", label: "Rue partagée",     color: "#16a34a", width: 3,   dash: false, hidden: true },
  { id: "pedestrian",    label: "Zone piétonne",     color: "#15803d", width: 3,   dash: false, hidden: true },
  { id: "footway",       label: "Trottoir / allée",  color: "#22c55e", width: 2,   dash: false, hidden: true },
  { id: "cycleway",      label: "Piste cyclable",    color: "#0000ff", width: 2.5, dash: false, hidden: true },
  { id: "path",          label: "Sentier",           color: "#86efac", width: 1.5, dash: true,  hidden: true },
  { id: "steps",         label: "Escaliers",         color: "#166534", width: 2,   dash: true,  hidden: true },
  { id: "track",         label: "Chemin rural / forestier", color: "#a16207", width: 1.5, dash: true, hidden: true },
  { id: "platform",      label: "Quai d'arrêt",      color: "#64748b", width: 2.5, dash: false, hidden: true },
];

const ELEVATOR_COLOR = "#4338ca";
const ELEVATOR_LAYER_IDS = ["highway-elevator", "highway-elevator-line"];
const IS_ELEVATOR = ["any", ["==", ["get", "highway"], "elevator"], ["==", ["get", "amenity"], "elevator"]];

const FLOW_PCT = ["to-number", ["get", "flow_pct"], 0];

const FLOW_COLORS = {
  pedestrian: "#16a34a",
  road: "#ef4444",
  cycleway_foot_yes: "#2563eb",
  cycleway_no_foot: "#7c3aed",
};

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
    id: "highway-elevator-line", type: "line", source: "pedestrian", "source-layer": "highways",
    filter: ["all", ["==", ["geometry-type"], "LineString"], IS_ELEVATOR],
    layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ELEVATOR_COLOR,
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4, 18, 7],
      "line-opacity": 0.9
    }
  },
  {
    id: "highway-elevator", type: "circle", source: "pedestrian", "source-layer": "highways",
    filter: ["all", ["==", ["geometry-type"], "Point"], IS_ELEVATOR],
    layout: { visibility: "none" },
    paint: {
      "circle-color": ELEVATOR_COLOR,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 2, 14, 3.5, 18, 7],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 9, 0.5, 16, 1.5]
    }
  },
  {
    id: "flow-ped", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["==", ["get", "infra_type"], "pedestrian"],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["interpolate", ["linear"], FLOW_PCT, 0, "#bbf7d0", 50, "#16a34a", 100, "#14532d"],
      "line-width": ["interpolate", ["linear"], ["zoom"],
        10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 3],
        16, ["interpolate", ["linear"], FLOW_PCT, 0, 1,   100, 8]
      ],
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
      "line-width": ["interpolate", ["linear"], ["zoom"],
        10, ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 3],
        16, ["interpolate", ["linear"], FLOW_PCT, 0, 1,   100, 8]
      ],
      "line-opacity": 0.85
    }
  },
  {
    id: "flow-road", type: "line", source: "pedestrian", "source-layer": "flow_edges",
    filter: ["==", ["get", "infra_type"], "road"],
    layout: { "line-cap": "round", "line-join": "round", visibility: "visible" },
    paint: {
      "line-color": ["interpolate", ["linear"], FLOW_PCT,
        0, "#fdba74", 20, "#f97316", 40, "#ef4444", 60, "#dc2626", 80, "#991b1b", 100, "#450a0a"
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"],
        10, ["match", ["get", "highway"],
          ["primary",   "primary_link"],   ["interpolate", ["linear"], FLOW_PCT, 0, 1.4, 100, 7.0],
          ["secondary", "secondary_link"], ["interpolate", ["linear"], FLOW_PCT, 0, 1.1, 100, 5.5],
          ["tertiary",  "tertiary_link"],  ["interpolate", ["linear"], FLOW_PCT, 0, 0.9, 100, 4.5],
          ["residential","unclassified"],  ["interpolate", ["linear"], FLOW_PCT, 0, 0.7, 100, 3.5],
          ["interpolate", ["linear"], FLOW_PCT, 0, 0.5, 100, 2.5]
        ],
        16, ["match", ["get", "highway"],
          ["primary",   "primary_link"],   ["interpolate", ["linear"], FLOW_PCT, 0, 3.0, 100, 15.0],
          ["secondary", "secondary_link"], ["interpolate", ["linear"], FLOW_PCT, 0, 2.4, 100, 12.0],
          ["tertiary",  "tertiary_link"],  ["interpolate", ["linear"], FLOW_PCT, 0, 1.9, 100,  9.5],
          ["residential","unclassified"],  ["interpolate", ["linear"], FLOW_PCT, 0, 1.4, 100,  7.5],
          ["interpolate", ["linear"], FLOW_PCT, 0, 1.0, 100,  5.5]
        ]
      ],
      "line-opacity": 0.8
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
      "line-opacity": ["match", ["get", "sw"], "unknown", 0.45, 0.85]
    }
  },
  {
    id: "missing-crossings", type: "circle", source: "pedestrian",
    "source-layer": "missing_crossings",
    minzoom: 12,
    layout: { visibility: "none" },
    paint: {
      "circle-color": ["match", ["get", "type"],
        "missing_way", "#f97316",
        "missing_tag", "#eab308",
        "wrong_tag",   "#dc2626",
        "#f97316"
      ],
      "circle-radius": 12,
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    }
  },
  {
    id: "footway-crossing-candidates", type: "line", source: "pedestrian",
    "source-layer": "footway_crossing_candidates",
    minzoom: 13, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": "#7f1d1d",
      "line-width": ["interpolate", ["linear"], ["zoom"], 13, 3, 16, 7, 18, 10],
      "line-opacity": 0.9,
      "line-dasharray": [1, 2]
    }
  },
  {
    id: "tactile-paving-issues", type: "circle", source: "pedestrian",
    "source-layer": "tactile_paving_issues",
    minzoom: 13, layout: { visibility: "none" },
    paint: {
      "circle-color": "#a855f7",
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 4, 16, 9],
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    }
  },
  {
    id: "graph-islands", type: "line", source: "pedestrian",
    "source-layer": "graph_islands",
    minzoom: 12, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": ["match", ["get", "type"],
        "unjoined", "#db2777",
        "isolated", "#0d9488",
        "level",    "#ea580c",
        "#0d9488"
      ],
      "line-width": ["interpolate", ["linear"], ["zoom"], 12, 3, 16, 7, 18, 10],
      "line-opacity": 0.9
    }
  },
  {
    id: "kerb-issues", type: "circle", source: "pedestrian",
    "source-layer": "kerb_issues",
    minzoom: 13, layout: { visibility: "none" },
    paint: {
      "circle-color": ["match", ["get", "type"],
        "kerb_missing",  "#1e3a8a",
        "kerb_untagged", "#7c2d12",
        "#1e3a8a"
      ],
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 4, 16, 9],
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
      "circle-opacity": 0.9,
    }
  },
];

const HOVER_LAYERS = [
  {
    ids: ["sidewalk-gaps"],
    format: p => `
      ${popupTitle("#f59e0b", "Trottoir d'un seul côté")}
      <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
    `
  },
  {
    ids: ["footway-crossing-candidates"],
    format: p => `
      ${popupTitle("#7f1d1d", "Traversée sans footway=crossing ?")}
      <div class="popup-row"><span class="label">Rue traversée</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
      <div class="popup-row"><span class="label">Longueur</span><span class="value">${escapeHTML(p.length_m)} m</span></div>
    `
  },
  {
    ids: ["sidewalk-roads"],
    format: p => {
      const swLabels = {
        separate:   "sidewalk:both=separate",
        yes:        "sidewalk=yes, à mapper en separate",
        documented: "Deux côtés documentés",
        partial:    "Un seul côté documenté",
        unknown:    "Aucun tag sidewalk"
      };
      return `
        ${popupTitle((SIDEWALK_STATUSES.find(s => s.value === p.sw) || {}).color, "Tags sidewalk")}
        <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
        <div class="popup-row"><span class="label">Statut</span><span class="value">${escapeHTML(swLabels[p.sw] || p.sw || "?")}</span></div>
      `;
    }
  },
  {
    ids: ["flow-ped", "flow-cycleway", "flow-road"],
    format: p => `
      ${popupTitle(FLOW_COLORS[p.infra_type], "Flux simulé")}
      <div class="popup-row"><span class="label">Infrastructure</span><span class="value">${escapeHTML((p.infra_type || "—").replace(/_/g, " "))}</span></div>
      <div class="popup-row"><span class="label">highway</span><span class="value">${escapeHTML(p.highway || "—")}</span></div>
      <div class="popup-row"><span class="label">Flux relatif</span><span class="value">${escapeHTML(p.flow_pct) || 0} %</span></div>
    `
  },
  {
    ids: HIGHWAY_LAYERS.map(l => `highway-${l.id}`).concat(["highway-crossing"], ELEVATOR_LAYER_IDS),
    format: p => {
      const entries = Object.entries(p).filter(([k]) => !k.startsWith("@") && k !== "tippecanoe");
      const isElevator = p.highway === "elevator" || p.amenity === "elevator";
      const titleColor = isElevator ? ELEVATOR_COLOR : ((HIGHWAY_LAYERS.find(l => l.id === p.highway) || {}).color || "#15803d");
      return `
        ${popupTitle(titleColor, escapeHTML(p.highway || (isElevator ? "elevator" : "Infrastructure")))}
        ${entries.map(([k, v]) => `<div class="popup-row"><span class="label">${escapeHTML(k)}</span><span class="value">${escapeHTML(v)}</span></div>`).join("")}
      `;
    }
  },
];

function formatWrongTagCrossing(p) {
  const nid = parseInt(p.osm_id, 10) || 0;
  const wid = parseInt(p.way_osm_id, 10) || 0;
  const val = p.footway_value || "sidewalk";
  const objs = [nid > 0 ? `n${nid}` : "", wid > 0 ? `w${wid}` : ""].filter(Boolean).join(",");
  return `
    ${popupTitle("#dc2626", `Traversée taguée footway=${escapeHTML(val)}`)}
    <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
    <div class="popup-row"><span class="label">Problème</span><span class="value">Le way qui traverse la route au nœud crossing porte footway=${escapeHTML(val)} au lieu de footway=crossing</span></div>
    ${nid > 0 ? `<div class="popup-row"><span class="label">Nœud</span><span class="value">
      <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
    </span></div>` : ""}
    ${wid > 0 ? `<div class="popup-row"><span class="label">Way</span><span class="value">
      <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
      · <a href="https://www.openstreetmap.org/edit?way=${wid}" target="_blank" rel="noopener">iD</a>
    </span></div>` : ""}
    ${objs ? `<div class="popup-row"><span class="label">Éditer</span><span class="value">
      <a href="http://127.0.0.1:8111/load_object?objects=${objs}" target="_blank" rel="noopener">JOSM</a>
    </span></div>` : ""}
  `;
}

const CLICK_LAYERS = [
  {
    ids: ["missing-crossings"],
    format: p => {
      if (p.type === "wrong_tag") return formatWrongTagCrossing(p);
      const isMissingWay = p.type === "missing_way";
      const nearM = (typeof p.nearest_tag_m === "number" && p.nearest_tag_m >= 0)
        ? p.nearest_tag_m : null;
      const radius = p.detect_radius || 20;
      const nid = parseInt(p.osm_id, 10) || 0;
      return `
        ${isMissingWay ? popupTitle("#f97316", "Traversée non mappée") : popupTitle("#eab308", "Tag footway=crossing absent")}
        <div class="popup-row"><span class="label">Rue</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
        <div class="popup-row"><span class="label">Problème</span><span class="value">${isMissingWay
          ? "Aucune footway connectée au nœud"
          : "Footway connectée mais sans tag footway=crossing"
        }</span></div>
        ${nearM !== null && !isMissingWay ? `<div class="popup-row"><span class="label">footway=crossing le plus proche</span><span class="value">${nearM} m <span class="popup-note">(rayon ${radius} m)</span></span></div>` : ""}
        ${nid > 0 ? `<div class="popup-row"><span class="label">Nœud</span><span class="value">
          <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=n${nid}" target="_blank" rel="noopener">JOSM</a>
          · <a href="https://www.openstreetmap.org/edit?node=${nid}" target="_blank" rel="noopener">iD</a>
        </span></div>` : ""}
      `;
    }
  },
  {
    ids: ["footway-crossing-candidates"],
    format: p => {
      const wid = parseInt(p.osm_id, 10) || 0;
      return `
        ${popupTitle("#7f1d1d", "Traversée sans footway=crossing ?")}
        <div class="popup-row"><span class="label">Rue traversée</span><span class="value">${escapeHTML(p.name || "—")}</span></div>
        <div class="popup-row"><span class="label">Longueur</span><span class="value">${escapeHTML(p.length_m)} m</span></div>
        <div class="popup-row"><span class="label">Problème</span><span class="value">Relie un trottoir de chaque côté d'une route mais n'a pas le tag footway=crossing</span></div>
        ${wid > 0 ? `<div class="popup-row"><span class="label">Way</span><span class="value">
          <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}" target="_blank" rel="noopener">JOSM</a>
          · <a href="https://www.openstreetmap.org/edit?way=${wid}" target="_blank" rel="noopener">iD</a>
        </span></div>` : ""}
      `;
    }
  },
  {
    ids: ["tactile-paving-issues"],
    format: p => {
      const nid = parseInt(p.osm_id, 10) || 0;
      const wid = parseInt(p.way_osm_id, 10) || 0;
      const pwid = parseInt(p.partner_way_osm_id, 10) || 0;
      const sidesChecked = parseInt(p.sides_checked, 10) || 2;
      const reasonLabels = {
        value_mismatch:       "tactile_paving du kerb différent de celui du crossing",
        incorrect_not_mixed:  "incorrect attendu : un kerb yes + un kerb no",
      };
      return `
        ${popupTitle("#a855f7", "Bande podotactile incohérente")}
        <div class="popup-row"><span class="label">Crossing</span><span class="value">tactile_paving=${escapeHTML(p.crossing_tp || "?")}</span></div>
        <div class="popup-row"><span class="label">Kerb côté 1</span><span class="value">${escapeHTML(p.kerb1_tp) || "absent"}</span></div>
        ${sidesChecked === 2
          ? `<div class="popup-row"><span class="label">Kerb côté 2</span><span class="value">${escapeHTML(p.kerb2_tp) || "absent"}</span></div>`
          : `<div class="popup-row"><span class="label">Kerb côté 2</span><span class="value popup-note">non vérifié : la way s'arrête au nœud crossing</span></div>`
        }
        <div class="popup-row"><span class="label">Problème</span><span class="value">${escapeHTML(reasonLabels[p.reason] || p.reason || "?")}</span></div>
        ${nid > 0 ? `<div class="popup-row"><span class="label">Nœud crossing</span><span class="value">
          <a href="https://www.openstreetmap.org/node/${nid}" target="_blank" rel="noopener">n${nid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=n${nid}" target="_blank" rel="noopener">JOSM</a>
          · <a href="https://www.openstreetmap.org/edit?node=${nid}" target="_blank" rel="noopener">iD</a>
        </span></div>` : ""}
        ${wid > 0 ? `<div class="popup-row"><span class="label">Way crossing</span><span class="value">
          <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}${pwid > 0 ? `,w${pwid}` : ""}" target="_blank" rel="noopener">JOSM</a>
        </span></div>` : ""}
        ${pwid > 0 ? `<div class="popup-row"><span class="label">Way contiguë</span><span class="value">
          <a href="https://www.openstreetmap.org/way/${pwid}" target="_blank" rel="noopener">w${pwid}</a>
          <span class="popup-note">(même traversée que la précédente)</span>
        </span></div>` : ""}
      `;
    }
  },
  {
    ids: ["graph-islands"],
    format: p => {
      const isUnjoined = p.type === "unjoined";
      const isLevel = p.type === "level";
      const nodeId = parseInt(p.node_id, 10) || 0;
      const ways = String(p.way_ids || "").split(",").map(w => parseInt(w, 10)).filter(w => w > 0);
      const gap = (typeof p.gap_m === "number" && p.gap_m >= 0) ? p.gap_m : null;
      const pad = 0.0005;
      const w = Number(p.bbox_w) - pad, s = Number(p.bbox_s) - pad;
      const e = Number(p.bbox_e) + pad, n = Number(p.bbox_n) + pad;
      const hasBbox = [w, s, e, n].every(Number.isFinite);
      const selIds = ways.map(id => "w" + id).concat(nodeId > 0 ? ["n" + nodeId] : []);
      const select = selIds.length ? `&select=${selIds.join(",")}` : "";
      const josm = hasBbox
        ? `http://127.0.0.1:8111/load_and_zoom?left=${w.toFixed(6)}&right=${e.toFixed(6)}&top=${n.toFixed(6)}&bottom=${s.toFixed(6)}${select}`
        : null;
      const idLink = ways.length
        ? `https://www.openstreetmap.org/edit?way=${ways[0]}`
        : (hasBbox ? `https://www.openstreetmap.org/edit#map=19/${((s + n) / 2).toFixed(6)}/${((w + e) / 2).toFixed(6)}` : null);
      return `
        ${isLevel ? popupTitle("#ea580c", "Discontinuité de niveau") : isUnjoined ? popupTitle("#db2777", "Jonction manquante") : popupTitle("#0d9488", "Îlot isolé du réseau")}
        <div class="popup-row"><span class="label">Problème</span><span class="value">${isLevel
          ? "Escalier (steps) dont le level=* ne recouvre pas celui d'un chemin directement raccordé : liaison théoriquement non praticable"
          : isUnjoined
            ? "Touche presque le réseau principal mais ne partage aucun nœud avec lui"
            : "Groupe de chemins sans aucune liaison avec le réseau principal"
        }</span></div>
        ${isLevel
          ? `<div class="popup-row"><span class="label">Niveaux</span><span class="value">${escapeHTML(p.levels || "—")}</span></div>
        ${nodeId > 0 ? `<div class="popup-row"><span class="label">Nœud</span><span class="value"><a href="https://www.openstreetmap.org/node/${nodeId}" target="_blank" rel="noopener">n${nodeId}</a></span></div>` : ""}`
          : `<div class="popup-row"><span class="label">Écart au réseau</span><span class="value">${gap !== null ? gap + " m" : "—"}</span></div>`
        }
        <div class="popup-row"><span class="label">Longueur</span><span class="value">${Math.round(Number(p.length_m) || 0)} m</span></div>
        <div class="popup-row"><span class="label">Types</span><span class="value">${escapeHTML(p.highways || "—")}</span></div>
        <div class="popup-row"><span class="label">Ways</span><span class="value">${ways.length
          ? ways.slice(0, 5).map(id => `<a href="https://www.openstreetmap.org/way/${id}" target="_blank" rel="noopener">w${id}</a>`).join(" ") + (ways.length > 5 ? ` +${ways.length - 5}` : "")
          : "—"
        }</span></div>
        ${josm || idLink ? `<div class="popup-row"><span class="label">Éditer</span><span class="value">
          ${josm ? `<a href="${josm}" target="_blank" rel="noopener">JOSM</a>` : ""}
          ${josm && idLink ? " · " : ""}
          ${idLink ? `<a href="${idLink}" target="_blank" rel="noopener">iD</a>` : ""}
        </span></div>` : ""}
      `;
    }
  },
  {
    ids: ["kerb-issues"],
    format: p => {
      const isMissing = p.type === "kerb_missing";
      const cid = parseInt(p.crossing_osm_id, 10) || 0;
      const wid = parseInt(p.way_osm_id, 10) || 0;
      const kid = parseInt(p.kerb_osm_id, 10) || 0;
      const pwid = parseInt(p.partner_way_osm_id, 10) || 0;
      return `
        ${isMissing ? popupTitle("#1e3a8a", "Kerb absent") : popupTitle("#7c2d12", "Kerb sans tactile_paving")}
        <div class="popup-row"><span class="label">Problème</span><span class="value">${isMissing
          ? "Aucun nœud barrier=kerb trouvé à cette extrémité"
          : "Kerb présent mais sans tag tactile_paving"
        }</span></div>
        ${cid > 0 ? `<div class="popup-row"><span class="label">Crossing</span><span class="value">
          <a href="https://www.openstreetmap.org/node/${cid}" target="_blank" rel="noopener">n${cid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=n${cid}" target="_blank" rel="noopener">JOSM</a>
          · <a href="https://www.openstreetmap.org/edit?node=${cid}" target="_blank" rel="noopener">iD</a>
        </span></div>` : ""}
        ${!isMissing && kid > 0 ? `<div class="popup-row"><span class="label">Kerb</span><span class="value">
          <a href="https://www.openstreetmap.org/node/${kid}" target="_blank" rel="noopener">n${kid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=n${kid}" target="_blank" rel="noopener">JOSM</a>
          · <a href="https://www.openstreetmap.org/edit?node=${kid}" target="_blank" rel="noopener">iD</a>
        </span></div>` : ""}
        ${wid > 0 ? `<div class="popup-row"><span class="label">Way crossing</span><span class="value">
          <a href="https://www.openstreetmap.org/way/${wid}" target="_blank" rel="noopener">w${wid}</a>
          · <a href="http://127.0.0.1:8111/load_object?objects=w${wid}${pwid > 0 ? `,w${pwid}` : ""}" target="_blank" rel="noopener">JOSM</a>
        </span></div>` : ""}
        ${pwid > 0 ? `<div class="popup-row"><span class="label">Way contiguë</span><span class="value">
          <a href="https://www.openstreetmap.org/way/${pwid}" target="_blank" rel="noopener">w${pwid}</a>
          <span class="popup-note">(même traversée que la précédente)</span>
        </span></div>` : ""}
      `;
    }
  },
];

const LIBERTY_URL = "https://tiles.openfreemap.org/styles/liberty";
const ZINNEKE_BASE = "https://pasloin.github.io/ZinnekeTiles/";
const ZINNEKE_ATTRIBUTION = '<a href="https://github.com/PasLoin/ZinnekeTiles" target="_blank" rel="noopener">ZinnekeTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
const ZINNEKE_SOURCE_PREFIX = "zt-";
const LIBERTY_THUMB = "data:image/svg+xml," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">' +
  '<rect width="80" height="80" fill="#f2efe9"/>' +
  '<path d="M48 0h32v30c-12 4-22 0-32-8z" fill="#d7ebc9"/>' +
  '<path d="M0 58c14-6 26 2 30 22H0z" fill="#d7ebc9"/>' +
  '<g fill="#e3ddd4"><rect x="6" y="6" width="16" height="10"/><rect x="28" y="8" width="12" height="14"/><rect x="8" y="26" width="14" height="16"/><rect x="40" y="38" width="16" height="12"/><rect x="60" y="40" width="14" height="18"/><rect x="40" y="60" width="18" height="14"/></g>' +
  '<g fill="none" stroke="#aaaaaa" stroke-width="5"><path d="M0 22h80M25 0v80M0 52h80M58 0l-6 80"/></g>' +
  '<g fill="none" stroke="#d5d5d5" stroke-width="3"><path d="M0 22h80M25 0v80M0 52h80M58 0l-6 80"/></g>' +
  '<path d="M0 34 80 30" stroke="#a0c8f0" stroke-width="4"/>' +
  '</svg>'
);

const BASEMAPS = [
  { id: "liberty", label: "Liberty", title: "OpenFreeMap Liberty", thumb: LIBERTY_THUMB },
  {
    id: "zinneke", label: "Zinneke", title: "ZinnekeTiles",
    thumb: ZINNEKE_BASE + "assets/img/basemap-zinneke.png",
    url: ZINNEKE_BASE + "style.json",
    hideSources: ["public_transport", "poi"],
    hideLayers: ["railway-tram*", "railway-subway*", "railway-tunnel-tram", "railway-tunnel-subway"]
  },
  {
    id: "nb", label: "Zinneke N&B", title: "ZinnekeTiles noir et blanc",
    thumb: ZINNEKE_BASE + "assets/img/basemap-nb.png",
    url: ZINNEKE_BASE + "style.nb.json"
  }
];

const OVERLAY_SOURCES = ["pedestrian", "nav-route"];
const BASEMAP_STORAGE_KEY = "bpn-basemap";
const basemapStyleCache = {};
let currentBasemap = "liberty";
let basemapRequest = 0;

async function loadLibertyStyle() {
  let libertyStyle;
  try {
    const res = await fetch(LIBERTY_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    libertyStyle = await res.json();
  } catch (err) {
    console.warn("Style Liberty indisponible, chargement direct :", err);
    return LIBERTY_URL;
  }
  let localPaintById = new Map();
  try {
    const localStyle = await (await fetch("./style.json")).json();
    const allowedIds = new Set(Object.keys(BASE_STYLE_OVERRIDES));
    localPaintById = new Map(
      (localStyle.layers || []).filter(l => allowedIds.has(l.id)).map(l => [l.id, l.paint || {}])
    );
  } catch (err) {
    console.warn("style.json local indisponible :", err);
  }
  libertyStyle.layers = (libertyStyle.layers || []).map(layer => {
    const localPaint = localPaintById.get(layer.id) || {};
    const overrides  = BASE_STYLE_OVERRIDES[layer.id] || {};
    return { ...layer, paint: { ...(layer.paint || {}), ...localPaint, ...overrides } };
  });
  return libertyStyle;
}

async function loadZinnekeStyle(bm) {
  const res = await fetch(bm.url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const style = await res.json();
  const hideSources = new Set(bm.hideSources || []);
  const hideLayers = bm.hideLayers || [];
  const isHidden = layer => hideSources.has(layer.source) || hideLayers.some(pattern =>
    pattern.endsWith("*") ? layer.id.startsWith(pattern.slice(0, -1)) : layer.id === pattern);
  const layers = (style.layers || []).filter(layer => !isHidden(layer));
  const usedSources = new Set(layers.map(layer => layer.source).filter(Boolean));
  const sources = {};
  for (const [id, src] of Object.entries(style.sources || {})) {
    if (!usedSources.has(id)) continue;
    const copy = { ...src, attribution: ZINNEKE_ATTRIBUTION };
    if (copy.url && /\.pmtiles$/.test(copy.url)) copy.url = "pmtiles://" + new URL(copy.url, bm.url).href;
    sources[ZINNEKE_SOURCE_PREFIX + id] = copy;
  }
  style.sources = sources;
  style.layers = layers.map(layer => {
    const out = { ...layer };
    if (out.source) out.source = ZINNEKE_SOURCE_PREFIX + out.source;
    if (out.layout && out.layout["icon-image"]) {
      out.layout = { ...out.layout, visibility: "none" };
      delete out.layout["icon-image"];
    }
    return out;
  });
  return style;
}

async function loadBasemapStyle(bm) {
  if (basemapStyleCache[bm.id]) return basemapStyleCache[bm.id];
  const style = bm.url ? await loadZinnekeStyle(bm) : await loadLibertyStyle();
  basemapStyleCache[bm.id] = style;
  return style;
}

async function rasterizeSvg(svgText, size, pixelRatio) {
  const blobUrl = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image();
    await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = blobUrl; });
    const px = Math.round(size * pixelRatio);
    const canvas = document.createElement("canvas");
    canvas.width = px; canvas.height = px;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, px, px);
    return ctx.getImageData(0, 0, px, px);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

async function loadBasemapPatterns(map, style, baseUrl) {
  if (!style || typeof style !== "object") return;
  const patterns = (style.metadata || {})["brussels:patterns"] || {};
  await Promise.all(Object.entries(patterns).map(async ([name, cfg]) => {
    if (!cfg || !cfg.file || map.hasImage(name)) return;
    try {
      const res = await fetch(new URL(cfg.file, baseUrl).href);
      if (!res.ok) return;
      let svg = await res.text();
      for (const [from, to] of Object.entries(cfg.replace || {})) svg = svg.split(from).join(to);
      const data = await rasterizeSvg(svg, cfg.size || 32, 2);
      if (!map.hasImage(name)) map.addImage(name, data, { pixelRatio: 2 });
    } catch (err) {
      console.warn(`Motif ${name} indisponible :`, err);
    }
  }));
  map.triggerRepaint();
}

function keepOverlays(prev, next) {
  const sources = { ...next.sources };
  for (const id of OVERLAY_SOURCES) {
    if (prev && prev.sources && prev.sources[id]) sources[id] = prev.sources[id];
  }
  const overlayLayers = ((prev && prev.layers) || []).filter(l => OVERLAY_SOURCES.includes(l.source));
  return { ...next, sources, layers: [...next.layers, ...overlayLayers] };
}

function renderBasemapMenu() {
  const menu = document.getElementById("basemap-menu");
  menu.replaceChildren(...BASEMAPS.map(bm => {
    const active = bm.id === currentBasemap;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "basemap-option" + (active ? " active" : "");
    btn.dataset.id = bm.id;
    btn.title = bm.title;
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", active ? "true" : "false");
    const img = document.createElement("img");
    img.src = bm.thumb;
    img.alt = "";
    img.loading = "lazy";
    const span = document.createElement("span");
    span.textContent = bm.label;
    btn.append(img, span);
    btn.addEventListener("click", () => setBasemap(bm.id));
    return btn;
  }));
}

async function setBasemap(id) {
  const bm = BASEMAPS.find(b => b.id === id);
  if (!bm || id === currentBasemap || !mapRef || !mapRef.getSource("pedestrian")) return;
  const request = ++basemapRequest;
  const btn = document.querySelector(`.basemap-option[data-id="${id}"]`);
  if (btn) btn.classList.add("loading");
  try {
    const style = await loadBasemapStyle(bm);
    if (request !== basemapRequest) return;
    currentBasemap = id;
    if (bm.url) mapRef.once("style.load", () => loadBasemapPatterns(mapRef, style, bm.url));
    mapRef.setStyle(style, { diff: false, transformStyle: keepOverlays });
    try { localStorage.setItem(BASEMAP_STORAGE_KEY, id); } catch (e) {}
    renderBasemapMenu();
  } catch (err) {
    console.error("Fond de carte indisponible :", err);
    if (btn) btn.classList.remove("loading");
  }
}

function setupBasemapControl() {
  const control = document.getElementById("basemap-control");
  const toggle = document.getElementById("basemap-toggle");
  const setOpen = open => {
    control.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };
  toggle.addEventListener("click", e => {
    e.stopPropagation();
    setOpen(!control.classList.contains("open"));
  });
  document.addEventListener("click", e => {
    if (!control.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && control.classList.contains("open")) {
      setOpen(false);
      toggle.focus();
    }
  });
  renderBasemapMenu();
}

(async () => {
  let saved = null;
  try { saved = localStorage.getItem(BASEMAP_STORAGE_KEY); } catch (e) {}
  let bm = BASEMAPS.find(b => b.id === saved) || BASEMAPS[0];
  let style;
  try {
    style = await loadBasemapStyle(bm);
  } catch (err) {
    console.warn("Fond de carte enregistré indisponible :", err);
    bm = BASEMAPS[0];
    style = await loadBasemapStyle(bm);
  }
  currentBasemap = bm.id;
  setupBasemapControl();
  initMap(style);
  if (bm.url) mapRef.once("style.load", () => loadBasemapPatterns(mapRef, style, bm.url));
})();

function initMap(style) {
  const map = new maplibregl.Map({
    container: "map", style,
    center: [4.3517, 50.8503], zoom: 12,
    attributionControl: false,
    hash: true
  });
  mapRef = map;

  map.addControl(
    new maplibregl.AttributionControl({
      compact: false,
      customAttribution: ['<a href="https://github.com/PasLoin/Brussels-Pedestrian-Network" target="_blank" rel="noopener">PasLoin</a> · <a href="./stats.html">Stats</a>']
    }),
    "bottom-right"
  );

  const updateLegendClearance = () => {
    const attrEl = document.querySelector(".maplibregl-ctrl-bottom-right");
    if (!attrEl) return;
    const rect = attrEl.getBoundingClientRect();
    const clearance = Math.max(40, window.innerHeight - rect.top + 8);
    document.documentElement.style.setProperty("--attribution-clearance", `${clearance}px`);
  };
  updateLegendClearance();
  window.addEventListener("resize", updateLegendClearance);

  map.on("load", () => {
    map.addSource("pedestrian", { type: "vector", url: `pmtiles://${PMTILES_URL}` });
    PEDESTRIAN_LAYERS.forEach(layer => map.addLayer(layer));

    map.addSource("nav-route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "nav-route-casing", type: "line", source: "nav-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#000", "line-width": ["interpolate", ["linear"], ["zoom"], 10, 6, 16, 14], "line-opacity": 0.4 }
    });
    map.addLayer({
      id: "nav-route-line", type: "line", source: "nav-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 10], "line-opacity": 0.92 }
    });
    map.on("click", handleNavClick);

    const legendEl = document.getElementById("legend-content");
    const addSection = (txt) => {
      const s = document.createElement("div");
      s.className = "legend-section";
      s.textContent = txt;
      legendEl.appendChild(s);
    };

    const makeItem = ({ layerId, label, color, color2, swatchType = "line", dashed = false, onToggle = null, linkedLayerIds = [] }) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      const swatch = document.createElement("div");
      swatch.className = `legend-${swatchType}`;
      if (color2) {
        swatch.classList.add(swatchType === "dot" ? "gradient-dot" : "gradient");
        swatch.style.setProperty("--c1", color);
        swatch.style.setProperty("--c2", color2);
      } else if (dashed) {
        swatch.classList.add("dashed");
        swatch.style.setProperty("--c", color);
      } else {
        swatch.style.background = color;
      }
      const lbl = document.createElement("span");
      lbl.className = "legend-label";
      lbl.textContent = label;
      item.append(swatch, lbl);

      const updateState = (byUser = false, notify = true) => {
        const isHidden = map.getLayoutProperty(layerId, "visibility") === "none";
        item.classList.toggle("hidden", isHidden);
        item.setAttribute("aria-pressed", !isHidden);
        if (onToggle && notify) onToggle(!isHidden, byUser);
      };
      updateState();

      const toggle = () => {
        const v = map.getLayoutProperty(layerId, "visibility") === "none" ? "visible" : "none";
        map.setLayoutProperty(layerId, "visibility", v);
        linkedLayerIds.forEach(id => map.setLayoutProperty(id, "visibility", v));
        updateState(true);
      };
      item.onclick = toggle;
      item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
      item.sync = () => updateState(false, false);
      return item;
    };

    const makeKerbTypeItem = ({ type, label, color }) => {
      const item = document.createElement("div");
      item.className = "legend-item";
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      const swatch = document.createElement("div");
      swatch.className = "legend-dot";
      swatch.style.background = color;

      const lbl = document.createElement("span");
      lbl.className = "legend-label";
      lbl.textContent = label;
      item.append(swatch, lbl);

      const updateState = () => {
        const isActive = activeKerbIssueTypes.has(type);
        item.classList.toggle("hidden", !isActive);
        item.setAttribute("aria-pressed", isActive);
      };
      updateState();

      const toggle = () => {
        if (activeKerbIssueTypes.has(type)) activeKerbIssueTypes.delete(type);
        else activeKerbIssueTypes.add(type);
        updateState();
        setVisibilityIfLayer(map, "kerb-issues", activeKerbIssueTypes.size > 0);
        updateKerbIssuesFilter();
      };
      item.onclick = toggle;
      item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
      return item;
    };

    const makeSubFilter = ({ items, activeSet, dataKey, updateFn, parentSub, layerId, parentItem }) => {
      const header = document.createElement("div");
      header.className = "legend-sub-header";
      header.innerHTML = `<span>Filtrer par type</span>`;

      const resetBtn = document.createElement("button");
      resetBtn.className = "legend-sub-reset";
      resetBtn.type = "button";

      const isLayerVisible = () => map.getLayoutProperty(layerId, "visibility") !== "none";

      const refresh = () => {
        const shown = isLayerVisible();
        parentSub.querySelectorAll(".legend-sub-item").forEach(el => {
          const on = shown && activeSet.has(el.dataset[dataKey]);
          el.classList.toggle("hidden", !on);
          el.setAttribute("aria-pressed", on);
        });
        resetBtn.textContent = shown && activeSet.size === items.length
          ? "Tout désélectionner" : "Tout sélectionner";
      };

      const apply = () => {
        const visible = activeSet.size > 0;
        if (visible !== isLayerVisible()) {
          map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
          parentItem.sync();
        }
        updateFn();
        refresh();
      };

      resetBtn.onclick = (e) => {
        e.stopPropagation();
        const allOn = isLayerVisible() && activeSet.size === items.length;
        activeSet.clear();
        if (!allOn) items.forEach(it => activeSet.add(it.value));
        apply();
      };
      header.appendChild(resetBtn);
      parentSub.appendChild(header);

      items.forEach(it => {
        const item = document.createElement("div");
        item.className = "legend-sub-item";
        item.dataset[dataKey] = it.value;
        item.setAttribute("role", "button");
        item.setAttribute("tabindex", "0");

        const dot = document.createElement("div");
        dot.className = "legend-sub-dot";
        dot.style.background = it.color;

        const lbl = document.createElement("span");
        lbl.className = "legend-sub-label";
        lbl.textContent = it.label;

        item.append(dot, lbl);

        const toggle = (e) => {
          e.stopPropagation();
          if (!isLayerVisible()) activeSet.clear();
          if (activeSet.has(it.value)) activeSet.delete(it.value);
          else activeSet.add(it.value);
          apply();
        };
        item.onclick = toggle;
        item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } };
        parentSub.appendChild(item);
      });

      refresh();
      return { refresh };
    };

    const addFilteredLayer = ({ layerId, label, color, color2, swatchType, items, activeSet, dataKey, updateFn }) => {
      const sub = document.createElement("div");
      sub.className = "legend-sub";
      let filter = null;
      const parentItem = makeItem({
        layerId, label, color, color2, swatchType,
        onToggle: (isVisible, byUser) => {
          if (isVisible && byUser) {
            items.forEach(it => activeSet.add(it.value));
            updateFn();
          }
          if (filter) filter.refresh();
        }
      });
      legendEl.appendChild(parentItem);
      filter = makeSubFilter({ items, activeSet, dataKey, updateFn, parentSub: sub, layerId, parentItem });
      legendEl.appendChild(sub);
    };

    addSection("Routage simulé");
    legendEl.appendChild(makeItem({ layerId: "flow-ped",      label: "Flux piéton",        color: "#bbf7d0", color2: "#14532d" }));
    legendEl.appendChild(makeItem({ layerId: "flow-cycleway",  label: "Flux sur piste cyclable",     color: "#bfdbfe", color2: "#3b0764" }));
    legendEl.appendChild(makeItem({ layerId: "flow-road",      label: "Flux sur route",      color: "#fdba74", color2: "#450a0a" }));

    addSection("Analyse spatiale et qualité");
    legendEl.appendChild(makeItem({ layerId: "sidewalk-gaps", label: "Trottoir d'un seul côté", color: "#f59e0b", dashed: true }));
    legendEl.appendChild(makeItem({ layerId: "footway-crossing-candidates", label: "Traversée sans footway=crossing ?", color: "#7f1d1d", dashed: true }));
    legendEl.appendChild(makeItem({ layerId: "tactile-paving-issues", label: "Bande podotactile incohérente", color: "#a855f7", swatchType: "dot" }));

    KERB_ISSUE_TYPES.forEach(t => {
      legendEl.appendChild(makeKerbTypeItem({ type: t.value, label: t.label, color: t.color }));
    });

    addFilteredLayer({
      layerId:   "missing-crossings",
      label:     "Traversée manquante",
      color:     "#f97316",
      swatchType: "dot",
      items:     MISSING_CROSSING_TYPES,
      activeSet: activeMissingTypes,
      dataKey:   "type",
      updateFn:  updateMissingCrossingsFilter,
    });

    addFilteredLayer({
      layerId:   "graph-islands",
      label:     "Îlot déconnecté du réseau",
      color:     "#db2777",
      color2:    "#0d9488",
      items:     ISLAND_TYPES,
      activeSet: activeIslandTypes,
      dataKey:   "islandType",
      updateFn:  updateIslandsFilter,
    });

    addFilteredLayer({
      layerId:   "sidewalk-roads",
      label:     "Tags sidewalk",
      color:     "#9ca3af",
      color2:    "#15803d",
      items:     SIDEWALK_STATUSES,
      activeSet: activeSidewalkStatuses,
      dataKey:   "status",
      updateFn:  updateSidewalkFilter,
    });

    addSection("Réseau de base");
    HIGHWAY_LAYERS.forEach(l => legendEl.appendChild(makeItem({ layerId: `highway-${l.id}`, label: l.label, color: l.color, dashed: l.dash })));
    legendEl.appendChild(makeItem({
      layerId: ELEVATOR_LAYER_IDS[0], linkedLayerIds: ELEVATOR_LAYER_IDS.slice(1),
      label: "Ascenseur", color: ELEVATOR_COLOR, swatchType: "dot",
    }));

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: "280px" });
    const allHoverIds = HOVER_LAYERS.flatMap(h => h.ids);

    map.on("mousemove", (e) => {
      if (navMode && navStep < 2) { popup.remove(); return; }
      const visibleIds = allHoverIds.filter(id => {
        try { return map.getLayoutProperty(id, "visibility") !== "none"; }
        catch { return false; }
      });
      if (!visibleIds.length) { popup.remove(); return; }
      const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
      if (!features.length) { popup.remove(); if (!navMode) map.getCanvas().style.cursor = ""; return; }
      if (!navMode) map.getCanvas().style.cursor = "pointer";
      const f = features[0];
      const hoverConf = HOVER_LAYERS.find(h => h.ids.includes(f.layer.id));
      if (!hoverConf) return;
      popup.setLngLat(e.lngLat).setHTML(hoverConf.format(f.properties)).addTo(map);
    });

    map.on("mouseleave", allHoverIds, () => { popup.remove(); if (!navMode) map.getCanvas().style.cursor = ""; });

    const clickPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: "300px" });
    const allClickIds = CLICK_LAYERS.flatMap(c => c.ids);

    map.on("click", (e) => {
      if (navMode) return;
      const visibleIds = allClickIds.filter(id => {
        try { return map.getLayoutProperty(id, "visibility") !== "none"; }
        catch { return false; }
      });
      if (!visibleIds.length) return;
      const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
      if (!features.length) return;
      e.preventDefault && e.preventDefault();
      const f = features[0];
      const conf = CLICK_LAYERS.find(c => c.ids.includes(f.layer.id));
      if (!conf) return;
      map.getCanvas().style.cursor = "pointer";
      clickPopup.setLngLat(e.lngLat).setHTML(conf.format(f.properties)).addTo(map);
    });

    map.on("mousemove", (e) => {
      if (navMode) return;
      const visibleIds = allClickIds.filter(id => {
        try { return map.getLayoutProperty(id, "visibility") !== "none"; }
        catch { return false; }
      });
      if (!visibleIds.length) return;
      const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
      map.getCanvas().style.cursor = features.length ? "pointer" : "";
    });
  });

  const syncZoomUi = () => {
    const z = map.getZoom();
    const c = map.getCenter();
    document.getElementById("zoom-val").textContent = z.toFixed(1);
    const btn = document.getElementById("edit-btn");
    if (z >= EDIT_MIN_ZOOM) {
      btn.href = `https://www.openstreetmap.org/edit#map=${Math.round(z)}/${c.lat.toFixed(5)}/${c.lng.toFixed(5)}`;
      btn.classList.remove("disabled");
      btn.setAttribute("aria-disabled", "false");
      btn.setAttribute("tabindex", "0");
    } else {
      btn.classList.add("disabled");
      btn.setAttribute("aria-disabled", "true");
      btn.setAttribute("tabindex", "-1");
    }
  };
  map.on("load", syncZoomUi);
  map.on("moveend", syncZoomUi);
}
