import { classifyApiCall } from "./api-meter.js";

const MINUTE_MS = 60 * 1000;

export class ApiPausedError extends Error {
  constructor(reason, until) {
    super(`OSM API paused (${reason}) until ${new Date(until).toISOString()}`);
    this.name = "ApiPausedError";
    this.reason = reason;
    this.until = until;
  }
}

export function createApiGuard({ apiUrl, mapPerMinute, pauseMs, now = () => Date.now(), storage = null, key = null }) {
  let mapCalls = [];
  let pausedUntil = 0;
  try {
    const saved = storage && key ? Number(storage.getItem(key)) : 0;
    if (Number.isFinite(saved) && saved > now()) pausedUntil = saved;
  } catch {}
  const listeners = new Set();
  const notify = () => { for (const fn of listeners) fn(); };
  const pauseFor = ms => {
    pausedUntil = now() + ms;
    try { if (storage && key) storage.setItem(key, String(pausedUntil)); } catch {}
    notify();
  };
  const recentMapCalls = () => {
    const cutoff = now() - MINUTE_MS;
    mapCalls = mapCalls.filter(t => t > cutoff);
    return mapCalls;
  };
  return {
    wrap(fetchImpl) {
      return async function guardedFetch(input, init) {
        const url = typeof input === "string" ? input : input && input.url;
        if (typeof url !== "string" || !url.startsWith(apiUrl)) return fetchImpl(input, init);
        if (pausedUntil > now()) throw new ApiPausedError("bandwidth", pausedUntil);
        if (classifyApiCall(url, (init && init.method) || (input && input.method)) === "map") {
          const calls = recentMapCalls();
          if (calls.length >= mapPerMinute) throw new ApiPausedError("rate", calls[0] + MINUTE_MS);
          calls.push(now());
        }
        const response = await fetchImpl(input, init);
        if (response && response.status === 509) pauseFor(pauseMs);
        return response;
      };
    },
    status() {
      const t = now();
      if (pausedUntil > t) return { reason: "bandwidth", until: pausedUntil };
      const calls = recentMapCalls();
      if (calls.length >= mapPerMinute) return { reason: "rate", until: calls[0] + MINUTE_MS };
      return null;
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
