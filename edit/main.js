import { i18n } from "../map/i18n.js";
import { createApiGuard } from "./api-guard.js";
import { blockApi, createApiMeter, installApiChain } from "./api-meter.js";
import { limitConcurrency } from "./api-queue.js";
import { store } from "../map/store.js";
import { guardEnvironment, isLoggedIn, login, loginInProgress, logout, tabId } from "./auth.js";
import { EMPTY_COLLECTION, boundsBox, boxString, boxWithin, candidateRequest, candidateWindow, candidatesFromMapData, countInBox, mergeCandidates, mergeSourceIds, sourceIds } from "./candidates.js";
import { MAX_TAG_LENGTH, buildChangesetTags, hashtagsValue, normalizeHashtags, sourceValue, splitList, tooLongFields } from "./changeset.js";
import { createClient } from "./client.js";
import { APP_NAME, APP_VERSION, envFromDocument } from "./env.js";
import { DEV_SOURCE, MAX_FILE_BYTES, createDevDataStore, devDataFromFile } from "./dev-data.js";
import { errorKind, errorMessage } from "./errors.js";
import { bboxOf, lineLengthM } from "./geo.js";
import { chooseValue, choiceFromIntent, completeChoice, makeIntent, switchMode } from "./intent.js";
import { linesOf, matchCandidate } from "./match.js";
import { nextCandidate } from "./next.js";
import { closeEmptyChangesets, planUpload, queueRoom, uploadGroups, zonesFor } from "./osm.js";
import { authView, detailView, devDataView, editLock, meterView, navView, queueView, statusView, tooLongMessage } from "./panel.js";
import { composeComment, describeGroup, indexCommunes } from "./places.js";
import { createPace } from "./pace.js";
import { createLookTracker, lookTimeMs } from "./look.js";
import { createQueue } from "./queue.js";
import { coveredIndexes, createReviewStore, samplesAlong } from "./review.js";
import { shortcutFor, sideForValue } from "./shortcuts.js";
import { createSkipList } from "./skipped.js";
import { DOCK_KEY, DOCK_POSITIONS, boxOf, boxVisible, fitPadding, freeRect, readDockPosition } from "./viewport.js";
import { isEditableCandidate, matchesWhitelist } from "./whitelist.js";

const SOURCE = "edit-candidates";
const LAYER = "edit-candidates";
const SELECTION = "edit-selection";
const SELECTED = "edit-candidates-selected";
const SELECTED_CASING = "edit-candidates-selected-casing";
const SIDE_LEFT = "edit-candidates-left";
const SIDE_RIGHT = "edit-candidates-right";
const FIT_MARGIN_PX = 40;
const VISIBLE_MARGIN_PX = 4;
const FIT_DURATION_MS = 250;
const WIDER_SEARCH = [2, 4];

const env = envFromDocument(document);
const storage = window.localStorage;
const meter = env.apiMeter ? createApiMeter({ storage, env: env.name, apiUrl: env.apiUrl }) : null;
const guard = createApiGuard({
  apiUrl: env.apiUrl,
  mapPerMinute: env.mapCallsPerMinute,
  pauseMs: env.pauseAfter509Ms,
  storage,
  key: `bpn.apiPause.${env.name}`,
});
installApiChain(window, {
  apiUrl: env.apiUrl,
  meter,
  guard,
  limit: (fetchImpl, options) => limitConcurrency(fetchImpl, { ...options, max: env.maxConcurrentApi }),
});
const looks = createLookTracker({ storage, env: env.name, history: env.lookHistory, tolerance: env.lookQuickTolerance });
const pace = createPace({
  storage,
  env: env.name,
  windowMs: env.paceWindowMs,
  maxMeters: env.paceMaxMeters,
  blockMeters: env.paceBlockMeters,
  repeatMs: env.paceRepeatMs,
  cooldownMs: env.paceCooldownMs,
});
if (!env.editEnabled) blockApi(window, env.apiUrl);
const osm = createClient(window.OSM);
const tab = tabId(window.sessionStorage);

guardEnvironment({ env: env.name, storage, osm });
osm.configure({ apiUrl: env.apiUrl });

const queue = createQueue({ storage, env: env.name });
const skipped = createSkipList({ storage, env: env.name });
const reviews = createReviewStore({ storage, env: env.name, ttlMs: env.reviewTtlMs });
let reviewSamples = [];
let reviewSeen = new Set();
let selectionCoords = null;
const visited = new Set();
const navEl = document.getElementById("edit-nav");
let navHint = "";
let candidatesBlocked = null;
let loadedBoxes = [];
const authEl = document.getElementById("edit-auth");
const statusEl = document.getElementById("edit-status");
const detailEl = document.getElementById("edit-detail");
const queueEl = document.getElementById("edit-queue");
const editBar = document.getElementById("edit-bar");
const enterButton = document.getElementById("edit-enter");
const pendingEl = document.getElementById("edit-enter-pending");
const exitButton = document.getElementById("edit-exit");
const exitDialog = document.getElementById("edit-exit-dialog");
const exitText = document.getElementById("edit-exit-text");
const MODE_KEY = `bpn.editing.${env.name}`;
let active = false;
let headerWasOpen = false;
store.editing = false;

const state = {
  user: null,
  detail: { kind: "none" },
  plan: null,
  result: null,
  busy: false,
  form: {
    remark: "",
    sources: [],
    sourceOther: "",
    hashtags: env.defaultHashtags.join(" "),
    review: false,
  },
};
const liveFeatures = new Map();
let sourceIndex = new Map();
let map = null;
let refreshSelected = null;
let communes = [];

fetch(new URL("../communes.geojson", import.meta.url))
  .then(res => (res.ok ? res.json() : null))
  .then((data) => {
    communes = indexCommunes(data);
    if (state.plan) renderQueue();
  })
  .catch(() => {});

