import { distanceM } from "./geo.js";

const MAX_ENTRIES = 300;

export function reviewKey(env) {
  return `bpn.reviewed.${env}`;
}

export function createReviewStore({ storage, env, ttlMs, now = () => Date.now(), max = MAX_ENTRIES }) {
  const key = reviewKey(env);
  let entries = {};
  try {
    const value = JSON.parse(storage.getItem(key) || "{}");
    if (value && typeof value === "object" && !Array.isArray(value)) entries = value;
  } catch {}
  const fresh = entry => entry && Number.isFinite(entry.at) && now() - entry.at < ttlMs;
  const prune = () => {
    const kept = Object.entries(entries).filter(([, e]) => fresh(e)).sort(([, a], [, b]) => b.at - a.at).slice(0, max);
    entries = Object.fromEntries(kept);
  };
  const save = () => {
    prune();
    try { storage.setItem(key, JSON.stringify(entries)); } catch {}
  };
  prune();
  const get = (wayId, version) => {
    const entry = entries[wayId];
    return fresh(entry) && entry.v === version ? entry : null;
  };
  const mark = (wayId, version, field) => {
    const entry = get(wayId, version) || { v: version, whole: false, detail: false };
    entries[wayId] = { ...entry, [field]: true, at: now() };
    save();
  };
  return {
    get,
    seenWhole: (wayId, version) => Boolean(get(wayId, version)?.whole),
    seenDetail: (wayId, version) => Boolean(get(wayId, version)?.detail),
    markWhole: (wayId, version) => mark(wayId, version, "whole"),
    markDetail: (wayId, version) => mark(wayId, version, "detail"),
    clear() {
      entries = {};
      save();
    },
  };
}

export function samplesAlong(coords, stepM) {
  if (!coords || !coords.length) return [];
  const out = [coords[0]];
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i - 1];
    const b = coords[i];
    const length = distanceM(a, b);
    const parts = Math.max(1, Math.ceil(length / stepM));
    for (let k = 1; k <= parts; k++) {
      const f = k / parts;
      out.push([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]);
    }
  }
  return out;
}

export function coveredIndexes(points, free, margin = 0) {
  const hits = [];
  points.forEach((p, i) => {
    if (p.x >= free.left + margin && p.x <= free.right - margin && p.y >= free.top + margin && p.y <= free.bottom - margin) hits.push(i);
  });
  return hits;
}

export function parseReviewZoom(value) {
  const zoom = Number(value);
  return value !== null && value !== "" && Number.isFinite(zoom) && zoom >= 15 && zoom <= 22 ? zoom : null;
}
