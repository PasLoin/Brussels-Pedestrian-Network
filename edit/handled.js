const MAX_HANDLED = 2000;
const HANDLED_TTL_MS = 14 * 24 * 60 * 60 * 1000;

export function handledKey(env) {
  return `bpn.handled.${env}`;
}

export function parseDataTimestamp(text) {
  const match = String(text || "").match(/\{[\s\S]*?\}/);
  if (!match) return null;
  try {
    const at = Date.parse(JSON.parse(match[0]).timestamp);
    return Number.isFinite(at) ? at : null;
  } catch {
    return null;
  }
}

export function createHandledList({ storage, env, now = () => Date.now(), ttlMs = HANDLED_TTL_MS, max = MAX_HANDLED }) {
  const key = handledKey(env);
  const entries = new Map();
  try {
    const value = JSON.parse(storage.getItem(key) || "{}");
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [id, at] of Object.entries(value)) {
        if (/^\d+$/.test(id) && Number.isFinite(at)) entries.set(Number(id), at);
      }
    }
  } catch {}
  const save = () => {
    try { storage.setItem(key, JSON.stringify(Object.fromEntries(entries))); } catch {}
  };
  return {
    has: id => entries.has(Number(id)),
    size: () => entries.size,
    add(ids) {
      const at = now();
      for (const id of [].concat(ids)) if (Number.isInteger(Number(id)) && Number(id) > 0) entries.set(Number(id), at);
      if (entries.size > max) {
        const kept = [...entries.entries()].sort((a, b) => b[1] - a[1]).slice(0, max);
        entries.clear();
        for (const [id, when] of kept) entries.set(id, when);
      }
      save();
    },
    prune(dataAt = null) {
      const oldest = now() - ttlMs;
      let changed = false;
      for (const [id, at] of entries) {
        if (at < oldest || (dataAt !== null && dataAt >= at)) {
          entries.delete(id);
          changed = true;
        }
      }
      if (changed) save();
    },
  };
}
