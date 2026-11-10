const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");
const OSM = require("../../vendor/osm-api-4.0.1.min.js");

globalThis.html = html;

const EDIT = path.join(__dirname, "..", "..", "edit");
const load = name => import(pathToFileURL(path.join(EDIT, name)).href);

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return { getItem: k => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: k => data.delete(k) };
}

const SETTINGS = { maxWaysPerChangeset: 50, maxChangesetSpanM: 1000, maxChangesetsPerUpload: 3 };
const UCCLE = [4.3330, 50.8000, 4.3340, 50.8005];
const UCCLE_NEAR = [4.3350, 50.8010, 4.3360, 50.8012];
const JETTE = [4.3100, 50.8800, 4.3110, 50.8805];

function way(id, tags, version = 3) {
  return { type: "way", id, version, nodes: [id * 10, id * 10 + 1], tags, user: "u", uid: 1, changeset: 5, timestamp: "t" };
}

async function intentFor(w, left, right, bbox = UCCLE) {
  const { makeIntent } = await load("intent.js");
  return makeIntent({ way: w, left, right, bbox, lengthM: 80, now: 1 });
}

function fakeOsm({ ways = {}, nodes = {}, upload, getFeaturesError, changesets = [] } = {}) {
  const calls = [];
  return {
    calls,
    getFeatures: async (type, ids) => {
      if (type === "node") {
        calls.push(["getNodes", ids]);
        return ids.filter(id => nodes[id]).map(id => nodes[id]);
      }
      calls.push(["getFeatures", ids]);
      if (getFeaturesError) throw getFeaturesError;
      return ids.filter(id => ways[id]).map(id => ways[id]);
    },
    getFeature: async (type, id) => {
      calls.push(["getFeature", id]);
      if (!ways[id]) { const e = new Error("OSM API: gone"); e.cause = 410; throw e; }
      return [ways[id]];
    },
    uploadChangeset: async (tags, diff) => {
      calls.push(["upload", tags, diff]);
      return upload ? upload(tags, diff, calls) : { [1000 + calls.filter(c => c[0] === "upload").length]: { diffResult: {} } };
    },
    listChangesets: async (q) => { calls.push(["list", q]); return changesets; },
    getAuthToken: () => "tok",
  };
}

test("one value for both sides becomes sidewalk:both, different values become left and right", async () => {
  const { tagsForChoice } = await load("intent.js");
  assert.deepEqual(tagsForChoice("separate", "separate"), { "sidewalk:both": "separate" });
  assert.deepEqual(tagsForChoice("separate", "no"), { "sidewalk:left": "separate", "sidewalk:right": "no" });
  assert.throws(() => tagsForChoice("separate", ""), /invalid-choice/);
  assert.throws(() => tagsForChoice("both", "yes"), /invalid-choice/);
});

test("an intent stores what to write, never the snapshot tags", async () => {
  const w = way(7, { highway: "residential", name: "Rue A", lit: "yes" });
  const intent = await intentFor(w, "yes", "no");
  assert.deepEqual(intent.set, { "sidewalk:left": "yes", "sidewalk:right": "no" });
  assert.deepEqual(intent.preconditions, { highway: "residential", noSidewalkKeys: true });
  assert.equal(intent.wayId, 7);
  assert.equal(intent.name, "Rue A");
  assert.equal("tags" in intent, false);
});

test("applying an intent keeps every live tag and only touches sidewalk keys", async () => {
  const { applyIntent } = await load("intent.js");
  const live = { highway: "residential", name: "Rue A", maxspeed: "30" };
  assert.deepEqual(applyIntent(live, { set: { "sidewalk:both": "separate" }, unset: [] }), { ...live, "sidewalk:both": "separate" });
  assert.deepEqual(live, { highway: "residential", name: "Rue A", maxspeed: "30" });
  assert.throws(() => applyIntent(live, { set: { highway: "footway" }, unset: [] }), /refusing to touch highway/);
  assert.throws(() => applyIntent(live, { set: {}, unset: ["name"] }), /refusing to touch name/);
});

test("preconditions are checked against the live tags", async () => {
  const { preconditionsHold } = await load("intent.js");
  const intent = await intentFor(way(1, { highway: "residential" }), "no", "no");
  assert.equal(preconditionsHold(intent, { highway: "residential", name: "x" }), true);
  assert.equal(preconditionsHold(intent, { highway: "residential", sidewalk: "both" }), false);
  assert.equal(preconditionsHold(intent, { highway: "living_street" }), false);
  assert.equal(preconditionsHold(intent, undefined), false);
});

