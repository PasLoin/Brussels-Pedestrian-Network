export function paceKey(env) {
  return `bpn.pace.${env}`;
}

function validEvent(e) {
  return Array.isArray(e) && Number.isFinite(e[0]) && Number.isFinite(e[1]);
}

export function createPace({ storage, env, windowMs, maxMeters, blockMeters, repeatMs, cooldownMs, now = () => Date.now() }) {
  const key = paceKey(env);
  let state = { events: [], warnedAt: null, cooldownUntil: 0 };
  try {
    const saved = JSON.parse(storage.getItem(key) || "null");
    if (saved && Array.isArray(saved.events)) state = { ...state, ...saved, events: saved.events.filter(validEvent) };
  } catch {}
  const save = () => {
    try { storage.setItem(key, JSON.stringify(state)); } catch {}
  };
  const recentMeters = () => {
    const cutoff = now() - windowMs;
    state.events = state.events.filter(([t]) => t > cutoff);
    return state.events.reduce((sum, [, m]) => sum + m, 0);
  };
  const warnedRecently = t => Number.isFinite(state.warnedAt) && t - state.warnedAt < repeatMs;
  return {
    record(lengthM) {
      const t = now();
      const alreadyWarned = warnedRecently(t);
      state.events.push([t, Math.max(0, Number(lengthM) || 0)]);
      const meters = recentMeters();
      if (alreadyWarned && meters > blockMeters) {
        state.cooldownUntil = t + cooldownMs;
        state.events = [];
        state.warnedAt = t;
      } else if (meters > maxMeters && !alreadyWarned) {
        state.warnedAt = t;
      }
      save();
    },
    status() {
      recentMeters();
      const t = now();
      const meters = Math.round(state.events.reduce((sum, [, m]) => sum + m, 0));
      return {
        meters,
        tooFast: meters > maxMeters && state.cooldownUntil <= t,
        cooldownLeftMs: Math.max(0, state.cooldownUntil - t),
      };
    },
  };
}
