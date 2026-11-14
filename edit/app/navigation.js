import { i18n } from "../../map/i18n.js";
import { nextCandidate } from "../next.js";
import { navView } from "../panel.js";

export function installNavigation(ctx) {
  const { env, queue, skipped } = ctx;
  const navEl = ctx.el.nav;
  const visited = new Set();
  let navHint = "";

  function renderNav() {
    navEl.innerHTML = html`${navView({
      candidates: ctx.liveFeatures.size,
      skipped: skipped.size(),
      selected: ctx.state.detail.kind === "way",
      hint: navHint,
    }, i18n)}`;
  }

  function showNavHint(text) {
    navHint = text;
    renderNav();
  }

  function selectNext(widen = true) {
    const map = ctx.map;
    if (!map) return false;
    const d = ctx.state.detail;
    const current = d.kind === "way" ? d.way.id : null;
    const here = map.getCenter();
    const from = current && d.bbox
      ? [(d.bbox[0] + d.bbox[2]) / 2, (d.bbox[1] + d.bbox[3]) / 2]
      : [here.lng, here.lat];
    const pool = [...ctx.liveFeatures.values()];
    const base = new Set([...skipped.list(), ...queue.list().map(i => i.wayId)]);
    if (current) base.add(current);
    let next = nextCandidate(pool, from, new Set([...base, ...visited]));
    if (!next && visited.size) {
      visited.clear();
      next = nextCandidate(pool, from, base);
    }
    if (!next) {
      const searching = widen && current !== null && ctx.searchWider(current);
      navHint = searching ? i18n.t("edit.nav.searching") : ctx.candidatesBlocked() === "zoom" ? i18n.t("edit.status.zoomIn", { zoom: env.candidateFloorZoom }) : i18n.t("edit.nav.none");
      renderNav();
      return false;
    }
    navHint = "";
    ctx.selectWay(next.properties.osm_id);
    return true;
  }

  function skipSelected() {
    const d = ctx.state.detail;
    if (d.kind !== "way") return;
    skipped.add(d.way.id);
    if (queue.has(d.way.id)) {
      queue.remove(d.way.id);
      ctx.state.plan = null;
      ctx.renderQueue();
    }
    ctx.syncQueuedState();
    if (!selectNext()) ctx.deselect();
  }

  navEl.addEventListener("click", (e) => {
    const action = e.target.closest("[data-edit-action]")?.dataset.editAction;
    if (action === "next") selectNext();
    else if (action === "reset-skipped") {
      skipped.clear();
      visited.clear();
      navHint = "";
      ctx.syncQueuedState();
      renderNav();
    }
  });

  Object.assign(ctx, { renderNav, showNavHint, selectNext, skipSelected, markVisited: id => visited.add(id) });
}
