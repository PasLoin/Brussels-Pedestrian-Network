import { isEditableCandidate } from "./whitelist.js";

export const EMPTY_COLLECTION = Object.freeze({ type: "FeatureCollection", features: Object.freeze([]) });

export function bboxAreaDeg2(bounds) {
  return Math.abs(bounds.getEast() - bounds.getWest()) * Math.abs(bounds.getNorth() - bounds.getSouth());
}

export function tooLargeForCandidates(zoom, bounds, settings) {
  if (zoom < settings.candidateMinZoom) return "zoom";
  if (bboxAreaDeg2(bounds) > settings.maxCandidateAreaDeg2) return "tooBig";
  return null;
}

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

export function viewSpanDeg(widthPx, heightPx, zoom, lat) {
  const degPerPx = 360 / (512 * 2 ** zoom);
  return { lon: widthPx * degPerPx, lat: heightPx * degPerPx * Math.cos((lat * Math.PI) / 180) };
}

export function candidateWindow({ center, canvas, focus = null, settings, scale = 1 }) {
  const span = viewSpanDeg(canvas.width, canvas.height, settings.candidateMinZoom, center[1]);
  let lon = span.lon * scale;
  let lat = span.lat * scale;
  let mid = center;
  if (focus) {
    mid = [(focus[0] + focus[2]) / 2, (focus[1] + focus[3]) / 2];
    lon = Math.max(lon, focus[2] - focus[0] + span.lon / 2);
    lat = Math.max(lat, focus[3] - focus[1] + span.lat / 2);
  }
  const area = lon * lat;
  if (area > settings.maxCandidateAreaDeg2) {
    const k = Math.sqrt(settings.maxCandidateAreaDeg2 / area);
    lon *= k;
    lat *= k;
  }
  return [mid[0] - lon / 2, mid[1] - lat / 2, mid[0] + lon / 2, mid[1] + lat / 2];
}

export function boundsBox(bounds) {
  return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
}

export function candidateRequest({ zoom, bounds, center, canvas, focus = null, settings }) {
  if (zoom >= settings.candidateMinZoom) {
    if (bboxAreaDeg2(bounds) > settings.maxCandidateAreaDeg2) return { blocked: "tooBig" };
    return { box: boundsBox(bounds), around: false };
  }
  if (!focus && zoom < settings.candidateFloorZoom) return { blocked: "zoom" };
  return { box: candidateWindow({ center, canvas, focus, settings }), around: true };
}

export function boxString(box) {
  return box.map(v => v.toFixed(7)).join(",");
}

function inBox([x, y], [w, s, e, n]) {
  return x >= w && x <= e && y >= s && y <= n;
}

export function mergeCandidates(previous, collection, box, { max = 3000 } = {}) {
  const out = new Map();
  for (const [id, f] of previous) {
    if (!f.geometry.coordinates.some(c => inBox(c, box))) out.set(id, f);
  }
  for (const f of collection.features) out.set(f.properties.osm_id, f);
  if (out.size <= max) return out;
  const mid = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  const far = f => Math.min(...f.geometry.coordinates.map(([x, y]) => (x - mid[0]) ** 2 + (y - mid[1]) ** 2));
  return new Map([...out.entries()].sort((a, b) => far(a[1]) - far(b[1])).slice(0, max));
}

export function countInBox(features, box) {
  let n = 0;
  for (const f of features) if (f.geometry.coordinates.some(c => inBox(c, box))) n += 1;
  return n;
}

export function boxWithin(inner, outer) {
  return inner[0] >= outer[0] && inner[1] >= outer[1] && inner[2] <= outer[2] && inner[3] <= outer[3];
}
