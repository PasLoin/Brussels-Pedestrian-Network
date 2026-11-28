import { editLock } from "../panel.js";

export function installQuality(ctx) {
  const { env, pace, looks } = ctx;
  let qualityTick = null;
  let lastTick = 0;

  function basemapAllowed() {
    return Boolean(window.BPNMap) && env.editBasemaps.includes(window.BPNMap.currentBasemap());
  }

  function qualityNow() {
    const status = pace.status();
    return { basemapOk: basemapAllowed(), tooFast: status.tooFast, paceLeftMs: status.cooldownLeftMs, lookMode: env.lookMode, lookHasty: looks.hasty() };
  }

  function tickQuality() {
    const t = Date.now();
    const elapsed = lastTick ? t - lastTick : 0;
    lastTick = t;
    const d = ctx.state.detail;
    if (!ctx.active || d.kind !== "way" || !d.editable) return;
    const before = editLock(d);
    const shown = [Math.ceil((d.lookLeftMs || 0) / 1000), Math.ceil((d.paceLeftMs || 0) / 1000), d.basemapOk, d.tooFast].join("|");
    const quality = qualityNow();
    let lookLeftMs = d.lookLeftMs || 0;
    if (lookLeftMs > 0 && !d.fitting && quality.basemapOk && document.visibilityState === "visible") lookLeftMs = Math.max(0, lookLeftMs - elapsed);
    ctx.state.detail = { ...d, ...quality, lookLeftMs };
    const after = [Math.ceil(lookLeftMs / 1000), Math.ceil(quality.paceLeftMs / 1000), quality.basemapOk, quality.tooFast].join("|");
    if (after !== shown || editLock(ctx.state.detail) !== before) ctx.renderDetail();
  }

  function startQualityTick() {
    lastTick = 0;
    qualityTick = setInterval(tickQuality, 250);
  }

  function stopQualityTick() {
    clearInterval(qualityTick);
    qualityTick = null;
  }

  function recordChoice(detail) {
    pace.record(detail.lengthM);
    looks.record(detail.lookLeftMs > 0);
  }

  Object.assign(ctx, { qualityNow, startQualityTick, stopQualityTick, recordChoice });
}
