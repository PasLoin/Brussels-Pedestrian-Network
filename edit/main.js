import { i18n } from "../map/i18n.js";
import { store } from "../map/store.js";
import { guardEnvironment, isLoggedIn, login, loginInProgress, logout, tabId } from "./auth.js";
import { EMPTY_COLLECTION, bboxString, candidatesFromMapData } from "./candidates.js";
import { envFromDocument } from "./env.js";
import { authView, detailView, statusView } from "./panel.js";
import { isEditableCandidate } from "./whitelist.js";

const SOURCE = "edit-candidates";
const LAYER = "edit-candidates";
const SELECTED = "edit-candidates-selected";
const NO_SELECTION = ["==", ["get", "osm_id"], -1];

const env = envFromDocument(document);
const osm = window.OSM;
const storage = window.localStorage;
const tab = tabId(window.sessionStorage);

guardEnvironment({ env: env.name, storage, osm });
osm.configure({ apiUrl: env.apiUrl });

const authEl = document.getElementById("edit-auth");
const statusEl = document.getElementById("edit-status");
const detailEl = document.getElementById("edit-detail");

function showAuth(state) {
  authEl.innerHTML = html`${authView(state, i18n)}`;
}

function showStatus(state) {
  statusEl.textContent = statusView(state, i18n);
}

function showDetail(state) {
  detailEl.innerHTML = html`${detailView(state, i18n, env.webUrl)}`;
}

async function refreshAuth(message) {
  if (!env.editEnabled) return showAuth({ kind: "disabled" });
  if (!env.clientId) return showAuth({ kind: "unconfigured" });
  if (!isLoggedIn({ osm, storage, env })) {
    const pending = loginInProgress({ storage, now: Date.now(), ttlMs: env.authPendingTtlMs, tab });
    return showAuth({ kind: pending ? "pending" : "anonymous", message });
  }
  try {
    const user = await osm.getUser("me");
    showAuth({ kind: "logged", name: user.display_name });
  } catch {
    logout({ osm, storage });
    showAuth({ kind: "anonymous", message: i18n.t("edit.auth.expired") });
  }
}

authEl.addEventListener("click", async (e) => {
  const action = e.target.closest("[data-edit-action]")?.dataset.editAction;
  if (action === "logout") {
    logout({ osm, storage });
    return refreshAuth();
  }
  if (action !== "login") return;
  showAuth({ kind: "waiting" });
  try {
    await login({ osm, storage, env, tab });
    await refreshAuth();
  } catch (err) {
    const message = err && err.message === "login-pending" ? i18n.t("edit.auth.pending") : i18n.t("edit.auth.failed");
    await refreshAuth(message);
  }
});

refreshAuth();

const map = store.mapReady
  ? store.map
  : await new Promise(resolve => window.addEventListener("bpn:map-ready", e => resolve(e.detail), { once: true }));

map.addSource(SOURCE, { type: "geojson", data: EMPTY_COLLECTION, promoteId: "osm_id" });
map.addLayer({
  id: LAYER, type: "line", source: SOURCE,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#c026d3", "line-width": ["interpolate", ["linear"], ["zoom"], 16, 4, 19, 9], "line-opacity": 0.85 },
});
map.addLayer({
  id: SELECTED, type: "line", source: SOURCE, filter: NO_SELECTION,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#111827", "line-width": ["interpolate", ["linear"], ["zoom"], 16, 7, 19, 13], "line-opacity": 0.6 },
});

let controller = null;
let timer = null;

async function loadCandidates() {
  if (controller) controller.abort();
  if (map.getZoom() < env.candidateMinZoom) {
    controller = null;
    map.getSource(SOURCE)?.setData(EMPTY_COLLECTION);
    return showStatus({ kind: "zoom", minZoom: env.candidateMinZoom });
  }
  const current = new AbortController();
  controller = current;
  showStatus({ kind: "loading" });
  try {
    const features = await osm.getMapData(bboxString(map.getBounds()), { signal: current.signal });
    if (current.signal.aborted) return;
    const collection = candidatesFromMapData(features);
    map.getSource(SOURCE)?.setData(collection);
    showStatus({ kind: "ready", count: collection.features.length });
  } catch (err) {
    if (current.signal.aborted) return;
    showStatus({ kind: "error", message: err && err.message });
  }
}

function scheduleCandidates() {
  clearTimeout(timer);
  timer = setTimeout(loadCandidates, 300);
}

async function selectWay(id) {
  map.setFilter(SELECTED, ["==", ["get", "osm_id"], id]);
  showDetail({ kind: "loading" });
  try {
    const [way] = await osm.getFeature("way", id);
    showDetail({ kind: "way", way, editable: isEditableCandidate(way.tags) });
  } catch (err) {
    showDetail({ kind: "error", message: err && err.message });
  }
}

map.on("click", LAYER, (e) => {
  const id = Number(e.features?.[0]?.properties?.osm_id);
  if (Number.isFinite(id) && id > 0) selectWay(id);
});
map.on("mouseenter", LAYER, () => { map.getCanvas().style.cursor = "pointer"; });
map.on("mouseleave", LAYER, () => { map.getCanvas().style.cursor = ""; });
map.on("moveend", scheduleCandidates);
loadCandidates();
