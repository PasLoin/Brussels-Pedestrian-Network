import { i18n } from "../../map/i18n.js";
import { DEV_SOURCE, MAX_FILE_BYTES, createDevDataStore, devDataFromFile } from "../dev-data.js";
import { devDataView } from "../panel.js";

const SIDEWALK_LAYER = "sidewalk-roads";

export function installDevDataPanel(ctx) {
  const { env } = ctx;
  const devStore = env.devData ? createDevDataStore(window.indexedDB, env.name) : null;
  const dataEl = ctx.el.data;
  const dataInput = ctx.el.dataInput;
  let devData = { active: null, loading: null, error: null };

  function renderDevData() {
    if (!devStore) return;
    dataEl.innerHTML = html`${devDataView(devData, i18n)}`;
  }

  function swapSidewalkSource(sourceSpec) {
    const map = ctx.map;
    const style = map.getStyle();
    const index = style.layers.findIndex(l => l.id === SIDEWALK_LAYER);
    if (index < 0) return;
    const layer = { ...style.layers[index] };
    delete layer["source-layer"];
    const before = style.layers[index + 1] ? style.layers[index + 1].id : undefined;
    map.removeLayer(SIDEWALK_LAYER);
    if (sourceSpec) {
      if (map.getSource(DEV_SOURCE)) map.getSource(DEV_SOURCE).setData(sourceSpec.data);
      else map.addSource(DEV_SOURCE, sourceSpec);
      map.addLayer({ ...layer, source: DEV_SOURCE }, before);
    } else {
      map.addLayer({ ...layer, source: "pedestrian", "source-layer": "sidewalk_roads" }, before);
      if (map.getSource(DEV_SOURCE)) map.removeSource(DEV_SOURCE);
    }
  }

  function applyDevData(data) {
    swapSidewalkSource({ type: "geojson", data: data.collection, promoteId: "osm_id" });
    devData = { active: data.meta, loading: null, error: null };
    renderDevData();
  }

  async function loadDevFile(file) {
    if (file.size > MAX_FILE_BYTES) {
      devData = { ...devData, error: "tooBig", size: Math.ceil(file.size / 1048576) };
      return renderDevData();
    }
    devData = { ...devData, loading: file.name, error: null };
    renderDevData();
    try {
      const data = devDataFromFile(await file.text(), file.name);
      await ctx.mapReady;
      await devStore.save(data);
      applyDevData(data);
    } catch (err) {
      devData = { ...devData, loading: null, error: err.code || "read" };
      renderDevData();
    }
  }

  async function resetDevData() {
    swapSidewalkSource(null);
    await devStore.clear();
    devData = { active: null, loading: null, error: null };
    renderDevData();
  }

  if (devStore) {
    renderDevData();
    dataEl.addEventListener("click", (e) => {
      const action = e.target.closest("[data-edit-action]")?.dataset.editAction;
      if (action === "data-load") dataInput.click();
      if (action === "data-reset") resetDevData();
    });
    dataInput.addEventListener("change", () => {
      const file = dataInput.files && dataInput.files[0];
      dataInput.value = "";
      if (file) loadDevFile(file);
    });
    Promise.all([devStore.load(), ctx.mapReady]).then(([saved]) => {
      if (saved && saved.collection && !devData.active) applyDevData(saved);
    });
  }

  Object.assign(ctx, { devDataActive: () => devData.active });
}
