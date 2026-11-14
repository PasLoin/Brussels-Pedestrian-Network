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

const paceOptions = (storage, clock) => ({ storage, env: "dev", windowMs: 60000, maxMeters: 600, blockMeters: 900, repeatMs: 300000, cooldownMs: 60000, now: () => clock.t });

test("editing too fast is measured in metres, so a street cut into short segments is not penalised", async () => {
  const { createPace } = await load("pace.js");
  const clock = { t: 0 };
  const pace = createPace(paceOptions(memoryStorage(), clock));
  for (let i = 0; i < 12; i++) { pace.record(40); clock.t += 1000; }
  assert.deepEqual(pace.status(), { meters: 480, tooFast: false, cooldownLeftMs: 0 });
  pace.record(150);
  assert.equal(pace.status().tooFast, true);
});

test("past 600 m a minute it only warns; a steady pace around the threshold is never blocked", async () => {
  const { createPace } = await load("pace.js");
  const clock = { t: 0 };
  const pace = createPace(paceOptions(memoryStorage(), clock));
  for (let i = 0; i < 60; i++) { clock.t += 10000; pace.record(110); }
  const status = pace.status();
  assert.equal(status.cooldownLeftMs, 0);
  assert.ok(status.meters > 600 && status.meters <= 900, String(status.meters));
  assert.equal(status.tooFast, true);
});

test("past 900 m a minute within five minutes of a warning it pauses for a minute", async () => {
  const { createPace } = await load("pace.js");
  const clock = { t: 0 };
  const pace = createPace(paceOptions(memoryStorage(), clock));
  for (let i = 0; i < 7; i++) { pace.record(100); clock.t += 1000; }
  assert.equal(pace.status().tooFast, true);
  for (let i = 0; i < 3; i++) { pace.record(100); clock.t += 1000; }
  const status = pace.status();
  assert.equal(status.tooFast, false);
  assert.ok(status.cooldownLeftMs > 58000 && status.cooldownLeftMs <= 60000, String(status.cooldownLeftMs));
  clock.t += 61000;
  assert.equal(pace.status().cooldownLeftMs, 0);
});

test("a single long street never blocks on its own, and a rush long after the warning only warns again", async () => {
  const { createPace } = await load("pace.js");
  const clock = { t: 0 };
  const pace = createPace(paceOptions(memoryStorage(), clock));
  pace.record(1200);
  assert.deepEqual(pace.status(), { meters: 1200, tooFast: true, cooldownLeftMs: 0 });
  clock.t += 400000;
  for (let i = 0; i < 7; i++) pace.record(100);
  assert.deepEqual(pace.status(), { meters: 700, tooFast: true, cooldownLeftMs: 0 });
});

test("the pause survives a reload", async () => {
  const { createPace } = await load("pace.js");
  const storage = memoryStorage();
  const clock = { t: 0 };
  const pace = createPace(paceOptions(storage, clock));
  for (let i = 0; i < 10; i++) { pace.record(100); clock.t += 500; }
  assert.ok(createPace(paceOptions(storage, clock)).status().cooldownLeftMs > 0);
});

test("an old pace record in the former format is ignored rather than breaking the page", async () => {
  const { createPace } = await load("pace.js");
  const storage = memoryStorage();
  storage.setItem("bpn.pace.dev", JSON.stringify({ events: [1, 2, 3], warnedAt: 0 }));
  const pace = createPace({ ...paceOptions(storage, { t: 10 }) });
  assert.equal(pace.status().meters, 0);
});

test("the look time grows with the street length up to three seconds", async () => {
  const { lookTimeMs } = await load("look.js");
  const settings = { minLookMs: 3000, lookMsPerMeter: 30 };
  assert.equal(lookTimeMs(20, settings), 600);
  assert.equal(lookTimeMs(50, settings), 1500);
  assert.equal(lookTimeMs(100, settings), 3000);
  assert.equal(lookTimeMs(800, settings), 3000);
  assert.equal(lookTimeMs(undefined, settings), 0);
});

test("the choice waits for the orthophoto, the look time and the pace pause, never for a queued street", async () => {
  const { editLock, detailView } = await load("panel.js");
  const base = { kind: "way", editable: true, seenWhole: true, basemapOk: true, lookLeftMs: 0, paceLeftMs: 0, lookMode: "block", way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  assert.equal(editLock(base), null);
  assert.equal(editLock({ ...base, basemapOk: false, lookLeftMs: 3000 }), "basemap");
  assert.equal(editLock({ ...base, lookLeftMs: 2100 }), "look");
  assert.equal(editLock({ ...base, lookLeftMs: 2100, paceLeftMs: 40000 }), "pace");
  assert.equal(editLock({ ...base, lookLeftMs: 2100, paceLeftMs: 40000, queued: { wayId: 5 } }), null);
  assert.equal(editLock({ ...base, basemapOk: false, queued: { wayId: 5 } }), "basemap");
  assert.equal(editLock({ ...base, lookLeftMs: 2100, lookMode: "warn" }), null);
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
  const warned = String(detailView({ ...base, lookLeftMs: 2100, lookMode: "warn" }, fr, "https://x", {}));
  assert.match(warned, /encore 3 secondes/);
  assert.doesNotMatch(warned, /data-value="separate"[^>]*disabled/);
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
  assert.equal(SETTINGS.minLookMs, 3000);
  assert.equal(SETTINGS.lookMsPerMeter, 30);
  assert.equal(SETTINGS.lookMode, "warn");
  assert.equal(SETTINGS.paceMaxMeters, 600);
  assert.equal(SETTINGS.paceBlockMeters, 900);
  assert.equal(SETTINGS.paceRepeatMs, 300000);
  assert.equal(SETTINGS.mapCallsPerMinute, 25);
  assert.equal(SETTINGS.pauseAfter509Ms, 300000);
});