test("the queue keeps one intent per way, persists per environment and undoes", async () => {
  const { createQueue, queueKey } = await load("queue.js");
  const storage = memoryStorage();
  const q = createQueue({ storage, env: "dev" });
  const a = await intentFor(way(1, { highway: "residential" }), "no", "no");
  const b = await intentFor(way(2, { highway: "residential" }), "yes", "yes");
  const a2 = await intentFor(way(1, { highway: "residential" }), "separate", "separate");
  q.put(a); q.put(b); q.put(a2);
  assert.deepEqual(q.list().map(i => [i.wayId, i.set]), [[2, { "sidewalk:both": "yes" }], [1, { "sidewalk:both": "separate" }]]);
  assert.equal(createQueue({ storage, env: "dev" }).size(), 2);
  assert.equal(createQueue({ storage, env: "prod" }).size(), 0);
  assert.equal(q.undo().wayId, 1);
  assert.deepEqual(q.list().map(i => i.wayId), [2]);
  q.remove([2]);
  assert.equal(q.size(), 0);
  storage.setItem(queueKey("dev"), "{broken");
  assert.equal(createQueue({ storage, env: "dev" }).size(), 0);
});

test("the preflight drops ways deleted or already fixed since they were queued", async () => {
  const { preflight } = await load("osm.js");
  const intents = [
    await intentFor(way(1, { highway: "residential" }), "no", "no"),
    await intentFor(way(2, { highway: "residential" }), "no", "no"),
    await intentFor(way(3, { highway: "residential" }), "no", "no"),
  ];
  const osm = fakeOsm({ ways: {
    1: way(1, { highway: "residential" }, 4),
    2: way(2, { highway: "residential", "sidewalk:both": "separate" }, 5),
    3: { ...way(3, { highway: "residential" }), visible: false },
  } });
  const { ready, dropped } = await preflight(osm, intents);
  assert.deepEqual(ready.map(r => [r.intent.wayId, r.way.version]), [[1, 4]]);
  assert.deepEqual(dropped.map(d => [d.intent.wayId, d.reason]), [[2, "already_fixed"], [3, "deleted"]]);
  assert.deepEqual(osm.calls, [["getFeatures", [1, 2, 3]]]);
});

test("a missing way in a batch read falls back to one read per way", async () => {
  const { preflight } = await load("osm.js");
  const err = new Error("OSM API: not found"); err.cause = 404;
  const osm = fakeOsm({ ways: { 1: way(1, { highway: "residential" }) }, getFeaturesError: err });
  const intents = [await intentFor(way(1, { highway: "residential" }), "no", "no"), await intentFor(way(9, { highway: "residential" }), "no", "no")];
  const { ready, dropped } = await preflight(osm, intents);
  assert.deepEqual(ready.map(r => r.intent.wayId), [1]);
  assert.deepEqual(dropped.map(d => [d.intent.wayId, d.reason]), [[9, "deleted"]]);
});

test("a network failure during the preflight is not mistaken for a deletion", async () => {
  const { preflight } = await load("osm.js");
  const osm = fakeOsm({ getFeaturesError: new Error("Failed to fetch") });
  await assert.rejects(preflight(osm, [await intentFor(way(1, { highway: "residential" }), "no", "no")]), /Failed to fetch/);
});

test("ways far apart go to separate changesets, close ones share one", async () => {
  const { groupEntries } = await load("osm.js");
  const entries = [
    { intent: await intentFor(way(1, { highway: "residential" }), "no", "no", UCCLE) },
    { intent: await intentFor(way(2, { highway: "residential" }), "no", "no", JETTE) },
    { intent: await intentFor(way(3, { highway: "residential" }), "no", "no", UCCLE_NEAR) },
  ];
  const groups = groupEntries(entries, SETTINGS);
  assert.deepEqual(groups.map(g => g.entries.map(e => e.intent.wayId)), [[1, 3], [2]]);
});

test("a changeset never holds more ways than allowed", async () => {
  const { groupEntries } = await load("osm.js");
  const entries = [];
  for (let i = 1; i <= 5; i++) entries.push({ intent: await intentFor(way(i, { highway: "residential" }), "no", "no", UCCLE) });
  const groups = groupEntries(entries, { ...SETTINGS, maxWaysPerChangeset: 2 });
  assert.deepEqual(groups.map(g => g.entries.length), [2, 2, 1]);
});

test("the plan refuses a queue spread over too many changesets", async () => {
  const { planUpload } = await load("osm.js");
  const ways = { 1: way(1, { highway: "residential" }), 2: way(2, { highway: "residential" }) };
  const intents = [await intentFor(ways[1], "no", "no", UCCLE), await intentFor(ways[2], "no", "no", JETTE)];
  const plan = await planUpload(fakeOsm({ ways }), intents, { ...SETTINGS, maxChangesetsPerUpload: 1 });
  assert.equal(plan.groups.length, 2);
  assert.equal(plan.tooMany, true);
});

