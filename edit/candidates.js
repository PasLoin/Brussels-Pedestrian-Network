import { isEditableCandidate } from "./whitelist.js";

export const EMPTY_COLLECTION = Object.freeze({ type: "FeatureCollection", features: Object.freeze([]) });

export function bboxString(bounds) {
  return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map(v => v.toFixed(7)).join(",");
}

export function candidatesFromMapData(features, isCandidate = isEditableCandidate) {
  const coords = new Map();
  for (const f of features || []) {
    if (f.type === "node") coords.set(f.id, [f.lon, f.lat]);
  }
  const out = [];
  for (const f of features || []) {
    if (f.type !== "way" || f.visible === false || !isCandidate(f.tags)) continue;
    const line = (f.nodes || []).map(id => coords.get(id));
    if (line.length < 2 || line.some(c => !c)) continue;
    const tags = f.tags || {};
    out.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: line },
      properties: { osm_id: f.id, version: f.version, highway: tags.highway || "", name: tags.name || "" },
    });
  }
  return { type: "FeatureCollection", features: out };
}
