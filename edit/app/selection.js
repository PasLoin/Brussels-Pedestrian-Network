import { i18n } from "../../map/i18n.js";
import { errorMessage } from "../errors.js";
import { bboxOf, lineLengthM } from "../geo.js";
import { chooseValue, choiceFromIntent, completeChoice, makeIntent, switchMode } from "../intent.js";
import { lookTimeMs } from "../look.js";
import { queueRoom } from "../osm.js";
import { detailView, editLock } from "../panel.js";
import { isEditableCandidate } from "../whitelist.js";

export function installSelection(ctx) {
  const { env, osm, queue, skipped, reviews } = ctx;
  const detailEl = ctx.el.detail;

  function roomFor(detail) {
    return queueRoom(queue.list(), { wayId: detail.way.id, bbox: detail.bbox }, env);
  }

  function renderDetail() {
    const d = ctx.state.detail;
    if (d.kind === "way" && d.editable) ctx.state.detail = { ...d, ...ctx.qualityNow(), room: roomFor(d) };
    detailEl.innerHTML = html`${detailView(ctx.state.detail, i18n, env.webUrl, env)}`;
    ctx.showSideLines();
    ctx.redrawSelection();
  }

  function editBlocked() {
    const d = ctx.state.detail;
    return d.kind !== "way" || !d.editable || Boolean(editLock(d));
  }

  function queueChoice() {
    const d = ctx.state.detail;
    const sides = completeChoice(d.choice);
    if (!sides || editBlocked()) return false;
    const intent = makeIntent({ way: d.way, left: sides.left, right: sides.right, bbox: d.bbox, lengthM: d.lengthM, coords: d.coords });
    if (!d.queued) ctx.recordChoice(d);
    queue.put(intent);
    skipped.remove(intent.wayId);
    ctx.state.plan = null;
    ctx.state.result = null;
    ctx.state.detail = { ...d, queued: intent };
    ctx.renderQueue();
    ctx.syncQueuedState();
    return true;
  }

  function unqueueSelected(choice) {
    const d = ctx.state.detail;
    queue.remove(d.way.id);
    ctx.state.plan = null;
    ctx.state.detail = { ...d, queued: null, choice };
    ctx.renderQueue();
    ctx.syncQueuedState();
  }

  function applyValue(side, value) {
    if (editBlocked()) return;
    const d = ctx.state.detail;
    ctx.state.detail = { ...d, choice: chooseValue(d.choice, side, value) };
    if (env.autoQueue && completeChoice(ctx.state.detail.choice)) {
      if (queueChoice() && env.autoAdvance && ctx.selectNext()) return;
    } else if (env.autoQueue && d.queued) {
      unqueueSelected(ctx.state.detail.choice);
    }
    renderDetail();
  }

  function deselect() {
    ctx.clearPendingKeys();
    ctx.state.detail = { kind: "none" };
    ctx.showSelection(null);
    renderDetail();
    ctx.renderNav();
  }

  function lockSignature(d) {
    return [d.visible, d.fitting, d.seenWhole, d.review && d.review.percent, d.review && d.review.done].join("|");
  }

  function updateVisibility(settled = false) {
    const d = ctx.state.detail;
    if (d.kind !== "way" || !d.editable) return;
    if (d.fitting && !settled && ctx.map.isMoving()) return;
    const visible = ctx.wholeWayVisible(d.coords) || Boolean(d.userFit && d.fitting && settled);
    const before = lockSignature(d);
    ctx.state.detail = { ...d, visible, fitting: false, userFit: false };
    ctx.noteReview();
    if (lockSignature(ctx.state.detail) === before) return;
    renderDetail();
    if (!editLock(ctx.state.detail)) ctx.replayPendingKeys();
    else ctx.clearPendingKeys();
  }

  async function selectWay(id) {
    ctx.clearPendingKeys();
    const known = ctx.liveFeatures.get(id);
    ctx.showSelection(known ? known.geometry.coordinates : null);
    ctx.setDockOpen(true);
    ctx.markVisited(id);
    ctx.state.detail = { kind: "loading" };
    renderDetail();
    try {
      const elements = await osm.getFeature("way", id, true);
      const way = elements.find(f => f.type === "way" && f.id === id);
      const nodes = new Map(elements.filter(f => f.type === "node").map(n => [n.id, [n.lon, n.lat]]));
      const coords = way.nodes.map(n => nodes.get(n));
      if (coords.some(c => !c)) throw new Error("incomplete way");
      ctx.showSelection(coords);
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
        ...ctx.qualityNow(),
      };
      ctx.startReview(coords);
      detail.seenWhole = reviews.seenWhole(id, way.version);
      detail.review = ctx.reviewState(reviews.seenDetail(id, way.version));
      const view = ctx.frameWay(detail);
      ctx.state.detail = { ...detail, fitting: view === "moving", visible: view === "visible" };
      ctx.noteReview();
    } catch (err) {
      const gone = err && (err.cause === 404 || err.cause === 410);
      ctx.state.detail = gone ? { kind: "gone", wayId: id } : { kind: "error", message: errorMessage(err, i18n.t) };
      if (gone) ctx.showSelection(null);
    }
    renderDetail();
    ctx.renderNav();
    (detailEl.querySelector(".edit-form") || detailEl).scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (ctx.state.detail.kind === "way" && !ctx.state.detail.fitting) ctx.loadAroundSelection();
  }

  detailEl.addEventListener("click", (e) => {
    const button = e.target.closest("[data-edit-action]");
    const d = ctx.state.detail;
    if (!button || d.kind !== "way" || !d.editable) return;
    const action = button.dataset.editAction;
    if (action === "basemap") {
      if (window.BPNMap) window.BPNMap.setBasemap(env.editBasemaps[0]);
      return;
    }
    if (action === "fit") {
      ctx.applyView(ctx.bringWholeWayIntoView(d, true));
      ctx.state.detail = { ...ctx.state.detail, userFit: ctx.state.detail.fitting };
      renderDetail();
      return;
    } else if (action === "plan") {
      return ctx.onPlan();
    } else if (action === "review-next") {
      return ctx.goToUnseenPart();
    } else if (action === "choose") {
      return applyValue(button.dataset.side, button.dataset.value);
    } else if (action === "skip") {
      return ctx.skipSelected();
    } else if (action === "next") {
      ctx.selectNext();
      return;
    } else if (action === "mode") {
      if (editBlocked()) return;
      ctx.state.detail = { ...d, choice: switchMode(d.choice, button.dataset.mode) };
    } else if (action === "queue") {
      if (queueChoice() && env.autoAdvance && ctx.selectNext()) return;
    } else if (action === "unqueue") {
      unqueueSelected({ mode: d.choice.mode, both: "", left: "", right: "" });
    } else {
      return;
    }
    renderDetail();
  });

  Object.assign(ctx, { renderDetail, editBlocked, applyValue, deselect, updateVisibility, selectWay });
}
