import { i18n } from "./i18n.js";
import { store } from "./store.js";
import { hideRoutePanel, showRoutePanel } from "./panels.js";

let graphData = null;
let adjList   = null;
let mainComponent = null;
let groundEdges = null;
let graphReady = false;
let navMode = false, navStep = 0;
let startMarker = null, endMarker = null;
let startSnap = null, endSnap = null;

export function isNavigating() {
  return navMode;
}

export function isPickingRoute() {
  return navMode && navStep < 2;
}

export function loadGraph() {
  return fetch(i18n.dataUrl("graph.json"))
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
      document.getElementById("nav-btn-label").textContent = i18n.t("nav.start");
      console.log(`Graph loaded: ${data.n.length} nodes, ${data.e.length} edges`);
    })
    .catch(err => {
      console.warn("graph.json not available:", err);
      document.getElementById("nav-btn-label").textContent = i18n.t("nav.unavailable");
      document.getElementById("nav-btn").classList.add("disabled");
      document.getElementById("nav-btn").setAttribute("aria-busy", "false");
    });
}

export function toggleNavMode() {
  if (!graphReady) return;
  navMode = !navMode;
  const btn  = document.getElementById("nav-btn");
  const hint = document.getElementById("nav-hint");
  btn.setAttribute("aria-pressed", navMode);
  if (navMode) {
    btn.classList.add("active");
    document.getElementById("nav-btn-label").textContent = i18n.t("nav.exit");
    hint.textContent = i18n.t("nav.placeStart");
    navStep = 0;
    document.getElementById("map").classList.add("nav-mode-cursor");
  } else {
    btn.classList.remove("active");
    document.getElementById("nav-btn-label").textContent = i18n.t("nav.start");
    hint.textContent = "";
    clearRoute();
    document.getElementById("map").classList.remove("nav-mode-cursor");
  }
}

export function clearRoute() {
  navStep = 0;
  if (startMarker) { startMarker.remove(); startMarker = null; }
  if (endMarker)   { endMarker.remove();   endMarker   = null; }
  hideRoutePanel();
  if (store.map) {
    const src = store.map.getSource("nav-route");
    if (src) src.setData({ type: "FeatureCollection", features: [] });
  }
  if (navMode) document.getElementById("nav-hint").textContent = i18n.t("nav.placeStart");
}

export function handleNavClick(e) {
  if (!navMode || !graphReady) return;
  const { lat, lng } = e.lngLat;
  if (navStep === 0) {
    startSnap = snapToNetwork(graphData, lat, lng, mainComponent, groundEdges);
    if (startMarker) startMarker.remove();
    startMarker = new maplibregl.Marker({ color: "#22c55e" }).setLngLat([lng, lat]).addTo(store.map);
    navStep = 1;
    document.getElementById("nav-hint").textContent = i18n.t("nav.placeEnd");
  } else if (navStep === 1) {
    endSnap = snapToNetwork(graphData, lat, lng, mainComponent, groundEdges);
    if (endMarker) endMarker.remove();
    endMarker = new maplibregl.Marker({ color: "#ef4444" }).setLngLat([lng, lat]).addTo(store.map);
    document.getElementById("nav-hint").textContent = i18n.t("nav.computing");
    requestAnimationFrame(() => {
      const t0 = performance.now();
      const found = startSnap && endSnap ? routeBetween(graphData, adjList, startSnap, endSnap) : null;
      const dt = Math.round(performance.now() - t0);
      if (!found || found.legs.length === 0) {
        document.getElementById("nav-hint").textContent = i18n.t("nav.noRoute");
        navStep = 2; return;
      }
      const route = buildRoute(graphData, found.legs);
      const src = store.map.getSource("nav-route");
      if (src) src.setData(route.geojson);
      document.getElementById("route-dist").textContent = route.totalM >= 1000
        ? `${i18n.number(route.totalM / 1000, { maximumFractionDigits: 2 })} km` : `${i18n.number(route.totalM)} m`;
      document.getElementById("route-time").textContent = i18n.t("route.walkTime", { minutes: route.walkMin });
      document.getElementById("bar-ped").style.width  = route.pedPct  + "%";
      document.getElementById("bar-road").style.width = route.roadPct + "%";
      document.getElementById("bar-cyc").style.width  = route.cycPct  + "%";
      const wholePct = { maximumFractionDigits: 0 };
      document.getElementById("stat-ped-m").textContent   = `${i18n.number(route.pedM)} m`;
      document.getElementById("stat-road-m").textContent  = `${i18n.number(route.roadM)} m`;
      document.getElementById("stat-cyc-m").textContent   = `${i18n.number(route.cycM)} m`;
      document.getElementById("stat-ped-pct").textContent  = i18n.percent(route.pedPct, wholePct);
      document.getElementById("stat-road-pct").textContent = i18n.percent(route.roadPct, wholePct);
      document.getElementById("stat-cyc-pct").textContent  = i18n.percent(route.cycPct, wholePct);
      showRoutePanel();
      document.getElementById("nav-hint").textContent = i18n.t("nav.computedIn", { ms: dt });
      navStep = 2;
    });
  } else {
    clearRoute();
    handleNavClick(e);
  }
}
