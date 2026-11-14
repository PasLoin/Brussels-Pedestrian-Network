import { EMPTY_COLLECTION } from "../candidates.js";

export const SOURCE = "edit-candidates";
export const LAYER = "edit-candidates";
export const SELECTION = "edit-selection";
export const SELECTED = "edit-candidates-selected";
export const SELECTED_CASING = "edit-candidates-selected-casing";
export const SIDE_LEFT = "edit-candidates-left";
export const SIDE_RIGHT = "edit-candidates-right";

export function addEditLayers(map) {
  const WIDTH = ["interpolate", ["linear"], ["zoom"], 16, 4, 19, 9];
  map.addSource(SOURCE, { type: "geojson", data: EMPTY_COLLECTION, promoteId: "osm_id" });
  map.addLayer({
    id: LAYER, type: "line", source: SOURCE,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["case", ["boolean", ["feature-state", "queued"], false], "#16a34a", ["boolean", ["feature-state", "skipped"], false], "#9ca3af", "#c026d3"],
      "line-width": WIDTH,
      "line-opacity": 0.85,
    },
  });
  map.addSource(SELECTION, { type: "geojson", data: EMPTY_COLLECTION });
  map.addLayer({
    id: SELECTED_CASING, type: "line", source: SELECTION,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#1f2421", "line-width": ["interpolate", ["linear"], ["zoom"], 16, 10, 19, 17], "line-opacity": 0.9 },
  });
  map.addLayer({
    id: SELECTED, type: "line", source: SELECTION,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["case", ["boolean", ["get", "queued"], false], "#16a34a", "#f5c518"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 16, 6, 19, 11],
    },
  });
  for (const [id, color, sign] of [[SIDE_LEFT, "#0284c7", -1], [SIDE_RIGHT, "#ea580c", 1]]) {
    map.addLayer({
      id, type: "line", source: SELECTION,
      layout: { "line-cap": "butt", "line-join": "round", visibility: "none" },
      paint: {
        "line-color": color,
        "line-width": ["interpolate", ["linear"], ["zoom"], 16, 4, 19, 6],
        "line-offset": ["interpolate", ["linear"], ["zoom"], 16, sign * 9, 19, sign * 16],
      },
    });
  }
}

export function installLayers(ctx) {
  let selectionCoords = null;

  function setEditLayersVisible(visible) {
    const map = ctx.map;
    if (!map) return;
    for (const id of [LAYER, SELECTED_CASING, SELECTED]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    }
    if (!visible) for (const id of [SIDE_LEFT, SIDE_RIGHT]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
  }

  function showSideLines() {
    const map = ctx.map;
    if (!map || !map.getLayer(SIDE_LEFT)) return;
    const d = ctx.state.detail;
    const sides = d.kind === "way" && d.editable && d.choice && d.choice.mode === "sides";
    for (const id of [SIDE_LEFT, SIDE_RIGHT]) map.setLayoutProperty(id, "visibility", sides ? "visible" : "none");
  }

  function showSelection(coords) {
    selectionCoords = coords || null;
    const source = ctx.map && ctx.map.getSource(SELECTION);
    if (!source) return;
    const queued = ctx.state.detail.kind === "way" && Boolean(ctx.state.detail.queued);
    source.setData(coords
      ? { type: "FeatureCollection", features: [{ type: "Feature", properties: { queued }, geometry: { type: "LineString", coordinates: coords } }] }
      : EMPTY_COLLECTION);
  }

  function redrawSelection() {
    if (selectionCoords) showSelection(selectionCoords);
  }

  Object.assign(ctx, { setEditLayersVisible, showSideLines, showSelection, redrawSelection });
}
