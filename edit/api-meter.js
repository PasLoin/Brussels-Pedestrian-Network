const WINDOW_MS = 60 * 1000;

export function meterKey(env) {
  return `bpn.apiMeter.${env}`;
}

export function classifyApiCall(url, method = "GET") {
  let path;
  try { path = new URL(url).pathname; } catch { return "other"; }
  const verb = String(method || "GET").toUpperCase();
  if (path.startsWith("/oauth2/")) return "oauth";
  const api = path.replace(/^\/api\/0\.6/, "");
  if (api === path) return "other";
  if (/^\/map(\.json)?$/.test(api)) return "map";
  if (/^\/way\/\d+\/full(\.json)?$/.test(api)) return "wayFull";
  if (/^\/way\/\d+(\.json)?$/.test(api)) return "way";
  if (/^\/ways(\.json)?$/.test(api)) return "ways";
  if (/^\/nodes(\.json)?$/.test(api)) return "nodes";
  if (api === "/changeset/create") return "changesetCreate";
  if (/^\/changeset\/\d+\/upload$/.test(api)) return "upload";
  if (/^\/changeset\/\d+\/close$/.test(api) && verb === "PUT") return "changesetClose";
  if (/^\/changesets(\.json)?$/.test(api)) return "changesets";
  if (/^\/user\/details(\.json)?$/.test(api)) return "user";
  return "other";
}

function emptyTotals(since) {
  return { since, total: 0, byKind: {}, byStatus: {}, failures: 0, peakPerMinute: 0, peakInFlight: 0, peakWaiting: 0 };
}

export function createApiMeter({ storage, env, apiUrl, now = () => Date.now() }) {
  const key = meterKey(env);
  let totals = emptyTotals(now());
  try {
    const saved = JSON.parse(storage.getItem(key) || "null");
    if (saved && typeof saved === "object" && Number.isFinite(saved.total)) totals = { ...emptyTotals(saved.since || now()), ...saved };
  } catch {}
  let recent = [];
  let inFlight = 0;
  let waiting = 0;
  const listeners = new Set();
  const save = () => {
    try { storage.setItem(key, JSON.stringify(totals)); } catch {}
  };
  const notify = () => { for (const fn of listeners) fn(); };
  const lastMinute = () => {
    const cutoff = now() - WINDOW_MS;
    recent = recent.filter(t => t > cutoff);
    return recent.length;
  };
  const start = kind => {
    recent.push(now());
    inFlight += 1;
    totals = {
      ...totals,
      total: totals.total + 1,
      byKind: { ...totals.byKind, [kind]: (totals.byKind[kind] || 0) + 1 },
      peakPerMinute: Math.max(totals.peakPerMinute, lastMinute()),
      peakInFlight: Math.max(totals.peakInFlight, inFlight),
    };
    save();
    notify();
  };
  const finish = status => {
    inFlight = Math.max(0, inFlight - 1);
    if (status === "network" || status >= 400) {
      const label = String(status);
      totals = { ...totals, failures: totals.failures + 1, byStatus: { ...totals.byStatus, [label]: (totals.byStatus[label] || 0) + 1 } };
      save();
    }
    notify();
  };
  const ours = url => typeof url === "string" && url.startsWith(apiUrl);
  return {
    wrap(fetchImpl) {
      return async function meteredFetch(input, init) {
        const url = typeof input === "string" ? input : input && input.url;
        if (!ours(url)) return fetchImpl(input, init);
        start(classifyApiCall(url, (init && init.method) || (input && input.method)));
        try {
          const response = await fetchImpl(input, init);
          finish(response.status);
          return response;
        } catch (err) {
          finish(err && err.name === "AbortError" ? 0 : "network");
          throw err;
        }
      };
    },
    stats() {
      return { ...totals, byKind: { ...totals.byKind }, byStatus: { ...totals.byStatus }, lastMinute: lastMinute(), inFlight, waiting };
    },
    noteWaiting(count) {
      waiting = count;
      if (count > totals.peakWaiting) {
        totals = { ...totals, peakWaiting: count };
        save();
      }
      notify();
    },
    reset() {
      totals = emptyTotals(now());
      recent = [];
      save();
      notify();
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

export function installApiMeter(target, meter) {
  const original = target.fetch.bind(target);
  target.fetch = meter.wrap(original);
  return () => { target.fetch = original; };
}

export function installApiChain(target, { apiUrl, meter = null, limit }) {
  const original = target.fetch.bind(target);
  const counted = meter ? meter.wrap(original) : original;
  target.fetch = limit(counted, { matches: url => typeof url === "string" && url.startsWith(apiUrl), onWaiting: n => meter && meter.noteWaiting(n) });
  return () => { target.fetch = original; };
}

export class ApiBlockedError extends Error {
  constructor(url) {
    super(`OSM API call blocked, editing is disabled: ${url}`);
    this.name = "ApiBlockedError";
  }
}

export function blockApi(target, apiUrl) {
  const original = target.fetch.bind(target);
  target.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input && input.url;
    if (typeof url === "string" && url.startsWith(apiUrl)) return Promise.reject(new ApiBlockedError(url));
    return original(input, init);
  };
  return () => { target.fetch = original; };
}