function hashtagList() {
  return normalizeHashtags(state.form.hashtags.split(/[\s;,]+/).filter(Boolean));
}

function commentFor(group) {
  return composeComment(describeGroup(group.entries, communes), { remark: state.form.remark, hashtags: hashtagList() });
}

function planComments() {
  return state.plan ? state.plan.groups.map(commentFor) : [];
}

function refreshCommentPreviews() {
  planComments().forEach((text, i) => {
    const el = queueEl.querySelector(`[data-comment-group="${i}"]`);
    if (el) el.textContent = text;
  });
}

function showAuth(view) {
  authEl.innerHTML = html`${authView(view, i18n)}`;
}

function showStatus(view) {
  statusEl.textContent = statusView(view, i18n);
}

function basemapAllowed() {
  return Boolean(window.BPNMap) && env.editBasemaps.includes(window.BPNMap.currentBasemap());
}

function qualityNow() {
  const status = pace.status();
  return { basemapOk: basemapAllowed(), tooFast: status.tooFast, paceLeftMs: status.cooldownLeftMs, lookMode: env.lookMode, lookHasty: looks.hasty() };
}

function renderDetail() {
  if (state.detail.kind === "way" && state.detail.editable) state.detail = { ...state.detail, ...qualityNow(), room: roomFor(state.detail) };
  detailEl.innerHTML = html`${detailView(state.detail, i18n, env.webUrl, env)}`;
  showSideLines();
  if (selectionCoords) showSelection(selectionCoords);
}

function showSideLines() {
  if (!map || !map.getLayer(SIDE_LEFT)) return;
  const d = state.detail;
  const sides = d.kind === "way" && d.editable && d.choice && d.choice.mode === "sides";
  for (const id of [SIDE_LEFT, SIDE_RIGHT]) map.setLayoutProperty(id, "visibility", sides ? "visible" : "none");
}

function showSelection(coords) {
  selectionCoords = coords || null;
  const source = map && map.getSource(SELECTION);
  if (!source) return;
  const queued = state.detail.kind === "way" && Boolean(state.detail.queued);
  source.setData(coords
    ? { type: "FeatureCollection", features: [{ type: "Feature", properties: { queued }, geometry: { type: "LineString", coordinates: coords } }] }
    : EMPTY_COLLECTION);
}

function reviewState(done) {
  if (!env.reviewZoom) return null;
  const total = reviewSamples.length || 1;
  return { zoom: env.reviewZoom, percent: done ? 100 : Math.floor((100 * reviewSeen.size) / total), done };
}

function noteReview() {
  let d = state.detail;
  if (!map || d.kind !== "way" || !d.editable || d.fitting) return false;
  let changed = false;
  if (!d.seenWhole && (d.visible || wholeWayVisible(d.coords))) {
    reviews.markWhole(d.way.id, d.way.version);
    d = { ...d, seenWhole: true };
    changed = true;
  }
  if (d.review && !d.review.done && map.getZoom() >= env.reviewZoom - 1e-6) {
    const points = reviewSamples.map(c => map.project(c));
    for (const i of coveredIndexes(points, viewArea().free, VISIBLE_MARGIN_PX)) reviewSeen.add(i);
    const done = reviewSeen.size >= reviewSamples.length;
    if (done) reviews.markDetail(d.way.id, d.way.version);
    const review = reviewState(done);
    if (review.percent !== d.review.percent || done) {
      d = { ...d, review };
      changed = true;
    }
  }
  if (changed) state.detail = d;
  return changed;
}

function goToUnseenPart() {
  const d = state.detail;
  if (!map || d.kind !== "way" || !d.review) return;
  const index = reviewSamples.findIndex((_, i) => !reviewSeen.has(i));
  if (index < 0) return;
  const { canvas, free } = viewArea();
  const offset = [(free.left + free.right) / 2 - canvas.width / 2, (free.top + free.bottom) / 2 - canvas.height / 2];
  map.easeTo({ center: reviewSamples[index], zoom: Math.max(map.getZoom(), env.reviewZoom), offset, duration: FIT_DURATION_MS });
}

function anyPartVisible(coords) {
  const { free } = viewArea();
  return coords.some(c => {
    const p = map.project(c);
    return p.x >= free.left && p.x <= free.right && p.y >= free.top && p.y <= free.bottom;
  });
}

function roomFor(detail) {
  return queueRoom(queue.list(), { wayId: detail.way.id, bbox: detail.bbox }, env);
}

function editBlocked() {
  const d = state.detail;
  return d.kind !== "way" || !d.editable || Boolean(editLock(d));
}

function formIssues() {
  const f = state.form;
  return tooLongFields({
    source: sourceValue([...f.sources, ...splitList(f.sourceOther)]),
    hashtags: hashtagsValue(hashtagList()),
  });
}

function refreshFormChecks() {
  const issues = formIssues();
  for (const key of ["source", "hashtags"]) {
    const el = queueEl.querySelector(`[data-field-error="${key}"]`);
    const issue = issues.find(i => i.key === key);
    if (el) el.textContent = issue ? tooLongMessage(issue, i18n.t) : "";
  }
  const send = queueEl.querySelector('[data-edit-action="send"]');
  if (send) send.disabled = issues.length > 0 || !state.user || state.busy;
}

function renderPending() {
  const count = queue.size();
  pendingEl.hidden = count === 0;
  pendingEl.textContent = count ? i18n.t("edit.mode.pending", { count }) : "";
}

function renderQueue() {
  const items = queue.list();
  renderPending();
  queueEl.innerHTML = html`${queueView({
    items,
    zones: zonesFor(items, env),
    maxZones: env.maxChangesetsPerUpload,
    tooLong: formIssues(),
    form: state.form,
    plan: state.plan,
    comments: planComments(),
    result: state.result,
    busy: state.busy,
    loggedIn: Boolean(state.user),
  }, i18n, env.webUrl, { ...env, maxTagLength: MAX_TAG_LENGTH })}`;
}

