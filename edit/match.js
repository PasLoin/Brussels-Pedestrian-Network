import { samplesAlong } from "./review.js";

const M_PER_DEG_LAT = 111320;

function projector(lat0) {
  const kx = M_PER_DEG_LAT * Math.cos((lat0 * Math.PI) / 180);
  return ([lon, lat]) => [lon * kx, lat * M_PER_DEG_LAT];
}

function pointToSegmentM(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) : 0;
  const x = a[0] + t * dx - p[0];
  const y = a[1] + t * dy - p[1];
  return Math.sqrt(x * x + y * y);
}

function distanceToLineM(p, line) {
  if (line.length === 1) return pointToSegmentM(p, line[0], line[0]);
  let best = Infinity;
  for (let i = 1; i < line.length; i++) best = Math.min(best, pointToSegmentM(p, line[i - 1], line[i]));
  return best;
}

export function linesOf(geometry) {
  if (!geometry) return [];
  if (geometry.type === "LineString") return [geometry.coordinates];
  if (geometry.type === "MultiLineString") return geometry.coordinates;
  return [];
}

export function matchCandidate(targetLines, candidates, { stepM = 5, nearM = 12, maxMeanM = 8, minCover = 0.8 } = {}) {
  const samples = targetLines.flatMap(line => samplesAlong(line, stepM));
  if (!samples.length) return null;
  const project = projector(samples[0][1]);
  const points = samples.map(project);
  let best = null;
  for (const feature of candidates) {
    const lines = linesOf(feature.geometry).map(line => line.map(project));
    if (!lines.length) continue;
    const distances = points.map(p => Math.min(...lines.map(line => distanceToLineM(p, line))));
    const close = distances.filter(d => d <= nearM);
    const cover = close.length / distances.length;
    if (cover < minCover) continue;
    const meanM = close.reduce((sum, d) => sum + d, 0) / close.length;
    if (meanM > maxMeanM) continue;
    if (!best || cover > best.cover || (cover === best.cover && meanM < best.meanM)) best = { feature, meanM, cover };
  }
  return best;
}
