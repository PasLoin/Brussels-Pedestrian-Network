const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");

globalThis.html = html;

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);
const API = "https://dev.example";

function memoryStorage() {
  const data = new Map();
  return { getItem: k => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)) };
}

test("at most 25 map loads per rolling minute, other calls are not counted", async () => {
  const { createApiGuard, ApiPausedError } = await load("api-guard.js");
  let clock = 0;
  const guard = createApiGuard({ apiUrl: API, mapPerMinute: 25, pauseMs: 300000, now: () => clock });
  let sent = 0;
  const f = guard.wrap(async () => { sent += 1; return { status: 200 }; });
  for (let i = 0; i < 25; i++) { await f(`${API}/api/0.6/map.json?bbox=${i}`); clock += 1000; }
  await f(`${API}/api/0.6/way/1/full.json`);
  await assert.rejects(f(`${API}/api/0.6/map.json?bbox=x`), err => err instanceof ApiPausedError && err.reason === "rate" && err.until === 60000);
  assert.deepEqual(guard.status(), { reason: "rate", until: 60000 });
  assert.equal(sent, 26);
  clock = 60001;
  await f(`${API}/api/0.6/map.json?bbox=y`);
  assert.equal(sent, 27);
  await f("https://tiles.example/a.pbf");
});

test("a 509 stops every API call for five minutes, even after a reload", async () => {
  const { createApiGuard, ApiPausedError } = await load("api-guard.js");
  const storage = memoryStorage();
  let clock = 1000;
  const make = () => createApiGuard({ apiUrl: API, mapPerMinute: 25, pauseMs: 300000, now: () => clock, storage, key: "pause" });
  let status = 509;
  let sent = 0;
  const guard = make();
  const f = guard.wrap(async () => { sent += 1; return { status }; });
  assert.equal((await f(`${API}/api/0.6/map.json`)).status, 509);
  status = 200;
  await assert.rejects(f(`${API}/api/0.6/way/1/full.json`), err => err instanceof ApiPausedError && err.reason === "bandwidth" && err.until === 301000);
  const again = make().wrap(async () => { sent += 1; return { status: 200 }; });
  await assert.rejects(again(`${API}/api/0.6/user/details.json`), ApiPausedError);
  assert.equal(sent, 1);
  clock = 301001;
  await again(`${API}/api/0.6/user/details.json`);
  assert.equal(sent, 2);
});

test("the guard sits in front of the queue, so refused calls are never counted or queued", async () => {
  const { createApiGuard } = await load("api-guard.js");
  const { createApiMeter, installApiChain } = await load("api-meter.js");
  const { limitConcurrency } = await load("api-queue.js");
  const meter = createApiMeter({ storage: memoryStorage(), env: "dev", apiUrl: API });
  const guard = createApiGuard({ apiUrl: API, mapPerMinute: 1, pauseMs: 1000 });
  const target = { fetch: async () => new Response("ok") };
  installApiChain(target, { apiUrl: API, meter, guard, limit: limitConcurrency });
  await target.fetch(`${API}/api/0.6/map.json?a`);
  await assert.rejects(target.fetch(`${API}/api/0.6/map.json?b`));
  assert.equal(meter.stats().total, 1);
});

test("editing too fast warns first, then pauses if it happens again soon after", async () => {
  const { createPace } = await load("pace.js");
  const storage = memoryStorage();
  let clock = 0;
  const options = { storage, env: "dev", windowMs: 60000, maxStreets: 6, repeatMs: 600000, cooldownMs: 60000, now: () => clock };
  let pace = createPace(options);
  for (let i = 0; i < 6; i++) { pace.record(); clock += 1000; }
  assert.deepEqual(pace.status(), { count: 6, tooFast: false, cooldownLeftMs: 0 });
  pace.record();
  assert.equal(pace.status().tooFast, true);
  pace.record();
  assert.equal(pace.status().cooldownLeftMs, 0);
  clock += 61000;
  assert.equal(pace.status().tooFast, false);
  pace = createPace(options);
  for (let i = 0; i < 7; i++) { pace.record(); clock += 500; }
  const status = pace.status();
  assert.equal(status.tooFast, false);
  assert.ok(status.cooldownLeftMs > 58000 && status.cooldownLeftMs <= 60000, String(status.cooldownLeftMs));
  clock += 61000;
  assert.equal(pace.status().cooldownLeftMs, 0);
});

