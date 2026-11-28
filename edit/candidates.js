import { linesOf } from "./match.js";
import { WHITELIST, isEditableCandidate, matchesWhitelist } from "./whitelist.js";

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

export function sourceIds(features) {
  const out = new Map();
  for (const f of features || []) {
    if (f.type !== "way" || f.visible === false) continue;
    const raw = (f.tags || {})["@id"];
    if (!/^\d+$/.test(String(raw ?? ""))) continue;
    const source = Number(raw);
    if (!out.has(source)) out.set(source, new Set());
    out.get(source).add(f.id);
  }
  return out;
}

export function mergeSourceIds(index, fresh, { max = 20000 } = {}) {
  const out = index.size + fresh.size > max ? new Map() : new Map(index);
  for (const [source, ids] of fresh) out.set(source, new Set([...(out.get(source) || []), ...ids]));
  return out;
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

export function pointsOf(geometry) {
  if (!geometry) return [];
  if (geometry.type === "Point") return [geometry.coordinates];
  if (geometry.type === "LineString") return geometry.coordinates;
  if (geometry.type === "MultiLineString") return geometry.coordinates.flat();
  return [];
}

export function parseCandidateIndex(text) {
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    return [];
  }
  if (!value || !Array.isArray(value.ways)) return [];
  const out = [];
  for (const entry of value.ways) {
    if (!Array.isArray(entry) || entry.length !== 3) continue;
    const [id, lon, lat] = entry;
    if (!Number.isInteger(id) || id <= 0 || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) continue;
    out.push({ id, lon, lat });
  }
  return out;
}

export function candidatesFromTiles(features, { box = null, exclude = () => false, whitelist = WHITELIST } = {}) {
  const parts = new Map();
  for (const f of features || []) {
    const p = f.properties || {};
    const id = Number(p.osm_id);
    if (!Number.isInteger(id) || id <= 0 || p.sw !== "unknown") continue;
    if (!matchesWhitelist({ highway: p.highway }, whitelist) || exclude(id)) continue;
    const lines = linesOf(f.geometry).filter(line => line.length >= 2);
    if (!lines.length) continue;
    const entry = parts.get(id) || { lines: [], highway: String(p.highway || ""), name: String(p.name || "") };
    entry.lines.push(...lines);
    parts.set(id, entry);
  }
  const out = [];
  for (const [id, { lines, highway, name }] of parts) {
    const geometry = lines.length === 1 ? { type: "LineString", coordinates: lines[0] } : { type: "MultiLineString", coordinates: lines };
    if (box && !pointsOf(geometry).some(c => inBox(c, box))) continue;
    out.push({ type: "Feature", geometry, properties: { osm_id: id, highway, name } });
  }
  return { type: "FeatureCollection", features: out };
}

export function mergeCandidates(previous, collection, box, { max = 3000 } = {}) {
  const out = new Map();
  for (const [id, f] of previous) {
    if (!pointsOf(f.geometry).some(c => inBox(c, box))) out.set(id, f);
  }
  for (const f of collection.features) out.set(f.properties.osm_id, f);
  if (out.size <= max) return out;
  const mid = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  const far = f => Math.min(...pointsOf(f.geometry).map(([x, y]) => (x - mid[0]) ** 2 + (y - mid[1]) ** 2));
  return new Map([...out.entries()].sort((a, b) => far(a[1]) - far(b[1])).slice(0, max));
}

export function countInBox(features, box) {
  let n = 0;
  for (const f of features) if (pointsOf(f.geometry).some(c => inBox(c, box))) n += 1;
  return n;
}

export function boxWithin(inner, outer) {
  return inner[0] >= outer[0] && inner[1] >= outer[1] && inner[2] <= outer[2] && inner[3] <= outer[3];
}