function syncQueuedState() {
  if (!map || !map.getSource(SOURCE)) return;
  for (const id of liveFeatures.keys()) map.setFeatureState({ source: SOURCE, id }, { queued: queue.has(id), skipped: skipped.has(id) });
}

function renderNav() {
  navEl.innerHTML = html`${navView({
    candidates: liveFeatures.size,
    skipped: skipped.size(),
    selected: state.detail.kind === "way",
    hint: navHint,
  }, i18n)}`;
}

function selectNext(widen = true) {
  if (!map) return false;
  const current = state.detail.kind === "way" ? state.detail.way.id : null;
  const here = map.getCenter();
  const from = current && state.detail.bbox
    ? [(state.detail.bbox[0] + state.detail.bbox[2]) / 2, (state.detail.bbox[1] + state.detail.bbox[3]) / 2]
    : [here.lng, here.lat];
  const pool = [...liveFeatures.values()];
  const base = new Set([...skipped.list(), ...queue.list().map(i => i.wayId)]);
  if (current) base.add(current);
  let next = nextCandidate(pool, from, new Set([...base, ...visited]));
  if (!next && visited.size) {
    visited.clear();
    next = nextCandidate(pool, from, base);
  }
  if (!next) {
    const searching = widen && current !== null && searchWider(current);
    navHint = searching ? i18n.t("edit.nav.searching") : candidatesBlocked === "zoom" ? i18n.t("edit.status.zoomIn", { zoom: env.candidateFloorZoom }) : i18n.t("edit.nav.none");
    renderNav();
    return false;
  }
  navHint = "";
  selectWay(next.properties.osm_id);
  return true;
}

function deselect() {
  pendingKeys = [];
  state.detail = { kind: "none" };
  showSelection(null);
  renderDetail();
  renderNav();
}

function skipSelected() {
  const d = state.detail;
  if (d.kind !== "way") return;
  skipped.add(d.way.id);
  if (queue.has(d.way.id)) {
    queue.remove(d.way.id);
    state.plan = null;
    renderQueue();
  }
  syncQueuedState();
  if (!selectNext()) deselect();
}

function viewArea() {
  const canvas = { width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight };
  const narrow = window.matchMedia("(max-width: 600px)").matches;
  const rect = dock.classList.contains("open") ? dock.getBoundingClientRect() : null;
  return { canvas, free: freeRect(canvas, rect, narrow ? "bottom" : dock.dataset.position) };
}

function wayBox(coords) {
  return boxOf(coords.map(c => map.project(c)));
}

function wholeWayVisible(coords, margin = VISIBLE_MARGIN_PX) {
  if (!map || !coords || !coords.length) return false;
  return boxVisible(viewArea().free, wayBox(coords), margin);
}

let settleTimer = null;
let pendingKeys = [];

function cameraFor(d, maxZoom) {
  const { canvas, free } = viewArea();
  return map.cameraForBounds([[d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]], {
    padding: fitPadding(canvas, free, FIT_MARGIN_PX),
    bearing: map.getBearing(),
    maxZoom,
  });
}

function moveTo(camera) {
  map.easeTo({ ...camera, bearing: map.getBearing(), pitch: map.getPitch(), duration: FIT_DURATION_MS });
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => updateVisibility(true), FIT_DURATION_MS + 150);
  return "moving";
}

function frameWay(d) {
  if (!map || d.kind !== "way") return "hidden";
  const camera = cameraFor(d, env.fitMaxZoom);
  const zoom = map.getZoom();
  const visible = wholeWayVisible(d.coords, FIT_MARGIN_PX);
  if (!camera) return visible ? "visible" : "hidden";
  if (visible && zoom >= Math.min(camera.zoom, env.fitMinZoom) - 1e-6) return "visible";
  if (d.seenWhole && camera.zoom < zoom) return anyPartVisible(d.coords) ? "partial" : bringWholeWayIntoView(d);
  return moveTo(camera);
}

function bringWholeWayIntoView(d, force = false) {
  if (!map || d.kind !== "way") return "hidden";
  if (!force && wholeWayVisible(d.coords, FIT_MARGIN_PX)) return "visible";
  const camera = cameraFor(d, map.getZoom());
  if (!camera) return wholeWayVisible(d.coords) ? "visible" : "hidden";
  return moveTo(camera);
}

function applyView(view) {
  const d = state.detail;
  if (d.kind !== "way") return;
  state.detail = { ...d, fitting: view === "moving", visible: view === "visible" };
}

function lockSignature(d) {
  return [d.visible, d.fitting, d.seenWhole, d.review && d.review.percent, d.review && d.review.done].join("|");
}

function updateVisibility(settled = false) {
  const d = state.detail;
  if (d.kind !== "way" || !d.editable) return;
  if (d.fitting && !settled && map.isMoving()) return;
  const visible = wholeWayVisible(d.coords) || Boolean(d.userFit && d.fitting && settled);
  const before = lockSignature(d);
  state.detail = { ...d, visible, fitting: false, userFit: false };
  noteReview();
  if (lockSignature(state.detail) === before) return;
  renderDetail();
  if (!editLock(state.detail)) replayPendingKeys();
  else pendingKeys = [];
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
  if (!sides || editBlocked()) return false;
  const intent = makeIntent({ way: d.way, left: sides.left, right: sides.right, bbox: d.bbox, lengthM: d.lengthM, coords: d.coords });
  if (!d.queued) {
    pace.record(d.lengthM);
    looks.record(d.lookLeftMs > 0);
  }
  queue.put(intent);
  skipped.remove(intent.wayId);
  state.plan = null;
  state.result = null;
  state.detail = { ...d, queued: intent };
  renderQueue();
  syncQueuedState();
  return true;
}

