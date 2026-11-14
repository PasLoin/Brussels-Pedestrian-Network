import { boxOf, boxVisible, fitPadding, freeRect } from "../viewport.js";

export const FIT_MARGIN_PX = 40;
export const VISIBLE_MARGIN_PX = 4;
export const FIT_DURATION_MS = 250;

export function installCamera(ctx) {
  const { env } = ctx;
  let settleTimer = null;

  function viewArea() {
    const map = ctx.map;
    const dock = ctx.el.dock;
    const canvas = { width: map.getCanvas().clientWidth, height: map.getCanvas().clientHeight };
    const narrow = window.matchMedia("(max-width: 600px)").matches;
    const rect = dock.classList.contains("open") ? dock.getBoundingClientRect() : null;
    return { canvas, free: freeRect(canvas, rect, narrow ? "bottom" : dock.dataset.position) };
  }

  function wayBox(coords) {
    return boxOf(coords.map(c => ctx.map.project(c)));
  }

  function wholeWayVisible(coords, margin = VISIBLE_MARGIN_PX) {
    if (!ctx.map || !coords || !coords.length) return false;
    return boxVisible(viewArea().free, wayBox(coords), margin);
  }

  function anyPartVisible(coords) {
    const { free } = viewArea();
    return coords.some(c => {
      const p = ctx.map.project(c);
      return p.x >= free.left && p.x <= free.right && p.y >= free.top && p.y <= free.bottom;
    });
  }

  function cameraFor(d, maxZoom) {
    const { canvas, free } = viewArea();
    return ctx.map.cameraForBounds([[d.bbox[0], d.bbox[1]], [d.bbox[2], d.bbox[3]]], {
      padding: fitPadding(canvas, free, FIT_MARGIN_PX),
      bearing: ctx.map.getBearing(),
      maxZoom,
    });
  }

  function moveTo(camera) {
    const map = ctx.map;
    map.easeTo({ ...camera, bearing: map.getBearing(), pitch: map.getPitch(), duration: FIT_DURATION_MS });
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => ctx.updateVisibility(true), FIT_DURATION_MS + 150);
    return "moving";
  }

  function frameWay(d) {
    if (!ctx.map || d.kind !== "way") return "hidden";
    const camera = cameraFor(d, env.fitMaxZoom);
    const zoom = ctx.map.getZoom();
    const visible = wholeWayVisible(d.coords, FIT_MARGIN_PX);
    if (!camera) return visible ? "visible" : "hidden";
    if (visible && zoom >= Math.min(camera.zoom, env.fitMinZoom) - 1e-6) return "visible";
    if (d.seenWhole && camera.zoom < zoom) return anyPartVisible(d.coords) ? "partial" : bringWholeWayIntoView(d);
    return moveTo(camera);
  }

  function bringWholeWayIntoView(d, force = false) {
    if (!ctx.map || d.kind !== "way") return "hidden";
    if (!force && wholeWayVisible(d.coords, FIT_MARGIN_PX)) return "visible";
    const camera = cameraFor(d, ctx.map.getZoom());
    if (!camera) return wholeWayVisible(d.coords) ? "visible" : "hidden";
    return moveTo(camera);
  }

  function applyView(view) {
    const d = ctx.state.detail;
    if (d.kind !== "way") return;
    ctx.state.detail = { ...d, fitting: view === "moving", visible: view === "visible" };
  }

  Object.assign(ctx, { viewArea, wholeWayVisible, anyPartVisible, frameWay, bringWholeWayIntoView, applyView });
}
