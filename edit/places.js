import { MAX_TAG_LENGTH, clipCodepoints, codepoints } from "./changeset.js";

export const MAX_COMMENT = MAX_TAG_LENGTH;

export function streetLabel(tags) {
  const t = tags || {};
  const fr = (t["name:fr"] || "").trim();
  const nl = (t["name:nl"] || "").trim();
  if (fr && nl) return fr === nl ? fr : `${fr}/${nl}`;
  return (t.name || fr || nl || "").trim();
}

export function communeLabel(props) {
  const p = props || {};
  if (p.name) return p.name;
  if (p.name_fr && p.name_nl && p.name_fr !== p.name_nl) return `${p.name_fr} - ${p.name_nl}`;
  return p.name_fr || p.name_nl || "";
}

function ringBbox(ring) {
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const [x, y] of ring) {
    if (x < w) w = x;
    if (x > e) e = x;
    if (y < s) s = y;
    if (y > n) n = y;
  }
  return [w, s, e, n];
}

function inRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inPolygon(point, rings) {
  if (!inRing(point, rings[0])) return false;
  return !rings.slice(1).some(hole => inRing(point, hole));
}

export function indexCommunes(collection) {
  const out = [];
  for (const f of (collection && collection.features) || []) {
    const g = f && f.geometry;
    if (!g) continue;
    const polygons = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    const label = communeLabel(f.properties);
    for (const rings of polygons) {
      if (label && rings.length && rings[0].length >= 4) out.push({ label, bbox: ringBbox(rings[0]), rings });
    }
  }
  return out;
}

export function communeAt(point, communes) {
  for (const c of communes || []) {
    const [w, s, e, n] = c.bbox;
    if (point[0] < w || point[0] > e || point[1] < s || point[1] > n) continue;
    if (inPolygon(point, c.rings)) return c.label;
  }
  return null;
}

export function bboxCenter([w, s, e, n]) {
  return [(w + e) / 2, (s + n) / 2];
}

function uniqueInOrder(values) {
  const out = [];
  for (const v of values) if (v && !out.includes(v)) out.push(v);
  return out;
}

export function describeGroup(entries, communes) {
  const streets = uniqueInOrder(entries.map(e => streetLabel(e.way && e.way.tags)));
  const unnamed = entries.filter(e => !streetLabel(e.way && e.way.tags)).length;
  const places = uniqueInOrder(entries.map(e => (e.intent.bbox ? communeAt(bboxCenter(e.intent.bbox), communes) : null)));
  return { streets, unnamed, communes: places, count: streets.length + unnamed };
}

export function actionText(count) {
  return `add sidewalk tags on ${count} residential ${count === 1 ? "street" : "streets"}`;
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function generatedComments(description) {
  const { streets, unnamed, communes, count } = description;
  const variants = [];
  if (streets.length === 1 && unnamed === 0) variants.push(`${streets[0]} - add sidewalk tags`);
  if (communes.length) variants.push(`${communes.join(" / ")} : ${actionText(count)}`);
  variants.push(capitalize(actionText(count)));
  return variants;
}

export function hashtagSuffix(text, hashtags) {
  const words = text.toLowerCase().split(/\s+/);
  return hashtags.filter(h => !words.includes(h.toLowerCase()));
}

export function composeComment(description, { remark = "", hashtags = [] } = {}) {
  const note = String(remark || "").trim();
  for (const base of generatedComments(description)) {
    const body = note ? `${base} - ${note}` : base;
    const full = [body, ...hashtagSuffix(body, hashtags)].join(" ");
    if (codepoints(full) <= MAX_COMMENT) return full;
  }
  const base = capitalize(actionText(description.count));
  return clipCodepoints([base, ...hashtagSuffix(base, hashtags)].join(" "), MAX_COMMENT);
}