function applyValue(side, value) {
  if (editBlocked()) return;
  const d = state.detail;
  state.detail = { ...d, choice: chooseValue(d.choice, side, value) };
  if (env.autoQueue && completeChoice(state.detail.choice)) {
    if (queueChoice() && env.autoAdvance && selectNext()) return;
  } else if (env.autoQueue && d.queued) {
    unqueueSelected(state.detail.choice);
  }
  renderDetail();
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
  if (action === "basemap") {
    if (window.BPNMap) window.BPNMap.setBasemap(env.editBasemaps[0]);
    return;
  }
  if (action === "fit") {
    applyView(bringWholeWayIntoView(d, true));
    state.detail = { ...state.detail, userFit: state.detail.fitting };
    renderDetail();
    return;
  } else if (action === "plan") {
    return onPlan();
  } else if (action === "review-next") {
    return goToUnseenPart();
  } else if (action === "choose") {
    return applyValue(button.dataset.side, button.dataset.value);
  } else if (action === "skip") {
    return skipSelected();
  } else if (action === "next") {
    selectNext();
    return;
  } else if (action === "mode") {
    if (editBlocked()) return;
    state.detail = { ...d, choice: switchMode(d.choice, button.dataset.mode) };
  } else if (action === "queue") {
    if (queueChoice() && env.autoAdvance && selectNext()) return;
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
  if (el.name === "cs-remark") f.remark = el.value;
  else if (el.name === "cs-source-other") f.sourceOther = el.value;
  else if (el.name === "cs-hashtags") f.hashtags = el.value;
  else if (el.name === "cs-review") f.review = el.checked;
  else if (el.name === "cs-source") {
    f.sources = el.checked ? [...new Set([...f.sources, el.value])] : f.sources.filter(v => v !== el.value);
  }
  if (el.name === "cs-remark" || el.name === "cs-hashtags") refreshCommentPreviews();
  refreshFormChecks();
});

function changesetTags(group, changesetsCount) {
  const f = state.form;
  return buildChangesetTags({
    comment: commentFor(group),
    sources: [...f.sources, ...splitList(f.sourceOther)],
    hashtags: hashtagList(),
    reviewRequested: f.review,
    locale: i18n.lang,
    host: `${window.location.origin}${window.location.pathname}`,
    imageryUsed: [...(store.imageryUsed || [])],
    changesetsCount,
  });
}

async function freshChangesetTags(group) {
  const me = await osm.getUser("me");
  const count = me && me.changesets ? Number(me.changesets.count) : NaN;
  if (state.user && Number.isFinite(count)) state.user.changesetsCount = count;
  return changesetTags(group, count);
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
    if (state.detail.kind === "way") renderDetail();
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
      state.result = { done: [], error: failure(err) };
      endSessionIfRevoked(err);
    }
  });
}

function failure(err) {
  return i18n.t("edit.result.failed", { message: errorMessage(err, i18n.t) });
}

function endSessionIfRevoked(err) {
  if (errorKind(err) !== "auth") return false;
  logout({ osm, storage });
  refreshAuth(errorMessage(err, i18n.t));
  return true;
}

function tagsErrorMessage(err) {
  if (err.message === "source-required") return i18n.t("edit.upload.sourceRequired");
  const issues = formIssues();
  if (issues.length) return issues.map(issue => tooLongMessage(issue, i18n.t)).join(" ");
  const tooLong = /^tag-too-long:(.+)$/.exec(err.message || "");
  if (tooLong) return tooLong[1].split(",").map(key => tooLongMessage({ key, max: MAX_TAG_LENGTH }, i18n.t)).join(" ");
  return failure(err);
}

