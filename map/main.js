import { loadBasemapPatterns, loadInitialBasemap, setupBasemapControl } from "./basemaps.js";
import { loadHeaderData } from "./header-data.js";
import { initMap } from "./map-view.js";
import { clearRoute, isNavigating, loadGraph, toggleNavMode } from "./navigation.js";
import {
  collapsePanelsOnSmallScreens, hideRoutePanel, setHeaderOpen, setLegendOpen, showRoutePanel, toggleHeader, toggleLegend,
} from "./panels.js";
import { CLICK_LAYERS, HOVER_LAYERS } from "./popup-layers.js";
import { updateFlowFilter } from "./type-filters.js";

collapsePanelsOnSmallScreens();

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isNavigating()) toggleNavMode(); });
document.getElementById("header-toggle").addEventListener("click", () => toggleHeader());
document.getElementById("legend-toggle").addEventListener("click", () => toggleLegend());
document.getElementById("nav-btn").addEventListener("click", () => toggleNavMode());
document.getElementById("route-clear").addEventListener("click", () => clearRoute());
document.getElementById("flow-threshold-slider").addEventListener("input", (e) => updateFlowFilter(e.target.value));
updateFlowFilter(document.getElementById("flow-threshold-slider").value);

window.BPNMap = Object.freeze({
  showRoutePanel,
  hideRoutePanel,
  setLegendOpen,
  toggleLegend,
  setHeaderOpen,
  toggleHeader,
  hoverPopups: HOVER_LAYERS,
  clickPopups: CLICK_LAYERS,
});

loadGraph();
loadHeaderData();

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile.bind(protocol));

const { bm, style } = await loadInitialBasemap();
setupBasemapControl();
const map = initMap(style);
if (bm.url) map.once("style.load", () => loadBasemapPatterns(map, style, bm.url));
