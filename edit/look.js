export function lookTimeMs(lengthM, settings) {
  const proportional = Math.max(0, Number(lengthM) || 0) * settings.lookMsPerMeter;
  return Math.round(Math.min(settings.minLookMs, proportional));
}

export function lookKey(env) {
  return `bpn.look.${env}`;
}

export function createLookTracker({ storage, env, history, tolerance }) {
  const key = lookKey(env);
  let decisions = [];
  try {
    const saved = JSON.parse(storage.getItem(key) || "[]");
    if (Array.isArray(saved)) decisions = saved.filter(d => typeof d === "boolean").slice(-history);
  } catch {}
  return {
    record(quick) {
      decisions = [...decisions, Boolean(quick)].slice(-history);
      try { storage.setItem(key, JSON.stringify(decisions)); } catch {}
    },
    quickCount: () => decisions.filter(Boolean).length,
    hasty: () => decisions.filter(Boolean).length >= tolerance,
  };
}