async function onSend() {
  if (state.busy || !state.user || !state.plan) return;
  if (!isLoggedIn({ osm, storage, env })) {
    state.plan = null;
    await refreshAuth(i18n.t("edit.upload.loginFirst"));
    return;
  }
  try {
    if (formIssues().length) throw new Error("tag-too-long");
    state.plan.groups.forEach(group => changesetTags(group, 0));
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
      state.plan = plan;
      const outcome = await uploadGroups({ osm, groups: plan.groups, tagsFor: freshChangesetTags, settings: env });
      queue.remove(outcome.done.flatMap(d => d.wayIds));
      dropFromQueue(outcome.dropped);
      const result = { done: outcome.done, failed: outcome.failed, conflictWayIds: [], closed: [], dropped: outcome.dropped, retried: outcome.retried };
      if (outcome.failed) {
        const err = { cause: outcome.failed.status, message: outcome.failed.message };
        result.failed = { ...outcome.failed, message: errorMessage(err, i18n.t) };
        result.conflictWayIds = outcome.failed.conflictWayIds || [];
        if (result.conflictWayIds.length) queue.remove(result.conflictWayIds);
        if (endSessionIfRevoked(err)) result.closed = [];
      }
      if ((outcome.failed && errorKind({ cause: outcome.failed.status }) !== "auth") || outcome.retried) {
        try {
          result.closed = await closeEmptyChangesets({ osm, uid: state.user.uid, createdBy: `${APP_NAME} ${APP_VERSION}` });
        } catch {}
      }
      state.plan = null;
      state.result = result;
      scheduleCandidates();
      const touched = new Set([...outcome.done.flatMap(d => d.wayIds), ...outcome.dropped.map(d => d.intent.wayId), ...result.conflictWayIds]);
      if (state.detail.kind === "way" && touched.has(state.detail.way.id)) refreshSelected = state.detail.way.id;
    } catch (err) {
      state.result = { done: [], error: failure(err) };
      endSessionIfRevoked(err);
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

navEl.addEventListener("click", (e) => {
  const action = e.target.closest("[data-edit-action]")?.dataset.editAction;
  if (action === "next") selectNext();
  else if (action === "reset-skipped") {
    skipped.clear();
    visited.clear();
    navHint = "";
    syncQueuedState();
    renderNav();
  }
});

function runEditKey(action) {
  const d = state.detail;
  if (d.kind !== "way" || !d.editable) return;
  if (action.type === "value") {
    applyValue(sideForValue(d.choice), action.value);
  } else if (action.type === "mode" && !editBlocked()) {
    state.detail = { ...d, choice: switchMode(d.choice, action.mode) };
    renderDetail();
  }
}

function replayPendingKeys() {
  const keys = pendingKeys;
  pendingKeys = [];
  const wayId = state.detail.kind === "way" ? state.detail.way.id : null;
  for (const key of keys) {
    if (state.detail.kind !== "way" || state.detail.way.id !== wayId || editBlocked()) return;
    runEditKey(key);
  }
}

document.addEventListener("keydown", (e) => {
  if (!active) return;
  const action = shortcutFor(e);
  if (!action) return;
  const d = state.detail;
  const editing = d.kind === "way" && d.editable;
  if ((action.type === "value" || action.type === "mode") && widening) return;
  if ((action.type === "value" || action.type === "mode") && editing && d.fitting) {
    pendingKeys.push(action);
    return;
  }
  if (action.type === "next") {
    e.preventDefault();
    e.stopPropagation();
    selectNext();
  } else if (action.type === "deselect") {
    if (d.kind !== "none") deselect();
  } else if (action.type === "skip") {
    if (d.kind === "way") skipSelected();
  } else if ((action.type === "value" || action.type === "mode") && editing) {
    runEditKey(action);
  }
}, true);

const dock = document.getElementById("edit-dock");
const dockToggle = document.getElementById("edit-dock-toggle");
const dockButtons = [...document.querySelectorAll("#edit-dock-position [data-dock]")];

function foldSidePanel(position) {
  if (position === "left" && window.BPNMap) window.BPNMap.setHeaderOpen(false);
  if (position === "right" && window.BPNMap) window.BPNMap.setLegendOpen(false);
}

function setDockPosition(position, persist) {
  const value = DOCK_POSITIONS.includes(position) ? position : "right";
  dock.dataset.position = value;
  for (const button of dockButtons) button.setAttribute("aria-pressed", button.dataset.dock === value ? "true" : "false");
  if (persist) {
    try { storage.setItem(DOCK_KEY, value); } catch {}
  }
  if (active) foldSidePanel(value);
  if (map && state.detail.kind === "way") afterLayoutChange();
}

function afterLayoutChange() {
  const d = state.detail;
  if (!map || d.kind !== "way") return;
  const view = bringWholeWayIntoView(d);
  if (view === "moving") {
    applyView(view);
    renderDetail();
  } else {
    updateVisibility(true);
  }
}

for (const button of dockButtons) button.addEventListener("click", () => setDockPosition(button.dataset.dock, true));
setDockPosition(readDockPosition(storage), false);
function setDockOpen(open) {
  dock.classList.toggle("open", open);
  dock.classList.toggle("closed", !open);
  dockToggle.setAttribute("aria-expanded", open ? "true" : "false");
}
dockToggle.addEventListener("click", () => {
  setDockOpen(!dock.classList.contains("open"));
  afterLayoutChange();
});

const mapReady = store.mapReady
  ? Promise.resolve(store.map)
  : new Promise(resolve => window.addEventListener("bpn:map-ready", e => resolve(e.detail), { once: true }));

function setEditLayersVisible(visible) {
  if (!map) return;
  for (const id of [LAYER, SELECTED_CASING, SELECTED]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
  if (!visible) for (const id of [SIDE_LEFT, SIDE_RIGHT]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
}

const GOVERNED_SOURCES = ["pedestrian", DEV_SOURCE];
const PREV_BASEMAP_KEY = `bpn.editPrevBasemap.${env.name}`;
let layerSnapshot = null;

function enforceEditLayers() {
  if (!map) return;
  layerSnapshot = layerSnapshot || {};
  for (const layer of map.getStyle().layers) {
    if (!GOVERNED_SOURCES.includes(layer.source)) continue;
    const now = map.getLayoutProperty(layer.id, "visibility") || "visible";
    if (!(layer.id in layerSnapshot)) layerSnapshot[layer.id] = now;
    const want = env.editRequiredLayers.includes(layer.id) ? "visible" : env.editOptionalLayers.includes(layer.id) ? now : "none";
    if (want !== now) map.setLayoutProperty(layer.id, "visibility", want);
  }
}

function applyEditMap() {
  if (!map || !window.BPNMap) return;
  const current = window.BPNMap.currentBasemap();
  if (!env.editBasemaps.includes(current)) {
    try { window.sessionStorage.setItem(PREV_BASEMAP_KEY, current); } catch {}
    window.BPNMap.setBasemap(env.editBasemaps[0]);
  }
  window.BPNMap.setBasemapWhitelist(env.editBasemaps);
  enforceEditLayers();
  window.BPNMap.setLegendPolicy({ required: env.editRequiredLayers, optional: env.editOptionalLayers });
}

function restoreEditMap() {
  if (!map || !window.BPNMap) return;
  window.BPNMap.setBasemapWhitelist(null);
  for (const [id, visibility] of Object.entries(layerSnapshot || {})) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
  }
  layerSnapshot = null;
  window.BPNMap.setLegendPolicy(null);
  let previous = null;
  try {
    previous = window.sessionStorage.getItem(PREV_BASEMAP_KEY);
    window.sessionStorage.removeItem(PREV_BASEMAP_KEY);
  } catch {}
  if (previous && previous !== window.BPNMap.currentBasemap()) window.BPNMap.setBasemap(previous);
}

let qualityTick = null;
let lastTick = 0;

function tickQuality() {
  const t = Date.now();
  const elapsed = lastTick ? t - lastTick : 0;
  lastTick = t;
  const d = state.detail;
  if (!active || d.kind !== "way" || !d.editable) return;
  const before = editLock(d);
  const shown = [Math.ceil((d.lookLeftMs || 0) / 1000), Math.ceil((d.paceLeftMs || 0) / 1000), d.basemapOk, d.tooFast].join("|");
  const quality = qualityNow();
  let lookLeftMs = d.lookLeftMs || 0;
  if (lookLeftMs > 0 && !d.fitting && quality.basemapOk && document.visibilityState === "visible") lookLeftMs = Math.max(0, lookLeftMs - elapsed);
  state.detail = { ...d, ...quality, lookLeftMs };
  const after = [Math.ceil(lookLeftMs / 1000), Math.ceil(quality.paceLeftMs / 1000), quality.basemapOk, quality.tooFast].join("|");
  if (after !== shown || editLock(state.detail) !== before) renderDetail();
}

function enterEdit() {
  if (active || !env.editEnabled) return;
  active = true;
  store.editing = true;
  try { window.sessionStorage.setItem(MODE_KEY, "1"); } catch {}
  document.body.classList.add("is-editing");
  editBar.hidden = false;
  dock.hidden = false;
  headerWasOpen = document.getElementById("header").classList.contains("open");
  if (window.BPNMap) {
    window.BPNMap.stopNavigation();
    window.BPNMap.closePopups();
    window.BPNMap.setHeaderOpen(false);
  }
  foldSidePanel(dock.dataset.position);
  setDockOpen(true);
  lastTick = 0;
  qualityTick = setInterval(tickQuality, 250);
  if (map) {
    applyEditMap();
    setEditLayersVisible(true);
    loadCandidates();
  }
}

function leaveEdit() {
  if (!active) return;
  active = false;
  store.editing = false;
  try { window.sessionStorage.removeItem(MODE_KEY); } catch {}
  clearTimeout(timer);
  if (controller) controller.abort();
  controller = null;
  deselect();
  clearInterval(qualityTick);
  qualityTick = null;
  setEditLayersVisible(false);
  restoreEditMap();
  document.body.classList.remove("is-editing");
  editBar.hidden = true;
  dock.hidden = true;
  if (headerWasOpen && window.BPNMap) window.BPNMap.setHeaderOpen(true);
  enterButton.focus();
}

function requestExit() {
  if (!active || state.busy) return;
  const count = queue.size();
  if (!count) return leaveEdit();
  exitText.textContent = i18n.t("edit.mode.exitText", { count });
  exitDialog.showModal();
}

function discardQueue() {
  queue.clear();
  state.plan = null;
  state.result = null;
  if (state.detail.kind === "way") state.detail = { ...state.detail, queued: null, choice: choiceFromIntent(null) };
  renderQueue();
  syncQueuedState();
}

exitDialog.addEventListener("click", (e) => {
  const choice = e.target.closest("[data-exit-choice]")?.dataset.exitChoice;
  if (!choice) return;
  exitDialog.close();
  if (choice === "discard") discardQueue();
  if (choice === "keep" || choice === "discard") leaveEdit();
});

const SIDEWALK_LAYER = "sidewalk-roads";
const devStore = env.devData ? createDevDataStore(window.indexedDB, env.name) : null;
const dataEl = document.getElementById("edit-data");
const dataInput = document.getElementById("edit-data-file");
let devData = { active: null, loading: null, error: null };

function renderDevData() {
  if (!devStore) return;
  dataEl.innerHTML = html`${devDataView(devData, i18n)}`;
}

function swapSidewalkSource(sourceSpec) {
  const style = map.getStyle();
  const index = style.layers.findIndex(l => l.id === SIDEWALK_LAYER);
  if (index < 0) return;
  const layer = { ...style.layers[index] };
  delete layer["source-layer"];
  const before = style.layers[index + 1] ? style.layers[index + 1].id : undefined;
  map.removeLayer(SIDEWALK_LAYER);
  if (sourceSpec) {
    if (map.getSource(DEV_SOURCE)) map.getSource(DEV_SOURCE).setData(sourceSpec.data);
    else map.addSource(DEV_SOURCE, sourceSpec);
    map.addLayer({ ...layer, source: DEV_SOURCE }, before);
  } else {
    map.addLayer({ ...layer, source: "pedestrian", "source-layer": "sidewalk_roads" }, before);
    if (map.getSource(DEV_SOURCE)) map.removeSource(DEV_SOURCE);
  }
}

function applyDevData(data) {
  swapSidewalkSource({ type: "geojson", data: data.collection, promoteId: "osm_id" });
  devData = { active: data.meta, loading: null, error: null };
  renderDevData();
}

async function loadDevFile(file) {
  if (file.size > MAX_FILE_BYTES) {
    devData = { ...devData, error: "tooBig", size: Math.ceil(file.size / 1048576) };
    return renderDevData();
  }
  devData = { ...devData, loading: file.name, error: null };
  renderDevData();
  try {
    const data = devDataFromFile(await file.text(), file.name);
    await mapReady;
    await devStore.save(data);
    applyDevData(data);
  } catch (err) {
    devData = { ...devData, loading: null, error: err.code || "read" };
    renderDevData();
  }
}

async function resetDevData() {
  swapSidewalkSource(null);
  await devStore.clear();
  devData = { active: null, loading: null, error: null };
  renderDevData();
}

if (devStore) {
  renderDevData();
  dataEl.addEventListener("click", (e) => {
    const action = e.target.closest("[data-edit-action]")?.dataset.editAction;
    if (action === "data-load") dataInput.click();
    if (action === "data-reset") resetDevData();
  });
  dataInput.addEventListener("change", () => {
    const file = dataInput.files && dataInput.files[0];
    dataInput.value = "";
    if (file) loadDevFile(file);
  });
  Promise.all([devStore.load(), mapReady]).then(([saved]) => {
    if (saved && saved.collection && !devData.active) applyDevData(saved);
  });
}

function tileLines(id) {
  const lines = [];
  if (store.lastClicked && Number(store.lastClicked.id) === id) lines.push(...linesOf(store.lastClicked.geometry));
  try {
    const parts = map.querySourceFeatures("pedestrian", { sourceLayer: "sidewalk_roads", filter: ["==", ["to-number", ["get", "osm_id"]], id] });
    for (const f of parts) lines.push(...linesOf(f.geometry));
  } catch {}
  return lines;
}

function paddedBox(lines, pad = 0.0003) {
  const [w, s, e, n] = bboxOf(lines.flat());
  return [w - pad, s - pad, e + pad, n + pad];
}

async function editWay(id) {
  if (!env.editEnabled) return;
  enterEdit();
  if (window.BPNMap) window.BPNMap.closePopups();
  await mapReady;
  if (env.candidates === "pmtiles" || devData.active) return selectWay(id);
  const lines = tileLines(id);
  await loadCandidates(lines.length ? { box: paddedBox(lines), around: true } : currentRequest());
  const twins = [...(sourceIndex.get(id) || [])];
  if (twins.length === 1) return selectWay(twins[0]);
  if (twins.length > 1) return showStatus({ kind: "splitOnDev", count: twins.length });
  if (!lines.length) return showStatus({ kind: "noMatch" });
  const best = matchCandidate(lines, liveFeatures.values());
  if (!best) return showStatus({ kind: "noMatch" });
  selectWay(best.feature.properties.osm_id);
}

const meterEl = document.getElementById("edit-meter");
let meterFrame = 0;
function renderMeter() {
  if (!meter || meterFrame) return;
  meterFrame = requestAnimationFrame(() => {
    meterFrame = 0;
    const open = Boolean(meterEl.querySelector("details[open]"));
    meterEl.innerHTML = html`${meterView(meter.stats(), i18n, env)}`;
    if (open) meterEl.querySelector("details").open = true;
  });
}
if (meter) {
  meter.onChange(renderMeter);
  renderMeter();
  setInterval(renderMeter, 15000);
  meterEl.addEventListener("click", (e) => {
    if (e.target.closest("[data-edit-action=meter-reset]")) meter.reset();
  });
}

enterButton.addEventListener("click", enterEdit);
exitButton.addEventListener("click", requestExit);
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-bpn-edit-way]");
  if (!button) return;
  const id = Number(button.dataset.bpnEditWay);
  if (!Number.isFinite(id) || id <= 0) return;
  e.preventDefault();
  editWay(id);
});

