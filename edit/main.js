import { i18n } from "../map/i18n.js";
import { store } from "../map/store.js";
import { createApiGuard } from "./api-guard.js";
import { blockApi, createApiMeter, installApiChain } from "./api-meter.js";
import { limitConcurrency } from "./api-queue.js";
import { guardEnvironment, tabId } from "./auth.js";
import { createClient } from "./client.js";
import { envFromDocument } from "./env.js";
import { createLookTracker } from "./look.js";
import { createPace } from "./pace.js";
import { statusView } from "./panel.js";
import { createQueue } from "./queue.js";
import { createReviewStore } from "./review.js";
import { createSkipList } from "./skipped.js";
import { installAuthPanel } from "./app/auth-panel.js";
import { installCamera } from "./app/camera.js";
import { installCandidateLoader } from "./app/candidate-loader.js";
import { installDevDataPanel } from "./app/dev-data-panel.js";
import { installEditHere } from "./app/edit-here.js";
import { installEditMode } from "./app/edit-mode.js";
import { installKeyboard } from "./app/keyboard.js";
import { addEditLayers, installLayers } from "./app/layers.js";
import { installMapEvents } from "./app/map-events.js";
import { installMeterPanel } from "./app/meter-panel.js";
import { installNavigation } from "./app/navigation.js";
import { installQuality } from "./app/quality.js";
import { installReviewProgress } from "./app/review-progress.js";
import { installSelection } from "./app/selection.js";
import { installUpload } from "./app/upload.js";

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
if (!env.editEnabled) blockApi(window, env.apiUrl);
const osm = createClient(window.OSM);
const tab = tabId(window.sessionStorage);

guardEnvironment({ env: env.name, storage, osm });
osm.configure({ apiUrl: env.apiUrl });

const byId = id => document.getElementById(id);
const statusEl = byId("edit-status");

const ctx = {
  env,
  storage,
  osm,
  tab,
  meter,
  queue: createQueue({ storage, env: env.name }),
  skipped: createSkipList({ storage, env: env.name }),
  reviews: createReviewStore({ storage, env: env.name, ttlMs: env.reviewTtlMs }),
  looks: createLookTracker({ storage, env: env.name, history: env.lookHistory, tolerance: env.lookQuickTolerance }),
  pace: createPace({
    storage,
    env: env.name,
    windowMs: env.paceWindowMs,
    maxMeters: env.paceMaxMeters,
    blockMeters: env.paceBlockMeters,
    repeatMs: env.paceRepeatMs,
    cooldownMs: env.paceCooldownMs,
  }),
  state: {
    user: null,
    detail: { kind: "none" },
    plan: null,
    result: null,
    busy: false,
    form: { remark: "", sources: [], sourceOther: "", hashtags: env.defaultHashtags.join(" "), review: false },
  },
  map: null,
  mapReady: store.mapReady
    ? Promise.resolve(store.map)
    : new Promise(resolve => window.addEventListener("bpn:map-ready", e => resolve(e.detail), { once: true })),
  el: {
    auth: byId("edit-auth"),
    detail: byId("edit-detail"),
    queue: byId("edit-queue"),
    nav: byId("edit-nav"),
    meter: byId("edit-meter"),
    data: byId("edit-data"),
    dataInput: byId("edit-data-file"),
    dock: byId("edit-dock"),
    dockToggle: byId("edit-dock-toggle"),
    dockButtons: [...document.querySelectorAll("#edit-dock-position [data-dock]")],
    editBar: byId("edit-bar"),
    enterButton: byId("edit-enter"),
    pending: byId("edit-enter-pending"),
    exitButton: byId("edit-exit"),
    exitDialog: byId("edit-exit-dialog"),
    exitText: byId("edit-exit-text"),
  },
  showStatus: view => { statusEl.textContent = statusView(view, i18n); },
};

installLayers(ctx);
installCamera(ctx);
installReviewProgress(ctx);
installQuality(ctx);
installCandidateLoader(ctx);
installNavigation(ctx);
installKeyboard(ctx);
installSelection(ctx);
installUpload(ctx);
installAuthPanel(ctx);
installEditMode(ctx);
installDevDataPanel(ctx);
installEditHere(ctx);
installMeterPanel(ctx);

window.BPNEdit = Object.freeze({
  enter: ctx.enterEdit,
  exit: ctx.requestExit,
  isActive: () => ctx.active,
  devData: () => ctx.devDataActive(),
  apiStats: () => (meter ? meter.stats() : null),
  resetApiStats: () => meter && meter.reset(),
  canEdit: ctx.canEdit,
});

ctx.refreshAuth();
ctx.restoreModeOnLoad();

const map = await ctx.mapReady;
ctx.map = map;

if (ctx.active) ctx.foldSidePanel(ctx.el.dock.dataset.position);
addEditLayers(map);
installMapEvents(ctx, map);
ctx.setEditLayersVisible(ctx.active);
if (ctx.active) {
  ctx.applyEditMap();
  ctx.loadCandidates();
}
