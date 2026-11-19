const test = require("node:test");
const assert = require("node:assert/strict");
const { loadEdit: load } = require("./helpers.js");

const DEV_API = "https://master.apis.dev.openstreetmap.org";

function fakeDocument(href, editEnv = "dev") {
  return { location: { href }, documentElement: { dataset: editEnv === null ? {} : { editEnv } } };
}

test("the page environment comes from the html attribute and the landing page sits next to it", async () => {
  const { envFromDocument, SETTINGS } = await load("env.js");
  const env = envFromDocument(fakeDocument("https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/devtest.html?x=1#17/50.8/4.4"));
  assert.equal(env.name, "dev");
  assert.equal(env.apiUrl, DEV_API);
  assert.equal(env.redirectUrl, "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/land.html");
  assert.equal(env.reviewZoom, SETTINGS.reviewZoom);
  assert.ok(Object.isFrozen(env));
});

test("the prod beta page lands on its own page, next to it, never on the dev one", async () => {
  const { envFromDocument, ENVS } = await load("env.js");
  const env = envFromDocument(fakeDocument("https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/beta.html#17/50.8/4.4", "prod"));
  assert.equal(env.name, "prod");
  assert.equal(env.apiUrl, "https://api.openstreetmap.org");
  assert.equal(env.redirectUrl, "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/beta-land.html");
  assert.notEqual(ENVS.dev.landingPage, ENVS.prod.landingPage);
  assert.equal(env.clientId, "");
  assert.equal(env.apiMeter, true);
});

test("review-zoom in the address changes or switches off the close-up check", async () => {
  const { envFromDocument } = await load("env.js");
  const page = query => fakeDocument(`https://example.org/test-api/devtest.html${query}#17/50.8/4.4`);
  assert.equal(envFromDocument(page("?review-zoom=18.6")).reviewZoom, 18.6);
  for (const off of ["?review-zoom=0", "?review-zoom=", "?review-zoom=abc", "?review-zoom=23", "?review-zoom=14.9"]) {
    assert.equal(envFromDocument(page(off)).reviewZoom, null, off);
  }
});

test("a page without an edit environment, or with an unknown one, refuses to start", async () => {
  const { envFromDocument } = await load("env.js");
  assert.throws(() => envFromDocument(fakeDocument("https://example.org/index.html", null)), /unknown edit environment/);
  assert.throws(() => envFromDocument(fakeDocument("https://example.org/index.html", "constructor")), /unknown edit environment/);
  assert.throws(() => envFromDocument(fakeDocument("https://example.org/index.html", "__proto__")), /unknown edit environment/);
});

test("a changeset never exceeds the API's 50 ways, whatever the settings say", async () => {
  const { resolveEnv, SETTINGS, MAX_WAYS_PER_CHANGESET } = await load("env.js");
  const env = resolveEnv("dev", "https://example.org/devtest.html", { ...SETTINGS, maxWaysPerChangeset: 500 });
  assert.equal(env.maxWaysPerChangeset, MAX_WAYS_PER_CHANGESET);
});

test("the API never sees more than two calls at once, whatever the settings say", async () => {
  const { resolveEnv, SETTINGS, MAX_CONCURRENT_API } = await load("env.js");
  const page = "https://example.org/devtest.html";
  assert.equal(MAX_CONCURRENT_API, 2);
  assert.ok(SETTINGS.maxConcurrentApi >= 1 && SETTINGS.maxConcurrentApi <= MAX_CONCURRENT_API);
  assert.equal(resolveEnv("dev", page, { ...SETTINGS, maxConcurrentApi: 5 }).maxConcurrentApi, MAX_CONCURRENT_API);
  assert.equal(resolveEnv("prod", page, { ...SETTINGS, maxConcurrentApi: 0 }).maxConcurrentApi, 1);
  assert.equal(resolveEnv("dev", page).maxConcurrentApi, SETTINGS.maxConcurrentApi);
});

function fakeOsm({ token = "abc", authHeader, apiUrl = DEV_API } = {}) {
  return {
    getConfig: () => ({ apiUrl, ...(authHeader ? { authHeader } : {}) }),
    getAuthToken: () => token,
    getUser: () => "kept",
  };
}