window.BPNEdit = Object.freeze({
  enter: enterEdit,
  exit: requestExit,
  isActive: () => active,
  devData: () => devData.active,
  apiStats: () => (meter ? meter.stats() : null),
  resetApiStats: () => meter && meter.reset(),
  canEdit: p => Boolean(env.editEnabled && p && p.sw === "unknown" && matchesWhitelist({ highway: p.highway })),
});

enterButton.hidden = !env.editEnabled;
refreshAuth();
try {
  if (!env.editEnabled) window.sessionStorage.removeItem(MODE_KEY);
  else if (window.sessionStorage.getItem(MODE_KEY) === "1") enterEdit();
} catch {}

map = await mapReady;

if (active) foldSidePanel(dock.dataset.position);
window.addEventListener("bpn:basemap", () => {
  if (active && state.detail.kind === "way") renderDetail();
});

const WIDTH = ["interpolate", ["linear"], ["zoom"], 16, 4, 19, 9];
map.addSource(SOURCE, { type: "geojson", data: EMPTY_COLLECTION, promoteId: "osm_id" });
map.addLayer({
  id: LAYER, type: "line", source: SOURCE,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: {
    "line-color": ["case", ["boolean", ["feature-state", "queued"], false], "#16a34a", ["boolean", ["feature-state", "skipped"], false], "#9ca3af", "#c026d3"],
    "line-width": WIDTH,
    "line-opacity": 0.85,
  },
});
map.addSource(SELECTION, { type: "geojson", data: EMPTY_COLLECTION });
map.addLayer({
  id: SELECTED_CASING, type: "line", source: SELECTION,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#1f2421", "line-width": ["interpolate", ["linear"], ["zoom"], 16, 10, 19, 17], "line-opacity": 0.9 },
});
map.addLayer({
  id: SELECTED, type: "line", source: SELECTION,
  layout: { "line-cap": "round", "line-join": "round" },
  paint: {
    "line-color": ["case", ["boolean", ["get", "queued"], false], "#16a34a", "#f5c518"],
    "line-width": ["interpolate", ["linear"], ["zoom"], 16, 6, 19, 11],
  },
});
for (const [id, color, sign] of [[SIDE_LEFT, "#0284c7", -1], [SIDE_RIGHT, "#ea580c", 1]]) {
  map.addLayer({
    id, type: "line", source: SELECTION,
    layout: { "line-cap": "butt", "line-join": "round", visibility: "none" },
    paint: {
      "line-color": color,
      "line-width": ["interpolate", ["linear"], ["zoom"], 16, 4, 19, 6],
      "line-offset": ["interpolate", ["linear"], ["zoom"], 16, sign * 9, 19, sign * 16],
    },
  });
}

