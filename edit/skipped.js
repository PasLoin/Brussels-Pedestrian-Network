const MAX_SKIPPED = 500;

export function skippedKey(env) {
  return `bpn.skipped.${env}`;
}

export function createSkipList({ storage, env, max = MAX_SKIPPED }) {
  const key = skippedKey(env);
  let ids = [];
  try {
    const value = JSON.parse(storage.getItem(key) || "[]");
    if (Array.isArray(value)) ids = value.filter(Number.isFinite);
  } catch {}
  const save = () => {
    try { storage.setItem(key, JSON.stringify(ids)); } catch {}
  };
  return {
    list: () => ids.slice(),
    size: () => ids.length,
    has: id => ids.includes(id),
    add(id) {
      ids = [...ids.filter(i => i !== id), id].slice(-max);
      save();
    },
    remove(id) {
      if (!ids.includes(id)) return;
      ids = ids.filter(i => i !== id);
      save();
    },
    clear() {
      ids = [];
      save();
    },
  };
}
