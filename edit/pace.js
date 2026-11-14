export function paceKey(env) {
  return `bpn.pace.${env}`;
}

function validEvent(e) {
  return Array.isArray(e) && Number.isFinite(e[0]) && Number.isFinite(e[1]);
}

export function createPace({ storage, env, windowMs, maxMeters, repeatMs, cooldownMs, now = () => Date.now() }) {
  const key = paceKey(env);
  let state = { events: [], warnedAt: 0, rearmed: false, cooldownUntil: 0 };
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
  const evaluate = () => {
    const meters = recentMeters();
    const t = now();
    if (meters <= maxMeters) {
      if (state.warnedAt && !state.rearmed) state.rearmed = true;
      return;
    }
    if (state.warnedAt && state.rearmed && t - state.warnedAt < repeatMs) {
      state.cooldownUntil = t + cooldownMs;
      state.events = [];
      state.warnedAt = t;
      state.rearmed = false;
    } else if (!state.warnedAt || t - state.warnedAt >= repeatMs) {
      state.warnedAt = t;
      state.rearmed = false;
    }
  };
  return {
    record(lengthM) {
      state.events.push([now(), Math.max(0, Number(lengthM) || 0)]);
      evaluate();
      save();
    },
    status() {
      evaluate();
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