test("the change sent to OSM uses the live version, nodes and tags", async () => {
  const { buildDiff } = await load("osm.js");
  const live = way(101, { highway: "residential", name: "Rue A & B" }, 9);
  const intent = await intentFor(way(101, { highway: "residential" }, 2), "separate", "separate");
  const diff = buildDiff({ entries: [{ intent, way: live }] });
  assert.deepEqual(diff.create, []);
  assert.deepEqual(diff.delete, []);
  const xml = OSM.createOsmChangeXml(777, diff);
  assert.match(xml, /<way id="101" version="9" changeset="777">/);
  assert.match(xml, /<tag k="name" v="Rue A &amp; B"\/>/);
  assert.match(xml, /<tag k="sidewalk:both" v="separate"\/>/);
  assert.match(xml, /<nd ref="1010"\/>\s*<nd ref="1011"\/>/);
});

test("each group is one uploadChangeset call with its own tags", async () => {
  const { groupEntries, uploadGroups } = await load("osm.js");
  const ways = { 1: way(1, { highway: "residential" }), 2: way(2, { highway: "residential" }) };
  const entries = [
    { intent: await intentFor(ways[1], "no", "no", UCCLE), way: ways[1] },
    { intent: await intentFor(ways[2], "no", "no", JETTE), way: ways[2] },
  ];
  const osm = fakeOsm();
  const tagsFor = group => ({ comment: `ways ${group.entries.map(e => e.intent.wayId).join(",")}` });
  const out = await uploadGroups({ osm, groups: groupEntries(entries, SETTINGS), tagsFor });
  assert.equal(out.failed, null);
  assert.equal(out.retried, 0);
  assert.deepEqual(out.done, [{ changesetIds: [1001], wayIds: [1] }, { changesetIds: [1002], wayIds: [2] }]);
  assert.deepEqual(osm.calls.filter(c => c[0] === "upload").map(u => u[1]), [{ comment: "ways 1" }, { comment: "ways 2" }]);
});

function conflictOn(id, times = Infinity) {
  let left = times;
  return (tags, diff, calls) => {
    if (left > 0 && diff.modify.some(w => w.id === id)) {
      left -= 1;
      const e = new Error(`OSM API: Version mismatch: Provided 3, server had: 4 of Way ${id}`);
      e.cause = 409;
      throw e;
    }
    return { [500 + calls.length]: {} };
  };
}

test("without retry a 409 stops the upload, names the conflicting way and keeps earlier groups", async () => {
  const { groupEntries, uploadGroups } = await load("osm.js");
  const ways = { 1: way(1, { highway: "residential" }), 2: way(2, { highway: "residential" }), 3: way(3, { highway: "residential" }) };
  const entries = [
    { intent: await intentFor(ways[1], "no", "no", UCCLE), way: ways[1] },
    { intent: await intentFor(ways[2], "no", "no", JETTE), way: ways[2] },
    { intent: await intentFor(ways[3], "no", "no", [4.40, 50.83, 4.401, 50.831]), way: ways[3] },
  ];
  const osm = fakeOsm({ ways, upload: conflictOn(2) });
  const out = await uploadGroups({ osm, groups: groupEntries(entries, SETTINGS), tagsFor: () => ({}), retryOnConflict: false });
  assert.deepEqual(out.done.map(d => d.wayIds), [[1]]);
  assert.equal(out.failed.index, 1);
  assert.equal(out.failed.conflictWayId, 2);
  assert.equal(osm.calls.filter(c => c[0] === "upload").length, 2);
});

test("a 409 on another tag re-reads the group once and sends it again with the fresh version", async () => {
  const { groupEntries, uploadGroups } = await load("osm.js");
  const queued = way(2, { highway: "residential" }, 3);
  const live = { ...way(2, { highway: "residential", name: "Rue renommée" }, 4) };
  const entries = [{ intent: await intentFor(queued, "no", "no", JETTE), way: queued }];
  const osm = fakeOsm({ ways: { 2: live }, upload: conflictOn(2, 1) });
  const out = await uploadGroups({ osm, groups: groupEntries(entries, SETTINGS), tagsFor: () => ({}) });
  assert.equal(out.failed, null);
  assert.equal(out.retried, 1);
  assert.deepEqual(out.done.map(d => d.wayIds), [[2]]);
  const second = osm.calls.filter(c => c[0] === "upload")[1][2].modify[0];
  assert.equal(second.version, 4);
  assert.deepEqual(second.tags, { highway: "residential", name: "Rue renommée", "sidewalk:both": "no" });
});