test("closing a changeset sends the bearer token, or the configured header, to its own URL", async () => {
  const { createClient, authorizationHeader } = await load("client.js");
  const calls = [];
  const client = createClient(fakeOsm(), async (url, init) => { calls.push([url, init]); return { ok: true }; });
  await client.closeChangeset("42/../../user");
  assert.equal(calls[0][0], `${DEV_API}/api/0.6/changeset/42%2F..%2F..%2Fuser/close`);
  assert.equal(calls[0][1].method, "PUT");
  assert.equal(calls[0][1].headers.Authorization, "Bearer abc");
  assert.equal(authorizationHeader(fakeOsm({ authHeader: "Basic eA==" })), "Basic eA==");
  assert.equal(authorizationHeader(fakeOsm({ token: null })), "");
  assert.equal(client.getUser(), "kept");
  assert.ok(Object.isFrozen(client));
});

test("a refused close keeps the status, even when the body cannot be read", async () => {
  const { createClient, apiError } = await load("client.js");
  const client = createClient(fakeOsm(), async () => ({ ok: false, status: 409, text: async () => "The changeset 42 was closed" }));
  await assert.rejects(client.closeChangeset(42), err => err.cause === 409 && /was closed/.test(err.message));
  const unreadable = await apiError({ status: 503, text: async () => { throw new Error("stream"); } });
  assert.equal(unreadable.cause, 503);
  assert.equal(unreadable.message, "OSM API: ");
});

test("the guard also reads Request objects and lets other hosts through untouched", async () => {
  const { createApiGuard, ApiPausedError } = await load("api-guard.js");
  let clock = 0;
  const guard = createApiGuard({ apiUrl: DEV_API, mapPerMinute: 1, pauseMs: 1000, now: () => clock });
  const seen = [];
  const f = guard.wrap(async (input) => { seen.push(input); return { status: 200 }; });
  await f({ url: `${DEV_API}/api/0.6/map.json?bbox=1`, method: "GET" });
  await assert.rejects(f({ url: `${DEV_API}/api/0.6/map.json?bbox=2` }), ApiPausedError);
  await f({ url: "https://tiles.example/1.pbf" });
  await f(undefined);
  assert.equal(seen.length, 3);
  assert.deepEqual(guard.status(), { reason: "rate", until: 60000 });
  clock = 60001;
  assert.equal(guard.status(), null);
});

test("a broken or unavailable storage never blocks or breaks the guard", async () => {
  const { createApiGuard } = await load("api-guard.js");
  const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("quota"); } };
  const guard = createApiGuard({ apiUrl: DEV_API, mapPerMinute: 25, pauseMs: 1000, now: () => 5, storage: throwing, key: "bpn.apiPause.dev" });
  assert.equal(guard.status(), null);
  const f = guard.wrap(async () => ({ status: 509 }));
  await f(`${DEV_API}/api/0.6/user/details.json`);
  assert.deepEqual(guard.status(), { reason: "bandwidth", until: 1005 });
  const stale = { getItem: () => "not a number", setItem() {} };
  assert.equal(createApiGuard({ apiUrl: DEV_API, mapPerMinute: 25, pauseMs: 1000, now: () => 5, storage: stale, key: "k" }).status(), null);
  const past = { getItem: () => "3", setItem() {} };
  assert.equal(createApiGuard({ apiUrl: DEV_API, mapPerMinute: 25, pauseMs: 1000, now: () => 5, storage: past, key: "k" }).status(), null);
});

test("listeners hear a pause and can stop listening", async () => {
  const { createApiGuard } = await load("api-guard.js");
  const guard = createApiGuard({ apiUrl: DEV_API, mapPerMinute: 25, pauseMs: 1000, now: () => 0 });
  let heard = 0;
  const stop = guard.onChange(() => { heard += 1; });
  const f = guard.wrap(async () => ({ status: 509 }));
  await f(`${DEV_API}/api/0.6/way/1.json`);
  stop();
  await assert.rejects(f(`${DEV_API}/api/0.6/way/1.json`));
  assert.equal(heard, 1);
});
