import { i18n } from "./i18n.js";
import { store } from "./store.js";
import { adaptZinnekeStyle, buildWmsStyle, keepOverlays, mergeLibertyStyle, wmsTileUrl } from "./basemap-styles.js";
import { BASE_STYLE_OVERRIDES } from "./layers.js";

const LIBERTY_URL = "https://tiles.openfreemap.org/styles/liberty";
const ZINNEKE_BASE = "https://pasloin.github.io/ZinnekeTiles/";
const URBIS_GRID_WMS = "https://geoservices-urbis.irisnet.be/geoserver/urbisgrid/wms";
const URBIS_TOPO_WMS = "https://geoservices-urbis.irisnet.be/geoserver/urbistopo/wms";
const URBIS_ATTRIBUTION = '<a href="https://datastore.brussels/web/urbis-download" target="_blank" rel="noopener">UrbIS</a> © <a href="https://paradigm.brussels" target="_blank" rel="noopener">Paradigm</a>';
const URBIS_THUMB_BBOX = "484351,6594098,484685,6594433";

const LIBERTY_THUMB = "data:image/svg+xml," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">' +
  '<rect width="80" height="80" fill="#f2efe9"/>' +
  '<path d="M48 0h32v30c-12 4-22 0-32-8z" fill="#d7ebc9"/>' +
  '<path d="M0 58c14-6 26 2 30 22H0z" fill="#d7ebc9"/>' +
  '<g fill="#e3ddd4"><rect x="6" y="6" width="16" height="10"/><rect x="28" y="8" width="12" height="14"/><rect x="8" y="26" width="14" height="16"/><rect x="40" y="38" width="16" height="12"/><rect x="60" y="40" width="14" height="18"/><rect x="40" y="60" width="18" height="14"/></g>' +
  '<g fill="none" stroke="#aaaaaa" stroke-width="5"><path d="M0 22h80M25 0v80M0 52h80M58 0l-6 80"/></g>' +
  '<g fill="none" stroke="#d5d5d5" stroke-width="3"><path d="M0 22h80M25 0v80M0 52h80M58 0l-6 80"/></g>' +
  '<path d="M0 34 80 30" stroke="#a0c8f0" stroke-width="4"/>' +
  '</svg>'
);

export const BASEMAPS = [
  { id: "liberty", label: "Liberty", title: "OpenFreeMap Liberty", osmName: "OpenFreeMap Liberty", thumb: LIBERTY_THUMB },
  {
    id: "zinneke", label: "Zinneke", title: "ZinnekeTiles", osmName: "ZinnekeTiles",
    thumb: ZINNEKE_BASE + "assets/img/basemap-zinneke.png",
    url: ZINNEKE_BASE + "style.json",
    hideSources: ["public_transport", "poi"],
    hideLayers: ["railway-tram*", "railway-subway*", "railway-tunnel-tram", "railway-tunnel-subway", "man_made-tunnel-*"]
  },
  {
    id: "nb", label: i18n.t("basemap.blackWhite.label"), title: i18n.t("basemap.blackWhite.title"), osmName: "ZinnekeTiles NB",
    thumb: ZINNEKE_BASE + "assets/img/basemap-nb.png",
    url: ZINNEKE_BASE + "style.nb.json",
    hideLayers: ["man_made-tunnel-*"]
  },
  {
    id: "urbis-ortho", label: i18n.t("basemap.urbisOrtho.label"), title: i18n.t("basemap.urbisOrtho.title"), osmName: "UrbIS Ortho",
    thumb: wmsTileUrl(URBIS_GRID_WMS, "Ortho", 160).replace("{bbox-epsg-3857}", URBIS_THUMB_BBOX),
    attribution: URBIS_ATTRIBUTION,
    bounds: [4.23, 50.75, 4.49, 50.92],
    wms: [
      { id: "urbis-ortho", endpoint: URBIS_GRID_WMS, layer: "Ortho" },
      { id: "urbis-topolines", endpoint: URBIS_TOPO_WMS, layer: "TopoLines" }
    ]
  }
];

export const BASEMAP_STORAGE_KEY = "bpn-basemap";
const basemapStyleCache = {};
let currentBasemap = "liberty";
let basemapRequest = 0;

