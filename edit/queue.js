import { isValidIntent } from "./intent.js";

export function queueKey(env) {
  return `bpn.queue.${env}`;
}

function load(storage, key) {
  let raw;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  try {
    const value = raw ? JSON.parse(raw) : [];
    return Array.isArray(value) ? value.filter(i => i && Number.isFinite(i.wayId) && i.set) : [];
  } catch {
    return [];
  }
}

export function createQueue({ storage, env }) {
  const key = queueKey(env);
  let items = load(storage, key) || [];
  let unsaved = false;
  const history = [];
  let putHere = false;
  const refresh = () => {
    if (unsaved) return;
    const stored = load(storage, key);
    if (stored) items = stored;
  };
  const save = () => {
    try {
      storage.setItem(key, JSON.stringify(items));
      unsaved = false;
    } catch {
      unsaved = true;
    }
  };
  return {
    persisted: () => !unsaved,
    list: () => items.slice(),
    size: () => items.length,
    has: wayId => items.some(i => i.wayId === wayId),
    get: wayId => items.find(i => i.wayId === wayId) || null,
    put(intent) {
      if (!isValidIntent(intent)) throw new Error("invalid-intent");
      refresh();
      items = [...items.filter(i => i.wayId !== intent.wayId), intent];
      history.push(intent.wayId);
      putHere = true;
      save();
    },
    remove(wayIds) {
      refresh();
      const drop = new Set([].concat(wayIds));
      items = items.filter(i => !drop.has(i.wayId));
      save();
    },
    undo() {
      refresh();
      while (history.length) {
        const wayId = history.pop();
        const index = items.findLastIndex(i => i.wayId === wayId);
        if (index === -1) continue;
        const last = items[index];
        items = items.filter((_, i) => i !== index);
        save();
        return last;
      }
      if (putHere) return null;
      const last = items.at(-1) || null;
      if (last) {
        items = items.slice(0, -1);
        save();
      }
      return last;
    },
    clear() {
      const known = new Set(items.map(i => i.wayId));
      refresh();
      items = items.filter(i => !known.has(i.wayId));
      history.length = 0;
      save();
    },
  };
}
