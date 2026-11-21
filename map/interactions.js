import { isNavigating, isPickingRoute } from "./navigation.js";
import { CLICK_LAYERS, HOVER_LAYERS } from "./popup-layers.js";
import { store } from "./store.js";

const openPopups = [];

export function closePopups() {
  for (const p of openPopups) p.remove();
}

export function bindPopups(map) {
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: "280px" });
  openPopups.push(popup);
  const allHoverIds = HOVER_LAYERS.flatMap(h => h.ids);

  map.on("mousemove", (e) => {
    if (isPickingRoute() || store.editing) { popup.remove(); return; }
    const visibleIds = allHoverIds.filter(id => {
      try { return map.getLayoutProperty(id, "visibility") !== "none"; }
      catch { return false; }
    });
    if (!visibleIds.length) { popup.remove(); return; }
    const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
    if (!features.length) { popup.remove(); if (!isNavigating()) map.getCanvas().style.cursor = ""; return; }
    if (!isNavigating()) map.getCanvas().style.cursor = "pointer";
    const f = features[0];
    const hoverConf = HOVER_LAYERS.find(h => h.ids.includes(f.layer.id));
    if (!hoverConf) return;
    popup.setLngLat(e.lngLat).setHTML(hoverConf.format(f.properties)).addTo(map);
  });

  map.on("mouseleave", allHoverIds, () => { popup.remove(); if (!isNavigating() && !store.editing) map.getCanvas().style.cursor = ""; });

  const clickPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: "300px" });
  openPopups.push(clickPopup);
  const allClickIds = CLICK_LAYERS.flatMap(c => c.ids);

  map.on("click", (e) => {
    if (isNavigating() || store.editing) return;
    const visibleIds = allClickIds.filter(id => {
      try { return map.getLayoutProperty(id, "visibility") !== "none"; }
      catch { return false; }
    });
    if (!visibleIds.length) return;
    const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
    if (!features.length) return;
    e.preventDefault && e.preventDefault();
    const f = features[0];
    const conf = CLICK_LAYERS.find(c => c.ids.includes(f.layer.id));
    if (!conf) return;
    map.getCanvas().style.cursor = "pointer";
    store.lastClicked = { id: f.properties.osm_id, geometry: f.geometry };
    clickPopup.setLngLat(e.lngLat).setHTML(conf.format(f.properties)).addTo(map);
  });

  map.on("mousemove", (e) => {
    if (isNavigating() || store.editing) return;
    const visibleIds = allClickIds.filter(id => {
      try { return map.getLayoutProperty(id, "visibility") !== "none"; }
      catch { return false; }
    });
    if (!visibleIds.length) return;
    const features = map.queryRenderedFeatures(e.point, { layers: visibleIds });
    map.getCanvas().style.cursor = features.length ? "pointer" : "";
  });
}