test("a fast burst long after the last warning only warns again", async () => {
  const { createPace } = await load("pace.js");
  let clock = 0;
  const pace = createPace({ storage: memoryStorage(), env: "dev", windowMs: 60000, maxStreets: 2, repeatMs: 600000, cooldownMs: 60000, now: () => clock });
  for (let i = 0; i < 3; i++) pace.record();
  assert.equal(pace.status().tooFast, true);
  clock += 700000;
  assert.equal(pace.status().tooFast, false);
  for (let i = 0; i < 3; i++) pace.record();
  assert.deepEqual(pace.status(), { count: 3, tooFast: true, cooldownLeftMs: 0 });
});

test("the choice waits for the orthophoto, the look time and the pace pause, never for a queued street", async () => {
  const { editLock, detailView } = await load("panel.js");
  const base = { kind: "way", editable: true, seenWhole: true, basemapOk: true, lookLeftMs: 0, paceLeftMs: 0, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  assert.equal(editLock(base), null);
  assert.equal(editLock({ ...base, basemapOk: false, lookLeftMs: 3000 }), "basemap");
  assert.equal(editLock({ ...base, lookLeftMs: 2100 }), "look");
  assert.equal(editLock({ ...base, lookLeftMs: 2100, paceLeftMs: 40000 }), "pace");
  assert.equal(editLock({ ...base, lookLeftMs: 2100, paceLeftMs: 40000, queued: { wayId: 5 } }), null);
  assert.equal(editLock({ ...base, basemapOk: false, queued: { wayId: 5 } }), "basemap");
  for (const lang of ["fr", "en", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const render = state => String(detailView(state, i18n, "https://x", { autoQueue: true }));
    assert.match(render({ ...base, basemapOk: false }), /data-edit-action="basemap"/);
    assert.match(render({ ...base, lookLeftMs: 2100 }), /edit-look/);
    assert.match(render({ ...base, paceLeftMs: 40000 }), /role="status"/);
    assert.match(render({ ...base, tooFast: true }), /role="alert"/);
    assert.match(render({ ...base, lookLeftMs: 2100 }), /data-value="separate"[^>]*disabled/);
    assert.deepEqual(warnings, []);
  }
  const fr = i18nFor("fr");
  assert.match(String(detailView({ ...base, lookLeftMs: 2100 }, fr, "https://x", {})), /encore 3 secondes/);
  assert.match(String(detailView({ ...base, tooFast: true }, fr, "https://x", {})), /privilégiez la qualité plutôt que la quantité/);
});

test("paused API calls get a message with the time they resume", async () => {
  const { ApiPausedError } = await load("api-guard.js");
  const { errorKind, errorMessage } = await load("errors.js");
  const until = new Date(2026, 10, 14, 7, 5).getTime();
  const fr = i18nFor("fr");
  assert.equal(errorKind(new ApiPausedError("rate", until)), "pausedRate");
  assert.match(errorMessage(new ApiPausedError("rate", until), fr.t), /07:05/);
  assert.match(errorMessage(new ApiPausedError("bandwidth", until), fr.t), /limite les téléchargements.*07:05/);
});

test("editing settings: orthophoto only, the three walking layers forced on, sidewalk tags allowed", async () => {
  const { SETTINGS } = await load("env.js");
  assert.deepEqual([...SETTINGS.editBasemaps], ["urbis-ortho"]);
  assert.deepEqual([...SETTINGS.editRequiredLayers], ["highway-pedestrian", "highway-footway", "highway-path"]);
  assert.deepEqual([...SETTINGS.editOptionalLayers], ["sidewalk-roads"]);
  assert.equal(SETTINGS.minLookMs, 4000);
  assert.equal(SETTINGS.mapCallsPerMinute, 25);
  assert.equal(SETTINGS.pauseAfter509Ms, 300000);
});
