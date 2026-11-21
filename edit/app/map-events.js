import { LAYER } from "./layers.js";

export function installMapEvents(ctx, map) {
  const { env } = ctx;
  let reviewFrame = 0;

  map.on("click", LAYER, (e) => {
    const id = Number(e.features?.[0]?.properties?.osm_id);
    if (Number.isFinite(id) && id > 0) ctx.selectWay(id);
  });
  map.on("mouseenter", LAYER, () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", LAYER, () => { map.getCanvas().style.cursor = ""; });
  map.on("moveend", () => {
    if (!ctx.active) return;
    ctx.scheduleCandidates();
    ctx.updateVisibility(true);
  });
  map.on("resize", ctx.updateVisibility);
  map.on("move", () => {
    if (!ctx.active || !env.reviewZoom || reviewFrame) return;
    reviewFrame = requestAnimationFrame(() => {
      reviewFrame = 0;
      if (ctx.noteReview()) ctx.renderDetail();
    });
  });
  map.on("style.load", () => {
    ctx.redrawCandidates();
    ctx.setEditLayersVisible(ctx.active);
    if (ctx.active) ctx.enforceEditLayers();
    ctx.syncQueuedState();
    ctx.showSideLines();
  });
  map.on("movestart", (e) => {
    const d = ctx.state.detail;
    if (e.originalEvent && d.kind === "way" && d.userFit) ctx.state.detail = { ...d, userFit: false };
  });
  window.addEventListener("bpn:basemap", () => {
    if (ctx.active && ctx.state.detail.kind === "way") ctx.renderDetail();
  });
}
