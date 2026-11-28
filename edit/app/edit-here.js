import { store } from "../../map/store.js";
import { bboxOf } from "../geo.js";
import { linesOf, matchCandidate } from "../match.js";
import { matchesWhitelist } from "../whitelist.js";

export function installEditHere(ctx) {
  const { env } = ctx;

  function tileLines(id) {
    const lines = [];
    if (store.lastClicked && Number(store.lastClicked.id) === id) lines.push(...linesOf(store.lastClicked.geometry));
    try {
      const parts = ctx.map.querySourceFeatures("pedestrian", { sourceLayer: "sidewalk_roads", filter: ["==", ["to-number", ["get", "osm_id"]], id] });
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
    ctx.enterEdit();
    if (window.BPNMap) window.BPNMap.closePopups();
    await ctx.mapReady;
    if (env.candidates === "pmtiles" || ctx.devDataActive()) return ctx.selectWay(id);
    const lines = tileLines(id);
    await ctx.loadCandidates(lines.length ? { box: paddedBox(lines), around: true } : ctx.currentRequest());
    const twins = ctx.sourceTwins(id);
    if (twins.length === 1) return ctx.selectWay(twins[0]);
    if (twins.length > 1) return ctx.showStatus({ kind: "splitOnDev", count: twins.length });
    if (!lines.length) return ctx.showStatus({ kind: "noMatch" });
    const best = matchCandidate(lines, ctx.liveFeatures.values());
    if (!best) return ctx.showStatus({ kind: "noMatch" });
    ctx.selectWay(best.feature.properties.osm_id);
  }

  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-bpn-edit-way]");
    if (!button) return;
    const id = Number(button.dataset.bpnEditWay);
    if (!Number.isFinite(id) || id <= 0) return;
    e.preventDefault();
    editWay(id);
  });

  Object.assign(ctx, { canEdit: p => Boolean(env.editEnabled && p && p.sw === "unknown" && matchesWhitelist({ highway: p.highway })) });
}
