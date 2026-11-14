export function queueKey(env) {
  return `bpn.queue.${env}`;
}

function load(storage, key) {
  try {
    const raw = storage.getItem(key);
    const value = raw ? JSON.parse(raw) : [];
    return Array.isArray(value) ? value.filter(i => i && Number.isFinite(i.wayId) && i.set) : [];
  } catch {
    return [];
  }
}

export function createQueue({ storage, env }) {
  const key = queueKey(env);
  let items = load(storage, key);
  const save = () => {
    try { storage.setItem(key, JSON.stringify(items)); } catch {}
  };
  return {
    list: () => items.slice(),
    size: () => items.length,
    has: wayId => items.some(i => i.wayId === wayId),
    get: wayId => items.find(i => i.wayId === wayId) || null,
    put(intent) {
      items = [...items.filter(i => i.wayId !== intent.wayId), intent];
      save();
    },
    remove(wayIds) {
      const drop = new Set([].concat(wayIds));
      items = items.filter(i => !drop.has(i.wayId));
      save();
    },
    undo() {
      const last = items.at(-1) || null;
      if (last) {
        items = items.slice(0, -1);
        save();
      }
      return last;
    },
    clear() {
      items = [];
      save();
    },
  };
}