test("the retry after a 409 drops a way reversed meanwhile instead of writing its sides backwards", async () => {
  const { groupEntries, uploadGroups } = await load("osm.js");
  const queued = way(2, { highway: "residential" }, 3);
  const reversed = { ...queued, version: 4, nodes: [...queued.nodes].reverse() };
  const entries = [{ intent: await intentFor(queued, "yes", "no", JETTE), way: queued }];
  const osm = fakeOsm({ ways: { 2: reversed }, upload: conflictOn(2, 1) });
  const out = await uploadGroups({ osm, groups: groupEntries(entries, SETTINGS), tagsFor: () => ({}) });
  assert.equal(out.failed, null);
  assert.deepEqual(out.done, []);
  assert.deepEqual(out.dropped.map(d => [d.intent.wayId, d.reason]), [[2, "geometry_changed"]]);
  assert.equal(osm.calls.filter(c => c[0] === "upload").length, 1);
});

test("a second 409 after the retry gives up on the group", async () => {
  const { groupEntries, uploadGroups } = await load("osm.js");
  const w2 = way(2, { highway: "residential" });
  const entries = [{ intent: await intentFor(w2, "no", "no", JETTE), way: w2 }];
  const osm = fakeOsm({ ways: { 2: w2 }, upload: conflictOn(2) });
  const out = await uploadGroups({ osm, groups: groupEntries(entries, SETTINGS), tagsFor: () => ({}) });
  assert.equal(out.retried, 1);
  assert.equal(out.failed.conflictWayId, 2);
  assert.equal(osm.calls.filter(c => c[0] === "upload").length, 2);
});

test("a server error that is not a conflict is never retried", async () => {
  const { groupEntries, uploadGroups } = await load("osm.js");
  const w1 = way(1, { highway: "residential" });
  const entries = [{ intent: await intentFor(w1, "no", "no", UCCLE), way: w1 }];
  const osm = fakeOsm({ ways: { 1: w1 }, upload: () => { const e = new Error("OSM API: Database offline for maintenance"); e.cause = 503; throw e; } });
  const out = await uploadGroups({ osm, groups: groupEntries(entries, SETTINGS), tagsFor: () => ({}) });
  assert.equal(out.retried, 0);
  assert.equal(out.failed.status, 503);
  assert.equal(osm.calls.filter(c => c[0] === "upload").length, 1);
});

test("the end nodes recorded at queue time guard against reversal and splitting", async () => {
  const { geometryUnchanged, wayEnds } = await load("intent.js");
  const base = way(7, { highway: "residential" });
  base.nodes = [1, 2, 3, 4];
  const intent = await intentFor(base, "yes", "no");
  assert.deepEqual(intent.ends, { closed: false, first: 1, last: 4 });
  assert.equal(geometryUnchanged(intent, { ...base, version: 4 }), true);
  assert.equal(geometryUnchanged(intent, { ...base, nodes: [1, 2, 9, 3, 4] }), true);
  assert.equal(geometryUnchanged(intent, { ...base, nodes: [4, 3, 2, 1] }), false);
  assert.equal(geometryUnchanged(intent, { ...base, nodes: [1, 2, 3] }), false);
  assert.equal(geometryUnchanged(intent, { ...base, nodes: [3, 4] }), false);
  assert.equal(geometryUnchanged({ ...intent, ends: undefined }, base), false);
  const loop = { ...base, nodes: [1, 2, 3, 1] };
  const loopIntent = await intentFor(loop, "yes", "no");
  assert.deepEqual(loopIntent.ends, { closed: true, nodes: [1, 2, 3, 1] });
  assert.equal(geometryUnchanged(loopIntent, loop), true);
  assert.equal(geometryUnchanged(loopIntent, { ...loop, nodes: [1, 3, 2, 1] }), false);
  assert.equal(geometryUnchanged(loopIntent, { ...loop, nodes: [1, 2, 5, 3, 1] }), false);
  assert.equal(wayEnds({ nodes: [1] }), null);
});

test("the preflight drops a way reversed or split since it was queued", async () => {
  const { preflight } = await load("osm.js");
  const a = way(1, { highway: "residential" });
  const b = way(2, { highway: "residential" });
  const intents = [await intentFor(a, "yes", "no"), await intentFor(b, "no", "no")];
  const osm = fakeOsm({ ways: {
    1: { ...a, version: 4, nodes: [...a.nodes].reverse() },
    2: { ...b, version: 4, nodes: [b.nodes[0], 999] },
  } });
  const { ready, dropped } = await preflight(osm, intents);
  assert.deepEqual(ready, []);
  assert.deepEqual(dropped.map(d => [d.intent.wayId, d.reason]), [[1, "geometry_changed"], [2, "geometry_changed"]]);
});

