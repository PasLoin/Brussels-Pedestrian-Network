import { i18n } from "../../map/i18n.js";
import { EMPTY_COLLECTION, boundsBox, boxString, boxWithin, candidateRequest, candidateWindow, candidatesFromMapData, countInBox, mergeCandidates, mergeSourceIds, sourceIds } from "../candidates.js";
import { errorMessage } from "../errors.js";
import { SOURCE } from "./layers.js";

const WIDER_SEARCH = [2, 4];

export function installCandidateLoader(ctx) {
  const { env, osm, queue, skipped } = ctx;
  const liveFeatures = new Map();
  let sourceIndex = new Map();
  let loadedBoxes = [];
  let controller = null;
  let timer = null;
  let widening = null;
  let candidatesBlocked = null;

  function syncQueuedState() {
    const map = ctx.map;
    if (!map || !map.getSource(SOURCE)) return;
    for (const id of liveFeatures.keys()) map.setFeatureState({ source: SOURCE, id }, { queued: queue.has(id), skipped: skipped.has(id) });
  }

  function redrawCandidates() {
    ctx.map.getSource(SOURCE)?.setData({ type: "FeatureCollection", features: [...liveFeatures.values()] });
  }

  function setCandidates(features) {
    liveFeatures.clear();
    for (const [id, f] of features) liveFeatures.set(id, f);
    redrawCandidates();
    syncQueuedState();
  }

  function clearCandidates() {
    loadedBoxes = [];
    liveFeatures.clear();
    ctx.map.getSource(SOURCE)?.setData(EMPTY_COLLECTION);
  }

  function candidateFocus() {
    const d = ctx.state.detail;
    return d.kind === "way" && d.bbox ? d.bbox : null;
  }

  function currentRequest(focus = candidateFocus()) {
    const map = ctx.map;
    const canvas = { width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight };
    const center = map.getCenter();
    return candidateRequest({ zoom: map.getZoom(), bounds: map.getBounds(), center: [center.lng, center.lat], canvas, focus, settings: env });
  }

  function searchWider(wayId) {
    const focus = candidateFocus();
    if (widening || !focus) return false;
    widening = (async () => {
      const map = ctx.map;
      for (const scale of WIDER_SEARCH) {
        const center = map.getCenter();
        const box = candidateWindow({ center: [center.lng, center.lat], canvas: { width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight }, focus, settings: env, scale });
        if (loadedBoxes.some(b => boxWithin(box, b))) continue;
        await loadCandidates({ box, around: true });
        if (ctx.state.detail.kind !== "way" || ctx.state.detail.way.id !== wayId) return;
        if (ctx.selectNext(false)) return;
      }
      if (ctx.state.detail.kind === "way" && ctx.state.detail.way.id === wayId) ctx.showNavHint(i18n.t("edit.nav.none"));
    })().finally(() => { widening = null; });
    return true;
  }

  function loadAroundSelection() {
    const focus = candidateFocus();
    if (!ctx.map || !focus) return;
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
        ctx.renderNav();
        return ctx.showStatus({ kind: "zoom", minZoom: env.candidateFloorZoom, kept: liveFeatures.size });
      }
      clearCandidates();
      ctx.renderNav();
      return ctx.showStatus({ kind: request.blocked, minZoom: env.candidateFloorZoom });
    }
    const current = new AbortController();
    controller = current;
    ctx.showStatus({ kind: "loading" });
    try {
      const features = await osm.getMapData(boxString(request.box), { signal: current.signal });
      if (current.signal.aborted) return;
      sourceIndex = mergeSourceIds(sourceIndex, sourceIds(features));
      setCandidates(mergeCandidates(liveFeatures, candidatesFromMapData(features), request.box));
      loadedBoxes = [request.box, ...loadedBoxes].slice(0, 20);
      ctx.showStatus({ kind: "ready", count: countInBox(liveFeatures.values(), boundsBox(ctx.map.getBounds())) });
      ctx.renderNav();
    } catch (err) {
      if (current.signal.aborted) return;
      clearCandidates();
      ctx.showStatus({ kind: "error", message: errorMessage(err, i18n.t) });
      ctx.renderNav();
    }
  }

  function scheduleCandidates() {
    clearTimeout(timer);
    timer = setTimeout(loadCandidates, 300);
  }

  function stopCandidates() {
    clearTimeout(timer);
    if (controller) controller.abort();
    controller = null;
  }

  Object.assign(ctx, {
    liveFeatures,
    syncQueuedState,
    redrawCandidates,
    currentRequest,
    searchWider,
    loadAroundSelection,
    loadCandidates,
    scheduleCandidates,
    stopCandidates,
    isWidening: () => Boolean(widening),
    candidatesBlocked: () => candidatesBlocked,
    sourceTwins: id => [...(sourceIndex.get(id) || [])],
  });
}
