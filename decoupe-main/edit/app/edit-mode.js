import { i18n } from "../../map/i18n.js";
import { store } from "../../map/store.js";
import { DEV_SOURCE } from "../dev-data.js";
import { DOCK_KEY, DOCK_POSITIONS, readDockPosition } from "../viewport.js";

const GOVERNED_SOURCES = ["pedestrian", DEV_SOURCE];

export function installEditMode(ctx) {
  const { env, storage, queue, state } = ctx;
  const { dock, dockToggle, dockButtons, editBar, enterButton, exitButton, exitDialog, exitText } = ctx.el;
  const MODE_KEY = `bpn.editing.${env.name}`;
  const PREV_BASEMAP_KEY = `bpn.editPrevBasemap.${env.name}`;
  let headerWasOpen = false;
  let layerSnapshot = null;
  ctx.active = false;
  store.editing = false;

  function foldSidePanel(position) {
    if (position === "left" && window.BPNMap) window.BPNMap.setHeaderOpen(false);
    if (position === "right" && window.BPNMap) window.BPNMap.setLegendOpen(false);
  }

  function afterLayoutChange() {
    const d = state.detail;
    if (!ctx.map || d.kind !== "way") return;
    const view = ctx.bringWholeWayIntoView(d);
    if (view === "moving") {
      ctx.applyView(view);
      ctx.renderDetail();
    } else {
      ctx.updateVisibility(true);
    }
  }

  function setDockPosition(position, persist) {
    const value = DOCK_POSITIONS.includes(position) ? position : "right";
    dock.dataset.position = value;
    for (const button of dockButtons) button.setAttribute("aria-pressed", button.dataset.dock === value ? "true" : "false");
    if (persist) {
      try { storage.setItem(DOCK_KEY, value); } catch {}
    }
    if (ctx.active) foldSidePanel(value);
    if (ctx.map && state.detail.kind === "way") afterLayoutChange();
  }

  function setDockOpen(open) {
    dock.classList.toggle("open", open);
    dock.classList.toggle("closed", !open);
    dockToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function enforceEditLayers() {
    const map = ctx.map;
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
    if (!ctx.map || !window.BPNMap) return;
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
    const map = ctx.map;
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

  function enterEdit() {
    if (ctx.active || !env.editEnabled) return;
    ctx.active = true;
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
    ctx.startQualityTick();
    if (ctx.map) {
      applyEditMap();
      ctx.setEditLayersVisible(true);
      ctx.loadCandidates();
    }
  }

  function leaveEdit() {
    if (!ctx.active) return;
    ctx.active = false;
    store.editing = false;
    try { window.sessionStorage.removeItem(MODE_KEY); } catch {}
    ctx.stopCandidates();
    ctx.deselect();
    ctx.stopQualityTick();
    ctx.setEditLayersVisible(false);
    restoreEditMap();
    document.body.classList.remove("is-editing");
    editBar.hidden = true;
    dock.hidden = true;
    if (headerWasOpen && window.BPNMap) window.BPNMap.setHeaderOpen(true);
    enterButton.focus();
  }

  function requestExit() {
    if (!ctx.active || state.busy) return;
    const count = queue.size();
    if (!count) return leaveEdit();
    exitText.textContent = i18n.t("edit.mode.exitText", { count });
    exitDialog.showModal();
  }

  function restoreModeOnLoad() {
    enterButton.hidden = !env.editEnabled;
    try {
      if (!env.editEnabled) window.sessionStorage.removeItem(MODE_KEY);
      else if (window.sessionStorage.getItem(MODE_KEY) === "1") enterEdit();
    } catch {}
  }

  for (const button of dockButtons) button.addEventListener("click", () => setDockPosition(button.dataset.dock, true));
  setDockPosition(readDockPosition(storage), false);
  dockToggle.addEventListener("click", () => {
    setDockOpen(!dock.classList.contains("open"));
    afterLayoutChange();
  });
  exitDialog.addEventListener("click", (e) => {
    const choice = e.target.closest("[data-exit-choice]")?.dataset.exitChoice;
    if (!choice) return;
    exitDialog.close();
    if (choice === "discard") ctx.discardQueue();
    if (choice === "keep" || choice === "discard") leaveEdit();
  });
  enterButton.addEventListener("click", enterEdit);
  exitButton.addEventListener("click", requestExit);

  Object.assign(ctx, { enterEdit, requestExit, applyEditMap, enforceEditLayers, setDockOpen, foldSidePanel, restoreModeOnLoad });
}