test("only version conflicts name a way", async () => {
  const { conflictWayId } = await load("osm.js");
  const conflict = Object.assign(new Error("OSM API: Version mismatch: Provided 3, server had: 4 of Way 42"), { cause: 409 });
  assert.equal(conflictWayId(conflict), 42);
  assert.equal(conflictWayId(Object.assign(new Error("OSM API: The changeset 5 was closed"), { cause: 409 })), null);
  assert.equal(conflictWayId(Object.assign(new Error("OSM API: Way 42 still used"), { cause: 412 })), null);
  assert.equal(conflictWayId(new Error("Failed to fetch")), null);
});

test("only our own open and empty changesets are closed after a failure", async () => {
  const { closeEmptyChangesets } = await load("osm.js");
  const osm = fakeOsm({ changesets: [
    { id: 1, open: true, changes_count: 0, tags: { created_by: "BrusselsPedestrianNetwork 0.2.0" } },
    { id: 2, open: true, changes_count: 3, tags: { created_by: "BrusselsPedestrianNetwork 0.2.0" } },
    { id: 3, open: true, changes_count: 0, tags: { created_by: "iD 2.30" } },
    { id: 4, open: false, changes_count: 0, tags: { created_by: "BrusselsPedestrianNetwork 0.2.0" } },
  ] });
  const requests = [];
  const fetchImpl = async (url, opts) => { requests.push([url, opts.method, opts.headers.Authorization]); return { ok: true }; };
  const closed = await closeEmptyChangesets({ osm, apiUrl: "https://dev", uid: 9, createdBy: "BrusselsPedestrianNetwork 0.2.0", fetchImpl });
  assert.deepEqual(closed, [1]);
  assert.deepEqual(requests, [["https://dev/api/0.6/changeset/1/close", "PUT", "Bearer tok"]]);
  assert.deepEqual(osm.calls.find(c => c[0] === "list")[1], { user: 9 });
});

test("changeset tags carry everything a reviewer needs", async () => {
  const { buildChangesetTags } = await load("changeset.js");
  const tags = buildChangesetTags({
    comment: "Ajout des tags sidewalk",
    sources: ["survey", "aerial imagery", "survey"],
    hashtags: ["BrusselsPedestrianNetwork", "#bpn", "#BPN"],
    reviewRequested: true,
    locale: "fr",
    host: "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/devtest.html",
    imageryUsed: ["OpenFreeMap Liberty", "UrbIS Ortho", "UrbIS Ortho"],
    changesetsCount: 12,
  });
  assert.deepEqual(tags, {
    created_by: "BrusselsPedestrianNetwork 0.2.0",
    osm_api_js_version: "4.0.1",
    comment: "Ajout des tags sidewalk #BrusselsPedestrianNetwork #bpn",
    source: "survey;aerial imagery",
    imagery_used: "OpenFreeMap Liberty;UrbIS Ortho",
    locale: "fr",
    hashtags: "#BrusselsPedestrianNetwork;#bpn",
    host: "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/devtest.html",
    changesets_count: "12",
    review_requested: "yes",
  });
});

test("a changeset without source or comment is refused, optional tags are left out", async () => {
  const { buildChangesetTags } = await load("changeset.js");
  assert.throws(() => buildChangesetTags({ comment: "x", sources: [] }), /source-required/);
  assert.throws(() => buildChangesetTags({ comment: "x", sources: [" "] }), /source-required/);
  assert.throws(() => buildChangesetTags({ comment: " ", sources: ["survey"] }), /comment-required/);
  assert.throws(() => buildChangesetTags({ comment: "x".repeat(300), sources: ["survey"] }), /tag-too-long:comment/);
  const tags = buildChangesetTags({ comment: "x #bpn", sources: ["survey"], hashtags: ["bpn"] });
  assert.equal(tags.comment, "x #bpn");
  assert.equal("review_requested" in tags, false);
  assert.equal("imagery_used" in tags, false);
  assert.equal("changesets_count" in tags, false);
});

test("the version announced in created_by matches the vendored library", async () => {
  const { OSM_API_VERSION } = await load("env.js");
  const fs = require("node:fs");
  assert.ok(fs.existsSync(path.join(__dirname, "..", "..", "vendor", `osm-api-${OSM_API_VERSION}.min.js`)));
});

test("a changeset can never exceed 50 ways whatever the settings", async () => {
  const { resolveEnv, SETTINGS: DEFAULTS } = await load("env.js");
  const env = resolveEnv("dev", "https://x/test-api/devtest.html", { ...DEFAULTS, maxWaysPerChangeset: 500 });
  assert.equal(env.maxWaysPerChangeset, 50);
});

test("lengths and spans are measured in metres", async () => {
  const { lineLengthM, spanM, bboxOf } = await load("geo.js");
  const coords = [[4.35, 50.85], [4.35, 50.86]];
  assert.ok(Math.abs(lineLengthM(coords) - 1112) < 5);
  assert.deepEqual(bboxOf(coords), [4.35, 50.85, 4.35, 50.86]);
  assert.ok(Math.abs(spanM([4.35, 50.85, 4.36, 50.85]) - 703) < 5);
});

