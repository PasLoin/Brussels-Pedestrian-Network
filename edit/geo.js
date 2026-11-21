const EARTH_RADIUS_M = 6371008.8;
const toRad = d => (d * Math.PI) / 180;

export function distanceM([lon1, lat1], [lon2, lat2]) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function lineLengthM(coords) {
  let total = 0;
  for (let i = 1; i < (coords || []).length; i++) total += distanceM(coords[i - 1], coords[i]);
  return total;
}

export function bboxOf(coords) {
  const lons = coords.map(c => c[0]);
  const lats = coords.map(c => c[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

export function mergeBbox(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
}

export function spanM([w, s, e, n]) {
  const mid = (s + n) / 2;
  return Math.max(distanceM([w, mid], [e, mid]), distanceM([w, s], [w, n]));
}
