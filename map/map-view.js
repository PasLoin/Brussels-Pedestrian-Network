import { i18n } from "./i18n.js";
import { store } from "./store.js";
import { pedestrianSource } from "./basemap-styles.js";
import { bindPopups } from "./interactions.js";
import { PEDESTRIAN_LAYERS } from "./layers.js";
import { buildLegend } from "./legend.js";
import { handleNavClick } from "./navigation.js";

const PMTILES_URL = new URL(i18n.dataUrl("pedestrian.pmtiles"), window.location.href).href;
const EDIT_MIN_ZOOM = 16;

export function initMap(style) {
  const map = new maplibregl.Map({
    container: "map", style,
    center: [4.3517, 50.8503], zoom: 12,
    attributionControl: false,
    hash: true
  });
  store.map = map;

  map.addControl(
    new maplibregl.AttributionControl({
      compact: false,
      customAttribution: [String(html`<a href="https://github.com/PasLoin/Brussels-Pedestrian-Network" target="_blank" rel="noopener">PasLoin</a> · <a href="./stats.html">${i18n.t("common.nav.statsShort")}</a>`)]
    }),
    "bottom-right"
  );

  const updateLegendClearance = () => {
    const attrEl = document.querySelector(".maplibregl-ctrl-bottom-right");
    if (!attrEl) return;
    const rect = attrEl.getBoundingClientRect();
    const clearance = Math.max(40, window.innerHeight - rect.top + 8);
    document.documentElement.style.setProperty("--attribution-clearance", `${clearance}px`);
  };
  updateLegendClearance();
  window.addEventListener("resize", updateLegendClearance);

  map.on("load", () => {
    map.addSource("pedestrian", pedestrianSource(`pmtiles://${PMTILES_URL}`));
    PEDESTRIAN_LAYERS.forEach(layer => map.addLayer(layer));

    map.addSource("nav-route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "nav-route-casing", type: "line", source: "nav-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#000", "line-width": ["interpolate", ["linear"], ["zoom"], 10, 6, 16, 14], "line-opacity": 0.4 }
    });
    map.addLayer({
      id: "nav-route-line", type: "line", source: "nav-route",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 10], "line-opacity": 0.92 }
    });
    map.on("click", handleNavClick);

    buildLegend(map);
    bindPopups(map);
  });

  const syncZoomUi = () => {
    const z = map.getZoom();
    const c = map.getCenter();
    document.getElementById("zoom-val").textContent = z.toFixed(1);
    const btn = document.getElementById("edit-btn");
    if (z >= EDIT_MIN_ZOOM) {
      btn.href = `https://www.openstreetmap.org/edit#map=${Math.round(z)}/${c.lat.toFixed(5)}/${c.lng.toFixed(5)}`;
      btn.classList.remove("disabled");
      btn.setAttribute("aria-disabled", "false");
      btn.setAttribute("tabindex", "0");
    } else {
      btn.classList.add("disabled");
      btn.setAttribute("aria-disabled", "true");
      btn.setAttribute("tabindex", "-1");
    }
  };
  map.on("load", syncZoomUi);
  map.on("moveend", syncZoomUi);
  return map;
}
