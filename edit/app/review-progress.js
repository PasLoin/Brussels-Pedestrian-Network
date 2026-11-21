import { coveredIndexes, samplesAlong } from "../review.js";
import { FIT_DURATION_MS, VISIBLE_MARGIN_PX } from "./camera.js";

export function installReviewProgress(ctx) {
  const { env, reviews } = ctx;
  let reviewSamples = [];
  let reviewSeen = new Set();

  function startReview(coords) {
    reviewSamples = env.reviewZoom ? samplesAlong(coords, env.reviewStepM) : [];
    reviewSeen = new Set();
  }

  function reviewState(done) {
    if (!env.reviewZoom) return null;
    const total = reviewSamples.length || 1;
    return { zoom: env.reviewZoom, percent: done ? 100 : Math.floor((100 * reviewSeen.size) / total), done };
  }

  function noteReview() {
    const map = ctx.map;
    let d = ctx.state.detail;
    if (!map || d.kind !== "way" || !d.editable || d.fitting) return false;
    let changed = false;
    if (!d.seenWhole && (d.visible || ctx.wholeWayVisible(d.coords))) {
      reviews.markWhole(d.way.id, d.way.version);
      d = { ...d, seenWhole: true };
      changed = true;
    }
    if (d.review && !d.review.done && map.getZoom() >= env.reviewZoom - 1e-6) {
      const points = reviewSamples.map(c => map.project(c));
      for (const i of coveredIndexes(points, ctx.viewArea().free, VISIBLE_MARGIN_PX)) reviewSeen.add(i);
      const done = reviewSeen.size >= reviewSamples.length;
      if (done) reviews.markDetail(d.way.id, d.way.version);
      const review = reviewState(done);
      if (review.percent !== d.review.percent || done) {
        d = { ...d, review };
        changed = true;
      }
    }
    if (changed) ctx.state.detail = d;
    return changed;
  }

  function goToUnseenPart() {
    const map = ctx.map;
    const d = ctx.state.detail;
    if (!map || d.kind !== "way" || !d.review) return;
    const index = reviewSamples.findIndex((_, i) => !reviewSeen.has(i));
    if (index < 0) return;
    const { canvas, free } = ctx.viewArea();
    const offset = [(free.left + free.right) / 2 - canvas.width / 2, (free.top + free.bottom) / 2 - canvas.height / 2];
    map.easeTo({ center: reviewSamples[index], zoom: Math.max(map.getZoom(), env.reviewZoom), offset, duration: FIT_DURATION_MS });
  }

  Object.assign(ctx, { startReview, reviewState, noteReview, goToUnseenPart });
}