let controller = null;
let timer = null;

function setCandidates(features) {
  liveFeatures.clear();
  for (const [id, f] of features) liveFeatures.set(id, f);
  map.getSource(SOURCE)?.setData({ type: "FeatureCollection", features: [...liveFeatures.values()] });
  syncQueuedState();
}

function clearCandidates() {
  loadedBoxes = [];
  liveFeatures.clear();
  map.getSource(SOURCE)?.setData(EMPTY_COLLECTION);
}

function candidateFocus() {
  return state.detail.kind === "way" && state.detail.bbox ? state.detail.bbox : null;
}

function currentRequest(focus = candidateFocus()) {
  const canvas = { width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight };
  const center = map.getCenter();
  return candidateRequest({ zoom: map.getZoom(), bounds: map.getBounds(), center: [center.lng, center.lat], canvas, focus, settings: env });
}

let widening = null;

function searchWider(wayId) {
  const focus = candidateFocus();
  if (widening || !focus) return false;
  widening = (async () => {
    for (const scale of WIDER_SEARCH) {
      const center = map.getCenter();
      const box = candidateWindow({ center: [center.lng, center.lat], canvas: { width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight }, focus, settings: env, scale });
      if (loadedBoxes.some(b => boxWithin(box, b))) continue;
      await loadCandidates({ box, around: true });
      if (state.detail.kind !== "way" || state.detail.way.id !== wayId) return;
      if (selectNext(false)) return;
    }
    if (state.detail.kind === "way" && state.detail.way.id === wayId) {
      navHint = i18n.t("edit.nav.none");
      renderNav();
    }
  })().finally(() => { widening = null; });
  return true;
}