test("the edit form offers both sides first, then different sides", async () => {
  const { detailView } = await load("panel.js");
  const way5 = { id: 5, version: 2, tags: { highway: "residential" } };
  const i18n = i18nFor("fr");
  const first = String(detailView({ kind: "way", editable: true, way: way5, choice: { mode: "both", both: "", left: "", right: "" } }, i18n, "https://dev", { autoQueue: true }));
  assert.match(first, /Les deux côtés/);
  assert.match(first, /data-side="both" data-value="separate"/);
  assert.doesNotMatch(first, /data-side="left"/);
  assert.match(first, /data-mode="sides"/);
  assert.doesNotMatch(first, /data-edit-action="queue"/);
  const sides = String(detailView({ kind: "way", editable: true, way: way5, choice: { mode: "sides", both: "", left: "yes", right: "" } }, i18n, "https://dev", { autoQueue: true }));
  assert.match(sides, /data-side="left" data-value="yes" aria-pressed="true"/);
  assert.match(sides, /data-side="right" data-value="yes" aria-pressed="false"/);
  assert.match(sides, /bleu à gauche/);
  assert.match(sides, /data-mode="both"/);
});

test("without automatic queueing the add button waits for a complete choice", async () => {
  const { detailView } = await load("panel.js");
  const way5 = { id: 5, version: 2, tags: { highway: "residential" } };
  const i18n = i18nFor("fr");
  const empty = String(detailView({ kind: "way", editable: true, way: way5, choice: { mode: "both", both: "", left: "", right: "" } }, i18n, "https://dev", { autoQueue: false }));
  assert.match(empty, /data-edit-action="queue" disabled/);
  const done = String(detailView({ kind: "way", editable: true, way: way5, choice: { mode: "both", both: "no", left: "no", right: "no" } }, i18n, "https://dev", { autoQueue: false }));
  assert.match(done, /data-edit-action="queue">/);
});

test("a queued way shows its tags, the long way warning and a remove button", async () => {
  const { detailView } = await load("panel.js");
  const intent = await intentFor(way(5, { highway: "residential" }), "separate", "no");
  const out = String(detailView({
    kind: "way", editable: true, longWay: true, lengthM: 412.4, queued: intent,
    choice: { mode: "sides", both: "", left: "separate", right: "no" },
    way: { id: 5, version: 2, tags: { highway: "residential" } },
  }, i18nFor("fr"), "https://dev", { autoQueue: true }));
  assert.match(out, /412 m/);
  assert.match(out, /En file : sidewalk:left=separate · sidewalk:right=no/);
  assert.match(out, /data-edit-action="unqueue"/);
  const fixed = String(detailView({ kind: "way", editable: false, way: { id: 5, version: 2, tags: {} } }, i18nFor("fr"), "https://dev", { autoQueue: true }));
  assert.doesNotMatch(fixed, /data-edit-action="choose"/);
});

test("choosing both sides first, switching to sides and back keeps a coherent choice", async () => {
  const { EMPTY_CHOICE, chooseValue, completeChoice, switchMode, choiceFromIntent } = await load("intent.js");
  let c = chooseValue(EMPTY_CHOICE, "both", "separate");
  assert.deepEqual(completeChoice(c), { left: "separate", right: "separate" });
  c = switchMode(c, "sides");
  assert.deepEqual([c.mode, c.left, c.right], ["sides", "separate", "separate"]);
  c = chooseValue(c, "right", "no");
  assert.deepEqual(completeChoice(c), { left: "separate", right: "no" });
  assert.deepEqual(switchMode(c, "both"), { mode: "both", both: "", left: "", right: "" });
  assert.equal(completeChoice(chooseValue(c, "left", "separate")), null);
  assert.equal(completeChoice(chooseValue(chooseValue(EMPTY_CHOICE, "both", "yes"), "both", "yes")), null);
  assert.throws(() => chooseValue(EMPTY_CHOICE, "both", "maybe"), /invalid-choice/);
  assert.throws(() => chooseValue(EMPTY_CHOICE, "top", "yes"), /invalid-side/);
  assert.deepEqual(choiceFromIntent(await intentFor(way(1, { highway: "residential" }), "no", "no")), { mode: "both", both: "no", left: "no", right: "no" });
  assert.deepEqual(choiceFromIntent(await intentFor(way(1, { highway: "residential" }), "yes", "no")), { mode: "sides", both: "", left: "yes", right: "no" });
  assert.equal(choiceFromIntent(null), EMPTY_CHOICE);
});

