import { distanceM } from "./geo.js";

const TIE_M = 0.01;

export function featureCenter(feature) {
  const coords = feature.geometry.coordinates;
  let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
  for (const [x, y] of coords) {
    if (x < w) w = x;
    if (x > e) e = x;
    if (y < s) s = y;
    if (y > n) n = y;
  }
  return [(w + e) / 2, (s + n) / 2];
}

export function nextCandidate(features, from, exclude) {
  let best = null;
  let bestDistance = Infinity;
  for (const feature of features) {
    const id = feature.properties.osm_id;
    if (exclude.has(id)) continue;
    const d = distanceM(from, featureCenter(feature));
    const tie = best && Math.abs(d - bestDistance) <= TIE_M;
    if ((!tie && d < bestDistance) || (tie && id < best.properties.osm_id)) {
      best = feature;
      bestDistance = d;
    }
  }
  return best;
}
