export function paceKey(env) {
  return `bpn.pace.${env}`;
}

export function createPace({ storage, env, windowMs, maxStreets, repeatMs, cooldownMs, now = () => Date.now() }) {
  const key = paceKey(env);
  let state = { events: [], warnedAt: 0, rearmed: false, cooldownUntil: 0 };
  try {
    const saved = JSON.parse(storage.getItem(key) || "null");
    if (saved && Array.isArray(saved.events)) state = { ...state, ...saved };
  } catch {}
  const save = () => {
    try { storage.setItem(key, JSON.stringify(state)); } catch {}
  };
  const recent = () => {
    const cutoff = now() - windowMs;
    state.events = state.events.filter(t => t > cutoff);
    return state.events.length;
  };
  const evaluate = () => {
    const count = recent();
    const t = now();
    if (count <= maxStreets) {
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
    record() {
      state.events.push(now());
      evaluate();
      save();
    },
    status() {
      evaluate();
      const t = now();
      const count = state.events.length;
      return {
        count,
        tooFast: count > maxStreets && state.cooldownUntil <= t,
        cooldownLeftMs: Math.max(0, state.cooldownUntil - t),
      };
    },
  };
}
