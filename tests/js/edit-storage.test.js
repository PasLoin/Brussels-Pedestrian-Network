const test = require("node:test");
const assert = require("node:assert/strict");
const { loadEdit: load } = require("./helpers.js");

function sharedStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  const faults = { read: false, write: false };
  return {
    faults,
    getItem: k => {
      if (faults.read) throw new Error("SecurityError");
      return data.has(k) ? data.get(k) : null;
    },
    setItem: (k, v) => {
      if (faults.write) {
        const err = new Error("quota");
        err.name = "QuotaExceededError";
        throw err;
      }
      data.set(k, String(v));
    },
    removeItem: k => data.delete(k),
    raw: k => data.get(k),
  };
}

const UCCLE = [4.33, 50.80, 4.331, 50.801];

async function intent(id, value = "no") {
  const { makeIntent } = await load("intent.js");
  const way = { id, version: 1, nodes: [id * 10, id * 10 + 1], tags: { highway: "residential" } };
  return makeIntent({ way, left: value, right: value, bbox: UCCLE, lengthM: 50, now: 1 });
}

const ids = q => q.list().map(i => i.wayId);

test("two tabs adding streets to the same queue keep both", async () => {
  const { createQueue, queueKey } = await load("queue.js");
  const storage = sharedStorage();
  const tabA = createQueue({ storage, env: "dev" });
  const tabB = createQueue({ storage, env: "dev" });
  tabA.put(await intent(1));
  tabB.put(await intent(2));
  tabA.put(await intent(3));
  assert.deepEqual(JSON.parse(storage.raw(queueKey("dev"))).map(i => i.wayId), [1, 2, 3]);
  assert.deepEqual(ids(tabA), [1, 2, 3]);
});

test("removing in one tab does not bring back a street sent from the other", async () => {
  const { createQueue } = await load("queue.js");
  const storage = sharedStorage();
  const tabA = createQueue({ storage, env: "dev" });
  tabA.put(await intent(1));
  tabA.put(await intent(2));
  const tabB = createQueue({ storage, env: "dev" });
  tabB.remove([1]);
  tabA.remove([2]);
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), []);
});

test("undo removes the last street queued in this tab, never one from another tab", async () => {
  const { createQueue } = await load("queue.js");
  const storage = sharedStorage();
  const tabA = createQueue({ storage, env: "dev" });
  const tabB = createQueue({ storage, env: "dev" });
  tabA.put(await intent(1));
  tabB.put(await intent(2));
  assert.equal(tabA.undo().wayId, 1);
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), [2]);
  assert.equal(tabA.undo(), null);
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), [2]);
});

test("undo skips streets already removed and follows a changed value", async () => {
  const { createQueue } = await load("queue.js");
  const q = createQueue({ storage: sharedStorage(), env: "dev" });
  q.put(await intent(1));
  q.put(await intent(2));
  q.put(await intent(1, "yes"));
  q.remove([1]);
  assert.equal(q.undo().wayId, 2);
  assert.equal(q.size(), 0);
});

test("after a reload undo still removes the last stored street", async () => {
  const { createQueue } = await load("queue.js");
  const storage = sharedStorage();
  const before = createQueue({ storage, env: "dev" });
  before.put(await intent(1));
  before.put(await intent(2));
  const after = createQueue({ storage, env: "dev" });
  assert.equal(after.undo().wayId, 2);
  assert.equal(createQueue({ storage, env: "dev" }).undo().wayId, 1);
  assert.equal(createQueue({ storage, env: "dev" }).undo(), null);
});

test("abandoning the queue only drops the streets this tab showed", async () => {
  const { createQueue } = await load("queue.js");
  const storage = sharedStorage();
  const tabA = createQueue({ storage, env: "dev" });
  tabA.put(await intent(1));
  const tabB = createQueue({ storage, env: "dev" });
  tabB.put(await intent(2));
  tabA.clear();
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), [2]);
  tabB.clear();
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), []);
});