test("automatic queueing is on by default and can be turned off in the settings", async () => {
  const { SETTINGS, resolveEnv } = await load("env.js");
  assert.equal(SETTINGS.autoQueue, true);
  assert.equal(resolveEnv("dev", "https://x/test-api/devtest.html", { ...SETTINGS, autoQueue: false }).autoQueue, false);
});

test("the queue view escapes names and only offers sending once a plan exists and the user is logged in", async () => {
  const { queueView } = await load("panel.js");
  const intent = { ...(await intentFor(way(5, { highway: "residential" }), "no", "no")), name: "<img src=x onerror=alert(1)>" };
  const form = { comment: "c", sources: ["survey"], sourceOther: "", hashtags: "#bpn", review: false };
  const settings = { sourcePresets: ["survey", "aerial imagery"] };
  const base = { items: [intent], form, plan: null, result: null, busy: false, loggedIn: false };
  const i18n = i18nFor("fr");
  const noPlan = String(queueView(base, i18n, "https://dev", settings));
  assert.doesNotMatch(noPlan, /<img/);
  assert.doesNotMatch(noPlan, /data-edit-action="send"/);
  assert.match(noPlan, /value="survey" checked/);
  const plan = { ready: [{}], dropped: [], groups: [{}], tooMany: false, max: 3 };
  assert.match(String(queueView({ ...base, plan }, i18n, "https://dev", settings)), /data-edit-action="send" disabled/);
  assert.match(String(queueView({ ...base, plan, loggedIn: true }, i18n, "https://dev", settings)), /data-edit-action="send">Envoyer 1 changeset</);
  const tooMany = String(queueView({ ...base, plan: { ...plan, groups: [{}, {}, {}, {}], tooMany: true }, loggedIn: true }, i18n, "https://dev", settings));
  assert.doesNotMatch(tooMany, /data-edit-action="send"/);
  assert.match(tooMany, /4 zones/);
});

test("results link every changeset on the environment's site", async () => {
  const { queueView } = await load("panel.js");
  const form = { comment: "", sources: [], sourceOther: "", hashtags: "", review: false };
  const out = String(queueView({
    items: [], form, plan: null, busy: false, loggedIn: true,
    result: { done: [{ changesetIds: [11], wayIds: [1] }, { changesetIds: [12], wayIds: [2] }], failed: { message: "x" }, conflictWayId: 3, closed: [99] },
  }, i18nFor("fr"), "https://master.apis.dev.openstreetmap.org", { sourcePresets: [] }));
  assert.match(out, /href="https:\/\/master\.apis\.dev\.openstreetmap\.org\/changeset\/11"/);
  assert.match(out, /href="https:\/\/master\.apis\.dev\.openstreetmap\.org\/changeset\/12"/);
  assert.match(out, /w3 a été modifié/);
  assert.match(out, /1 changeset vide fermé/);
});

