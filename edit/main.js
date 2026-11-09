import { i18n } from "../map/i18n.js";
import { store } from "../map/store.js";
import { guardEnvironment, isLoggedIn, login, loginInProgress, logout, tabId } from "./auth.js";
import { EMPTY_COLLECTION, bboxString, candidatesFromMapData } from "./candidates.js";
import { buildChangesetTags, splitList } from "./changeset.js";
import { APP_NAME, APP_VERSION, envFromDocument } from "./env.js";
import { bboxOf, lineLengthM } from "./geo.js";
import { chooseValue, choiceFromIntent, completeChoice, makeIntent, switchMode } from "./intent.js";
import { closeEmptyChangesets, planUpload, uploadGroups } from "./osm.js";
import { authView, detailView, queueView, statusView } from "./panel.js";
import { createQueue } from "./queue.js";
import { isEditableCandidate } from "./whitelist.js";

const SOURCE = "edit-candidates";
const LAYER = "edit-candidates";
const SELECTED = "edit-candidates-selected";
const SIDE_LEFT = "edit-candidates-left";
const SIDE_RIGHT = "edit-candidates-right";
const NO_SELECTION = ["==", ["get", "osm_id"], -1];

const env = envFromDocument(document);
const osm = window.OSM;
const storage = window.localStorage;
const tab = tabId(window.sessionStorage);

guardEnvironment({ env: env.name, storage, osm });
osm.configure({ apiUrl: env.apiUrl });

const queue = createQueue({ storage, env: env.name });
const authEl = document.getElementById("edit-auth");
const statusEl = document.getElementById("edit-status");
const detailEl = document.getElementById("edit-detail");
const queueEl = document.getElementById("edit-queue");

const state = {
  user: null,
  detail: { kind: "none" },
  plan: null,
  result: null,
  busy: false,
  form: {
    comment: "",
    commentTouched: false,
    sources: [],
    sourceOther: "",
    hashtags: env.defaultHashtags.join(" "),
    review: false,
  },
};
const liveFeatures = new Map();
let map = null;
let refreshSelected = null;

function defaultComment() {
  return i18n.t("edit.upload.defaultComment", { count: queue.size() });
}

function showAuth(view) {
  authEl.innerHTML = html`${authView(view, i18n)}`;
}

function showStatus(view) {
  statusEl.textContent = statusView(view, i18n);
}

function renderDetail() {
  detailEl.innerHTML = html`${detailView(state.detail, i18n, env.webUrl, env)}`;
  showSideLines();
}

function showSideLines() {
  if (!map || !map.getLayer(SIDE_LEFT)) return;
  const d = state.detail;
  const filter = d.kind === "way" && d.editable && d.choice && d.choice.mode === "sides"
    ? ["==", ["get", "osm_id"], d.way.id]
    : NO_SELECTION;
  map.setFilter(SIDE_LEFT, filter);
  map.setFilter(SIDE_RIGHT, filter);
}

function renderQueue() {
  if (!state.form.commentTouched) state.form.comment = defaultComment();
  queueEl.innerHTML = html`${queueView({
    items: queue.list(),
    form: state.form,
    plan: state.plan,
    result: state.result,
    busy: state.busy,
    loggedIn: Boolean(state.user),
  }, i18n, env.webUrl, env)}`;
}

function syncQueuedState() {
  if (!map || !map.getSource(SOURCE)) return;
  for (const id of liveFeatures.keys()) map.setFeatureState({ source: SOURCE, id }, { queued: queue.has(id) });
}