test("a full storage keeps the queue in memory and says it is not saved", async () => {
  const { createQueue, queueKey } = await load("queue.js");
  const storage = sharedStorage();
  const q = createQueue({ storage, env: "dev" });
  q.put(await intent(1));
  assert.equal(q.persisted(), true);
  storage.faults.write = true;
  q.put(await intent(2));
  assert.equal(q.persisted(), false);
  assert.deepEqual(ids(q), [1, 2]);
  q.put(await intent(3));
  assert.deepEqual(ids(q), [1, 2, 3]);
  assert.deepEqual(JSON.parse(storage.raw(queueKey("dev"))).map(i => i.wayId), [1]);
  storage.faults.write = false;
  q.remove([3]);
  assert.equal(q.persisted(), true);
  assert.deepEqual(JSON.parse(storage.raw(queueKey("dev"))).map(i => i.wayId), [1, 2]);
});

test("an unreadable storage, as in some private modes, never empties the queue in memory", async () => {
  const { createQueue } = await load("queue.js");
  const storage = sharedStorage();
  const q = createQueue({ storage, env: "dev" });
  q.put(await intent(1));
  storage.faults.read = true;
  q.put(await intent(2));
  assert.deepEqual(ids(q), [1, 2]);
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), []);
});

test("stored entries without a numeric way id or a change are dropped on load", async () => {
  const { createQueue, queueKey } = await load("queue.js");
  const good = await intent(1);
  const storage = sharedStorage({ [queueKey("dev")]: JSON.stringify([good, null, { wayId: "2", set: {} }, { wayId: 3 }, "x"]) });
  assert.deepEqual(ids(createQueue({ storage, env: "dev" })), [1]);
  const notList = sharedStorage({ [queueKey("dev")]: JSON.stringify({ wayId: 1 }) });
  assert.equal(createQueue({ storage: notList, env: "dev" }).size(), 0);
});

test("the pace survives a broken record, an unwritable storage and odd lengths", async () => {
  const { createPace, paceKey } = await load("pace.js");
  const settings = { windowMs: 60_000, maxMeters: 1200, blockMeters: 1800, repeatMs: 300_000, cooldownMs: 20_000 };
  let t = 1_000_000;
  const now = () => t;
  const broken = sharedStorage({ [paceKey("dev")]: "{not json" });
  assert.equal(createPace({ storage: broken, env: "dev", now, ...settings }).status().meters, 0);
  const mixed = sharedStorage({ [paceKey("dev")]: JSON.stringify({ events: [[t - 1000, 300], ["x", 5], [t, "y"], 7] }) });
  assert.equal(createPace({ storage: mixed, env: "dev", now, ...settings }).status().meters, 300);
  const storage = sharedStorage();
  storage.faults.write = true;
  const pace = createPace({ storage, env: "dev", now, ...settings });
  pace.record(-50);
  pace.record("abc");
  pace.record(undefined);
  assert.equal(pace.status().meters, 0);
  pace.record(1300);
  assert.equal(pace.status().tooFast, true);
  t += 61_000;
  assert.deepEqual(pace.status(), { meters: 0, tooFast: false, cooldownLeftMs: 0 });
});

test("a pause in progress hides the too-fast warning and counts down", async () => {
  const { createPace, paceKey } = await load("pace.js");
  const t = 5_000_000;
  const storage = sharedStorage({ [paceKey("dev")]: JSON.stringify({ events: [[t - 500, 1500]], warnedAt: null, cooldownUntil: t + 8000 }) });
  const pace = createPace({ storage, env: "dev", now: () => t, windowMs: 60_000, maxMeters: 1200, blockMeters: 1800, repeatMs: 300_000, cooldownMs: 20_000 });
  assert.deepEqual(pace.status(), { meters: 1500, tooFast: false, cooldownLeftMs: 8000 });
});