function loadAroundSelection() {
  const focus = candidateFocus();
  if (!map || !focus) return;
  const request = currentRequest(focus);
  if (request.blocked || !request.around) return;
  if (loadedBoxes.some(box => boxWithin(request.box, box))) return;
  loadCandidates(request);
}

async function loadCandidates(given = null) {
  if (!env.editEnabled) return;
  if (controller) controller.abort();
  const request = given || currentRequest();
  candidatesBlocked = request.blocked || null;
  if (request.blocked) {
    controller = null;
    if (request.blocked === "zoom" && liveFeatures.size) {
      renderNav();
      return showStatus({ kind: "zoom", minZoom: env.candidateFloorZoom, kept: liveFeatures.size });
    }
    clearCandidates();
    renderNav();
    return showStatus({ kind: request.blocked, minZoom: env.candidateFloorZoom });
  }
  const current = new AbortController();
  controller = current;
  showStatus({ kind: "loading" });
  try {
    const features = await osm.getMapData(boxString(request.box), { signal: current.signal });
    if (current.signal.aborted) return;
    sourceIndex = mergeSourceIds(sourceIndex, sourceIds(features));
    setCandidates(mergeCandidates(liveFeatures, candidatesFromMapData(features), request.box));
    loadedBoxes = [request.box, ...loadedBoxes].slice(0, 20);
    showStatus({ kind: "ready", count: countInBox(liveFeatures.values(), boundsBox(map.getBounds())) });
    renderNav();
  } catch (err) {
    if (current.signal.aborted) return;
    clearCandidates();
    showStatus({ kind: "error", message: errorMessage(err, i18n.t) });
    renderNav();
  }
}

function scheduleCandidates() {
  clearTimeout(timer);
  timer = setTimeout(loadCandidates, 300);
}

async function selectWay(id) {
  pendingKeys = [];
  const known = liveFeatures.get(id);
  showSelection(known ? known.geometry.coordinates : null);
  setDockOpen(true);
  visited.add(id);
  state.detail = { kind: "loading" };
  renderDetail();
  try {
    const elements = await osm.getFeature("way", id, true);
    const way = elements.find(f => f.type === "way" && f.id === id);
    const nodes = new Map(elements.filter(f => f.type === "node").map(n => [n.id, [n.lon, n.lat]]));
    const coords = way.nodes.map(n => nodes.get(n));
    if (coords.some(c => !c)) throw new Error("incomplete way");
    showSelection(coords);
    const detail = {
      kind: "way",
      way,
      editable: isEditableCandidate(way.tags),
      bbox: bboxOf(coords),
      coords,
      lengthM: lineLengthM(coords),
      queued: queue.get(id),
      choice: choiceFromIntent(queue.get(id)),
      lookLeftMs: queue.get(id) ? 0 : lookTimeMs(lineLengthM(coords), env),
      ...qualityNow(),
    };
    reviewSamples = env.reviewZoom ? samplesAlong(coords, env.reviewStepM) : [];
    reviewSeen = new Set();
    detail.seenWhole = reviews.seenWhole(id, way.version);
    detail.review = reviewState(reviews.seenDetail(id, way.version));
    const view = frameWay(detail);
    state.detail = { ...detail, fitting: view === "moving", visible: view === "visible" };
    noteReview();
  } catch (err) {
    const gone = err && (err.cause === 404 || err.cause === 410);
    state.detail = gone ? { kind: "gone", wayId: id } : { kind: "error", message: errorMessage(err, i18n.t) };
    if (gone) showSelection(null);
  }
  renderDetail();
  renderNav();
  (detailEl.querySelector(".edit-form") || detailEl).scrollIntoView({ block: "nearest", behavior: "smooth" });
  if (state.detail.kind === "way" && !state.detail.fitting) loadAroundSelection();
}

map.on("click", LAYER, (e) => {
  const id = Number(e.features?.[0]?.properties?.osm_id);
  if (Number.isFinite(id) && id > 0) selectWay(id);
});
map.on("mouseenter", LAYER, () => { map.getCanvas().style.cursor = "pointer"; });
map.on("mouseleave", LAYER, () => { map.getCanvas().style.cursor = ""; });
map.on("moveend", () => {
  if (!active) return;
  scheduleCandidates();
  updateVisibility(true);
});
map.on("resize", updateVisibility);
let reviewFrame = 0;
map.on("move", () => {
  if (!active || !env.reviewZoom || reviewFrame) return;
  reviewFrame = requestAnimationFrame(() => {
    reviewFrame = 0;
    if (noteReview()) renderDetail();
  });
});
map.on("style.load", () => {
  map.getSource(SOURCE)?.setData({ type: "FeatureCollection", features: [...liveFeatures.values()] });
  setEditLayersVisible(active);
  if (active) enforceEditLayers();
  syncQueuedState();
  showSideLines();
});
map.on("movestart", (e) => {
  if (e.originalEvent && state.detail.kind === "way" && state.detail.userFit) state.detail = { ...state.detail, userFit: false };
});
setEditLayersVisible(active);
if (active) {
  applyEditMap();
  loadCandidates();
}