async function loadLibertyStyle() {
  let libertyStyle;
  try {
    const res = await fetch(LIBERTY_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    libertyStyle = await res.json();
  } catch (err) {
    console.warn("Style Liberty indisponible, chargement direct :", err);
    return LIBERTY_URL;
  }
  let localStyle = null;
  try {
    localStyle = await (await fetch(i18n.dataUrl("style.json"))).json();
  } catch (err) {
    console.warn("style.json local indisponible :", err);
  }
  return mergeLibertyStyle(libertyStyle, localStyle, BASE_STYLE_OVERRIDES);
}

async function loadZinnekeStyle(bm) {
  const res = await fetch(bm.url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return adaptZinnekeStyle(await res.json(), bm);
}

async function loadBasemapStyle(bm) {
  if (basemapStyleCache[bm.id]) return basemapStyleCache[bm.id];
  const style = bm.wms ? buildWmsStyle(bm) : bm.url ? await loadZinnekeStyle(bm) : await loadLibertyStyle();
  basemapStyleCache[bm.id] = style;
  return style;
}

async function rasterizeSvg(svgText, size, pixelRatio) {
  const blobUrl = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image();
    await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = blobUrl; });
    const px = Math.round(size * pixelRatio);
    const canvas = document.createElement("canvas");
    canvas.width = px; canvas.height = px;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, px, px);
    return ctx.getImageData(0, 0, px, px);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

export async function loadBasemapPatterns(map, style, baseUrl) {
  if (!style || typeof style !== "object") return;
  const patterns = (style.metadata || {})["brussels:patterns"] || {};
  await Promise.all(Object.entries(patterns).map(async ([name, cfg]) => {
    if (!cfg || !cfg.file || map.hasImage(name)) return;
    try {
      const res = await fetch(new URL(cfg.file, baseUrl).href);
      if (!res.ok) return;
      let svg = await res.text();
      for (const [from, to] of Object.entries(cfg.replace || {})) svg = svg.split(from).join(to);
      const data = await rasterizeSvg(svg, cfg.size || 32, 2);
      if (!map.hasImage(name)) map.addImage(name, data, { pixelRatio: 2 });
    } catch (err) {
      console.warn(`Motif ${name} indisponible :`, err);
    }
  }));
  map.triggerRepaint();
}

function renderBasemapMenu() {
  const menu = document.getElementById("basemap-menu");
  menu.replaceChildren(...BASEMAPS.map(bm => {
    const active = bm.id === currentBasemap;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "basemap-option" + (active ? " active" : "");
    btn.dataset.id = bm.id;
    btn.title = bm.title;
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", active ? "true" : "false");
    const img = document.createElement("img");
    img.src = bm.thumb;
    img.alt = "";
    img.loading = "lazy";
    const span = document.createElement("span");
    span.textContent = bm.label;
    btn.append(img, span);
    btn.addEventListener("click", () => setBasemap(bm.id));
    return btn;
  }));
}

export async function setBasemap(id) {
  const bm = BASEMAPS.find(b => b.id === id);
  if (!bm || id === currentBasemap || !store.map || !store.map.getSource("pedestrian")) return;
  const request = ++basemapRequest;
  const btn = document.querySelector(`.basemap-option[data-id="${id}"]`);
  if (btn) btn.classList.add("loading");
  try {
    const style = await loadBasemapStyle(bm);
    if (request !== basemapRequest) return;
    currentBasemap = id;
    store.imageryUsed.add(bm.osmName);
    if (bm.url) store.map.once("style.load", () => loadBasemapPatterns(store.map, style, bm.url));
    store.map.setStyle(style, { diff: false, transformStyle: keepOverlays });
    try { localStorage.setItem(BASEMAP_STORAGE_KEY, id); } catch {}
    renderBasemapMenu();
  } catch (err) {
    console.error("Fond de carte indisponible :", err);
    if (btn) btn.classList.remove("loading");
  }
}

export function setupBasemapControl() {
  const control = document.getElementById("basemap-control");
  const toggle = document.getElementById("basemap-toggle");
  const setOpen = open => {
    control.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };
  toggle.addEventListener("click", e => {
    e.stopPropagation();
    setOpen(!control.classList.contains("open"));
  });
  document.addEventListener("click", e => {
    if (!control.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && control.classList.contains("open")) {
      setOpen(false);
      toggle.focus();
    }
  });
  renderBasemapMenu();
}

export function savedBasemap() {
  let saved = null;
  try { saved = localStorage.getItem(BASEMAP_STORAGE_KEY); } catch {}
  return BASEMAPS.find(b => b.id === saved) || BASEMAPS[0];
}

export async function loadInitialBasemap() {
  let bm = savedBasemap();
  let style;
  try {
    style = await loadBasemapStyle(bm);
  } catch (err) {
    console.warn("Fond de carte enregistré indisponible :", err);
    bm = BASEMAPS[0];
    style = await loadBasemapStyle(bm);
  }
  currentBasemap = bm.id;
  store.imageryUsed.add(bm.osmName);
  return { bm, style };
}