async function refreshAuth(message) {
  state.user = null;
  if (!env.editEnabled) showAuth({ kind: "disabled" });
  else if (!env.clientId) showAuth({ kind: "unconfigured" });
  else if (!isLoggedIn({ osm, storage, env })) {
    const pending = loginInProgress({ storage, now: Date.now(), ttlMs: env.authPendingTtlMs, tab });
    showAuth({ kind: pending ? "pending" : "anonymous", message });
  } else {
    try {
      const me = await osm.getUser("me");
      state.user = { uid: me.id, name: me.display_name, changesetsCount: me.changesets && me.changesets.count };
      showAuth({ kind: "logged", name: me.display_name });
    } catch {
      logout({ osm, storage });
      showAuth({ kind: "anonymous", message: i18n.t("edit.auth.expired") });
    }
  }
  renderQueue();
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

function queueChoice() {
  const d = state.detail;
  const sides = completeChoice(d.choice);
  if (!sides) return;
  const intent = makeIntent({ way: d.way, left: sides.left, right: sides.right, bbox: d.bbox, lengthM: d.lengthM });
  queue.put(intent);
  state.plan = null;
  state.result = null;
  state.detail = { ...d, queued: intent };
  renderQueue();
  syncQueuedState();
}

function unqueueSelected(choice) {
  const d = state.detail;
  queue.remove(d.way.id);
  state.plan = null;
  state.detail = { ...d, queued: null, choice };
  renderQueue();
  syncQueuedState();
}

detailEl.addEventListener("click", (e) => {
  const button = e.target.closest("[data-edit-action]");
  const d = state.detail;
  if (!button || d.kind !== "way" || !d.editable) return;
  const action = button.dataset.editAction;
  if (action === "choose") {
    state.detail = { ...d, choice: chooseValue(d.choice, button.dataset.side, button.dataset.value) };
    if (env.autoQueue && completeChoice(state.detail.choice)) queueChoice();
    else if (env.autoQueue && d.queued) unqueueSelected(state.detail.choice);
  } else if (action === "mode") {
    state.detail = { ...d, choice: switchMode(d.choice, button.dataset.mode) };
  } else if (action === "queue") {
    queueChoice();
  } else if (action === "unqueue") {
    unqueueSelected({ mode: d.choice.mode, both: "", left: "", right: "" });
  } else {
    return;
  }
  renderDetail();
});

queueEl.addEventListener("input", (e) => {
  const el = e.target;
  const f = state.form;
  if (el.name === "cs-comment") {
    f.comment = el.value;
    f.commentTouched = true;
  } else if (el.name === "cs-source-other") f.sourceOther = el.value;
  else if (el.name === "cs-hashtags") f.hashtags = el.value;
  else if (el.name === "cs-review") f.review = el.checked;
  else if (el.name === "cs-source") {
    f.sources = el.checked ? [...new Set([...f.sources, el.value])] : f.sources.filter(v => v !== el.value);
  }
});

function changesetTags() {
  const f = state.form;
  return buildChangesetTags({
    comment: f.comment,
    sources: [...f.sources, ...splitList(f.sourceOther)],
    hashtags: f.hashtags.split(/[\s;,]+/).filter(Boolean),
    reviewRequested: f.review,
    locale: i18n.lang,
    host: `${window.location.origin}${window.location.pathname}`,
    imageryUsed: [...(store.imageryUsed || [])],
    changesetsCount: state.user && state.user.changesetsCount,
  });
}

function dropFromQueue(dropped) {
  queue.remove(dropped.map(d => d.intent.wayId));
}

async function preparePlan() {
  const plan = await planUpload(osm, queue.list(), env);
  dropFromQueue(plan.dropped);
  if (state.detail.kind === "way" && plan.dropped.some(d => d.intent.wayId === state.detail.way.id)) refreshSelected = state.detail.way.id;
  return { ...plan, max: env.maxChangesetsPerUpload };
}

async function withBusy(task) {
  state.busy = true;
  renderQueue();
  try {
    await task();
  } finally {
    state.busy = false;
    renderQueue();
    syncQueuedState();
    if (refreshSelected !== null) {
      const id = refreshSelected;
      refreshSelected = null;
      selectWay(id);
    }
  }
}

async function onPlan() {
  state.result = null;
  await withBusy(async () => {
    try {
      state.plan = await preparePlan();
    } catch (err) {
      state.plan = null;
      state.result = { done: [], error: i18n.t("edit.result.failed", { message: err.message }) };
    }
  });
}

function tagsErrorMessage(err) {
  if (err.message === "source-required") return i18n.t("edit.upload.sourceRequired");
  if (err.message === "comment-required") return i18n.t("edit.upload.commentRequired");
  return i18n.t("edit.result.failed", { message: err.message });
}

async function onSend() {
  if (!state.user || !state.plan) return;
  let tags;
  try {
    tags = changesetTags();
  } catch (err) {
    state.result = { done: [], error: tagsErrorMessage(err) };
    return renderQueue();
  }
  const announced = state.plan.groups.length;
  await withBusy(async () => {
    try {
      const plan = await preparePlan();
      if (plan.tooMany || plan.groups.length !== announced || plan.dropped.length) {
        state.plan = plan;
        state.result = { done: [], error: i18n.t("edit.plan.changed") };
        return;
      }
      const outcome = await uploadGroups({ osm, groups: plan.groups, tags });
      queue.remove(outcome.done.flatMap(d => d.wayIds));
      const result = { done: outcome.done, failed: outcome.failed, conflictWayId: null, closed: [] };
      if (outcome.failed) {
        result.conflictWayId = outcome.failed.conflictWayId;
        if (result.conflictWayId) queue.remove(result.conflictWayId);
        try {
          result.closed = await closeEmptyChangesets({ osm, apiUrl: env.apiUrl, uid: state.user.uid, createdBy: `${APP_NAME} ${APP_VERSION}` });
        } catch {}
      }
      if (outcome.done.length && state.user.changesetsCount != null) state.user.changesetsCount += outcome.done.reduce((n, d) => n + d.changesetIds.length, 0);
      state.plan = null;
      state.result = result;
      scheduleCandidates();
      const touched = new Set([...outcome.done.flatMap(d => d.wayIds), result.conflictWayId]);
      if (state.detail.kind === "way" && touched.has(state.detail.way.id)) refreshSelected = state.detail.way.id;
    } catch (err) {
      state.result = { done: [], error: i18n.t("edit.result.failed", { message: err.message }) };
    }
  });
}

queueEl.addEventListener("click", async (e) => {
  const button = e.target.closest("[data-edit-action]");
  if (!button) return;
  const action = button.dataset.editAction;
  if (action === "dequeue") {
    queue.remove(Number(button.dataset.wayId));
    state.plan = null;
  } else if (action === "undo") {
    queue.undo();
    state.plan = null;
  } else if (action === "plan") {
    return onPlan();
  } else if (action === "send") {
    return onSend();
  } else {
    return;
  }
  if (state.detail.kind === "way") {
    const queued = queue.get(state.detail.way.id);
    state.detail = { ...state.detail, queued, choice: queued ? choiceFromIntent(queued) : state.detail.choice };
  }
  renderDetail();
  renderQueue();
  syncQueuedState();
});

const dock = document.getElementById("edit-dock");
const dockToggle = document.getElementById("edit-dock-toggle");
function setDockOpen(open) {
  dock.classList.toggle("open", open);
  dock.classList.toggle("closed", !open);
  dockToggle.setAttribute("aria-expanded", open ? "true" : "false");
}
dockToggle.addEventListener("click", () => setDockOpen(!dock.classList.contains("open")));

refreshAuth();

map = store.mapReady
  ? store.map
  : await new Promise(resolve => window.addEventListener("bpn:map-ready", e => resolve(e.detail), { once: true }));

window.BPNMap?.setLegendOpen(false);

const WIDTH = ["interpolate", ["linear"], ["zoom"], 16, 4, 19, 9];
map.addSource(SOURCE, { type: "geojson", data: EMPTY_COLLECTION, promoteId: "osm_id" });
map.addLayer({
  id: LAYER, type: "line", source: SOURCE,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: {
    "line-color": ["case", ["boolean", ["feature-state", "queued"], false], "#16a34a", "#c026d3"],
    "line-width": WIDTH,
    "line-opacity": 0.85,
  },
});
map.addLayer({
  id: SELECTED, type: "line", source: SOURCE, filter: NO_SELECTION,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#111827", "line-width": ["interpolate", ["linear"], ["zoom"], 16, 7, 19, 13], "line-opacity": 0.6 },
});
for (const [id, color, sign] of [[SIDE_LEFT, "#0284c7", -1], [SIDE_RIGHT, "#ea580c", 1]]) {
  map.addLayer({
    id, type: "line", source: SOURCE, filter: NO_SELECTION,
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: {
      "line-color": color,
      "line-width": ["interpolate", ["linear"], ["zoom"], 16, 3, 19, 5],
      "line-offset": ["interpolate", ["linear"], ["zoom"], 16, sign * 7, 19, sign * 14],
    },
  });
}

let controller = null;
let timer = null;

async function loadCandidates() {
  if (controller) controller.abort();
  if (map.getZoom() < env.candidateMinZoom) {
    controller = null;
    liveFeatures.clear();
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
    liveFeatures.clear();
    for (const f of collection.features) liveFeatures.set(f.properties.osm_id, f);
    map.getSource(SOURCE)?.setData(collection);
    syncQueuedState();
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

async function geometryOf(id) {
  const cached = liveFeatures.get(id);
  if (cached) return cached.geometry.coordinates;
  const elements = await osm.getFeature("way", id, true);
  const nodes = new Map(elements.filter(f => f.type === "node").map(n => [n.id, [n.lon, n.lat]]));
  const way = elements.find(f => f.type === "way" && f.id === id);
  return way.nodes.map(n => nodes.get(n)).filter(Boolean);
}

async function selectWay(id) {
  map.setFilter(SELECTED, ["==", ["get", "osm_id"], id]);
  setDockOpen(true);
  state.detail = { kind: "loading" };
  renderDetail();
  try {
    const [way] = await osm.getFeature("way", id);
    const coords = await geometryOf(id);
    const lengthM = lineLengthM(coords);
    state.detail = {
      kind: "way",
      way,
      editable: isEditableCandidate(way.tags),
      bbox: bboxOf(coords),
      lengthM,
      longWay: lengthM > env.longWayWarningM,
      queued: queue.get(id),
      choice: choiceFromIntent(queue.get(id)),
    };
  } catch (err) {
    state.detail = { kind: "error", message: err && err.message };
  }
  renderDetail();
  (detailEl.querySelector(".edit-form") || detailEl).scrollIntoView({ block: "nearest", behavior: "smooth" });
}

map.on("click", LAYER, (e) => {
  const id = Number(e.features?.[0]?.properties?.osm_id);
  if (Number.isFinite(id) && id > 0) selectWay(id);
});
map.on("mouseenter", LAYER, () => { map.getCanvas().style.cursor = "pointer"; });
map.on("mouseleave", LAYER, () => { map.getCanvas().style.cursor = ""; });
map.on("moveend", scheduleCandidates);
loadCandidates();