test("the P2 panel speaks every published language without a missing key", async () => {
  const { queueView, detailView } = await load("panel.js");
  const intent = await intentFor(way(5, { highway: "residential" }), "no", "yes");
  for (const lang of ["en", "fr", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const form = { comment: "", sources: [], sourceOther: "", hashtags: "", review: false };
    const outs = [
      detailView({ kind: "way", editable: true, longWay: true, lengthM: 300, queued: intent, choice: { mode: "sides", both: "", left: "no", right: "yes" }, way: { id: 5, version: 1, tags: {} } }, i18n, "https://x", { autoQueue: false }),
      detailView({ kind: "way", editable: true, longWay: false, lengthM: 30, queued: null, choice: { mode: "both", both: "", left: "", right: "" }, way: { id: 5, version: 1, tags: {} } }, i18n, "https://x", { autoQueue: true }),
      queueView({ items: [], form, plan: null, result: null, busy: false, loggedIn: false }, i18n, "https://x", { sourcePresets: ["survey"] }),
      queueView({ items: [intent], form, busy: true, loggedIn: true,
        plan: { ready: [{}], groups: [{}], tooMany: false, max: 3, dropped: ["deleted", "already_fixed", "modified_meanwhile"].map(reason => ({ intent, reason })) },
        result: { done: [{ changesetIds: [1, 2], wayIds: [5] }], failed: { message: "m" }, conflictWayId: null, closed: [1, 2], error: "e" } }, i18n, "https://x", { sourcePresets: ["survey"] }),
      queueView({ items: [intent], form, busy: false, loggedIn: true, plan: { ready: [], groups: [{}, {}], tooMany: true, max: 1, dropped: [] }, result: null }, i18n, "https://x", { sourcePresets: [] }),
    ].map(String);
    for (const text of outs) assert.doesNotMatch(text, /\bedit\.[a-z]+\.[A-Za-z_]+/, `${lang}`);
    assert.deepEqual(warnings, []);
  }
});

const node = (id, lon, lat, extra = {}) => ({ type: "node", id, lon, lat, version: 1, ...extra });

async function intentWithCoords(w, coords, settings = {}) {
  const { makeIntent } = await load("intent.js");
  return makeIntent({ way: w, left: "no", right: "no", bbox: UCCLE, lengthM: 80, coords, now: 1, ...settings });
}

test("an intent remembers where each node of the way was when it was queued", async () => {
  const w = way(9, { highway: "residential" });
  w.nodes = [1, 2, 3];
  const intent = await intentWithCoords(w, [[4.30, 50.80], [4.301, 50.80], [4.302, 50.80]]);
  assert.deepEqual(intent.nodeCoords, [[1, 4.30, 50.80], [2, 4.301, 50.80], [3, 4.302, 50.80]]);
  assert.equal((await intentWithCoords(w, [[4.30, 50.80]])).nodeCoords, null);
  assert.equal((await intentWithCoords(w, undefined)).nodeCoords, null);
});

test("a node moved further than the threshold since queueing drops the way with the distance", async () => {
  const { preflight } = await load("osm.js");
  const w = way(9, { highway: "residential" });
  w.nodes = [1, 2, 3];
  const intent = await intentWithCoords(w, [[4.30, 50.80], [4.301, 50.80], [4.302, 50.80]]);
  const moved = fakeOsm({ ways: { 9: w }, nodes: { 1: node(1, 4.30, 50.80), 2: node(2, 4.301, 50.8009), 3: node(3, 4.302, 50.80) } });
  const out = await preflight(moved, [intent], { maxNodeShiftM: 10 });
  assert.deepEqual(out.ready, []);
  assert.equal(out.dropped[0].reason, "node_moved");
  assert.ok(Math.abs(out.dropped[0].shiftM - 100) < 2);
  assert.deepEqual(moved.calls.find(c => c[0] === "getNodes")[1], [1, 2, 3]);
});

test("small realignments, removed nodes and intents without positions are not blocked", async () => {
  const { preflight } = await load("osm.js");
  const w = way(9, { highway: "residential" });
  w.nodes = [1, 2, 3];
  const intent = await intentWithCoords(w, [[4.30, 50.80], [4.301, 50.80], [4.302, 50.80]]);
  const nudged = fakeOsm({ ways: { 9: w }, nodes: { 1: node(1, 4.30, 50.80), 2: node(2, 4.30105, 50.80003), 3: node(3, 4.302, 50.80) } });
  assert.equal((await preflight(nudged, [intent], { maxNodeShiftM: 10 })).ready.length, 1);
  const without2 = { ...w, version: 4, nodes: [1, 3] };
  const removed = fakeOsm({ ways: { 9: without2 }, nodes: { 1: node(1, 4.30, 50.80), 2: node(2, 4.5, 50.9), 3: node(3, 4.302, 50.80) } });
  assert.equal((await preflight(removed, [intent], { maxNodeShiftM: 10 })).ready.length, 1);
  const legacy = { ...intent, nodeCoords: null };
  const noRead = fakeOsm({ ways: { 9: w } });
  assert.equal((await preflight(noRead, [legacy], { maxNodeShiftM: 10 })).ready.length, 1);
  assert.equal(noRead.calls.some(c => c[0] === "getNodes"), false);
});

test("nodes are read in chunks so a full queue never builds an oversized request", async () => {
  const { readLiveNodes } = await load("osm.js");
  const ids = Array.from({ length: 1200 }, (_, i) => i + 1);
  const osm = fakeOsm({ nodes: Object.fromEntries(ids.map(id => [id, node(id, 4.3, 50.8)])) });
  const live = await readLiveNodes(osm, [...ids, ...ids.slice(0, 10)]);
  assert.equal(live.size, 1200);
  assert.deepEqual(osm.calls.filter(c => c[0] === "getNodes").map(c => c[1].length), [500, 500, 200]);
});

test("the plan explains a moved node and a vanished way plainly", async () => {
  const { queueView, detailView } = await load("panel.js");
  const form = { remark: "", sources: [], sourceOther: "", hashtags: "", review: false };
  const out = String(queueView({
    items: [], form, busy: false, loggedIn: true, result: null, comments: [],
    plan: { ready: [], groups: [], tooMany: false, max: 3, dropped: [{ intent: { wayId: 4, name: "Rue A" }, reason: "node_moved", shiftM: 412.6 }] },
  }, i18nFor("fr"), "https://dev", { sourcePresets: [] }));
  assert.match(out, /Rue A \(w4\) : un nœud a été déplacé de 413 m depuis la mise en file/);
  assert.match(String(detailView({ kind: "gone", wayId: 4307565075 }, i18nFor("fr"), "https://dev")), /w4307565075 n&#039;existe plus sur OSM/);
});
