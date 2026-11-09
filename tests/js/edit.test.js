const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");

globalThis.html = html;

const EDIT = path.join(__dirname, "..", "..", "edit");
const load = name => import(pathToFileURL(path.join(EDIT, name)).href);

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: k => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: k => data.delete(k),
    dump: () => Object.fromEntries(data),
  };
}

function fakeOsm({ loginImpl } = {}) {
  const calls = [];
  return {
    calls,
    logout: () => calls.push(["logout"]),
    isLoggedIn: () => true,
    login: async (opts) => { calls.push(["login", opts]); if (loginImpl) await loginImpl(opts); },
  };
}

const DEV_PAGE = "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/devtest.html#17/50.8/4.5";

test("the dev environment talks to the dev API and lands next to its page", async () => {
  const { resolveEnv } = await load("env.js");
  const env = resolveEnv("dev", DEV_PAGE);
  assert.equal(env.apiUrl, "https://master.apis.dev.openstreetmap.org");
  assert.equal(env.redirectUrl, "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/land.html");
  assert.deepEqual([...env.scopes], ["read_prefs", "write_api"]);
  assert.equal(env.candidateMinZoom, 17);
});

test("dev and prod never share an API and an unknown environment is refused", async () => {
  const { ENVS, resolveEnv } = await load("env.js");
  assert.notEqual(ENVS.dev.apiUrl, ENVS.prod.apiUrl);
  assert.throws(() => resolveEnv("staging", DEV_PAGE), /unknown edit environment/);
  assert.throws(() => resolveEnv(undefined, DEV_PAGE), /unknown edit environment/);
});

test("the guard keeps a token issued for the same environment", async () => {
  const { guardEnvironment, AUTH_KEY, ENV_KEY } = await load("auth.js");
  const storage = memoryStorage({ [AUTH_KEY]: "{}", [ENV_KEY]: "dev" });
  const osm = fakeOsm();
  assert.equal(guardEnvironment({ env: "dev", storage, osm }), false);
  assert.deepEqual(osm.calls, []);
  assert.equal(storage.getItem(AUTH_KEY), "{}");
});

test("the guard logs out a token issued for another environment", async () => {
  const { guardEnvironment, AUTH_KEY, ENV_KEY } = await load("auth.js");
  for (const stored of ["prod", null]) {
    const storage = memoryStorage({ [AUTH_KEY]: "{}", ...(stored ? { [ENV_KEY]: stored } : {}) });
    const osm = fakeOsm();
    assert.equal(guardEnvironment({ env: "dev", storage, osm }), true);
    assert.deepEqual(osm.calls, [["logout"]]);
    assert.equal(storage.getItem(AUTH_KEY), null);
    assert.equal(storage.getItem(ENV_KEY), null);
  }
});

test("the guard clears a stale environment marker when there is no token", async () => {
  const { guardEnvironment, ENV_KEY } = await load("auth.js");
  const storage = memoryStorage({ [ENV_KEY]: "prod" });
  assert.equal(guardEnvironment({ env: "dev", storage, osm: fakeOsm() }), false);
  assert.equal(storage.getItem(ENV_KEY), null);
});

test("the landing page accepts a pending login only once, for its own API, while fresh", async () => {
  const { consumePending, markPending, PENDING_KEY } = await load("auth.js");
  const api = "https://master.apis.dev.openstreetmap.org";
  const ttlMs = 1000;
  const storage = memoryStorage();
  markPending({ storage, env: "dev", apiUrl: api, now: 5000, tab: "a" });
  assert.equal(consumePending({ storage, apiUrl: api, now: 5500, ttlMs }), "ok");
  assert.equal(storage.getItem(PENDING_KEY), null);
  assert.equal(consumePending({ storage, apiUrl: api, now: 5500, ttlMs }), "missing");

  markPending({ storage, env: "prod", apiUrl: "https://api.openstreetmap.org", now: 5000, tab: "a" });
  assert.equal(consumePending({ storage, apiUrl: api, now: 5100, ttlMs }), "mismatch");

  markPending({ storage, env: "dev", apiUrl: api, now: 5000, tab: "a" });
  assert.equal(consumePending({ storage, apiUrl: api, now: 6001, ttlMs }), "expired");

  markPending({ storage, env: "dev", apiUrl: api, now: 9000, tab: "a" });
  assert.equal(consumePending({ storage, apiUrl: api, now: 5000, ttlMs }), "expired");

  storage.setItem(PENDING_KEY, "{not json");
  assert.equal(consumePending({ storage, apiUrl: api, now: 5000, ttlMs }), "missing");
});

const ENV = {
  name: "dev",
  apiUrl: "https://master.apis.dev.openstreetmap.org",
  clientId: "client",
  redirectUrl: "https://example.org/test-api/land.html",
  scopes: ["read_prefs", "write_api"],
  authPendingTtlMs: 1000,
};

test("a successful login marks the environment and clears the pending marker", async () => {
  const { login, ENV_KEY, PENDING_KEY } = await load("auth.js");
  const storage = memoryStorage();
  let pendingDuringLogin = null;
  const osm = fakeOsm({ loginImpl: () => { pendingDuringLogin = JSON.parse(storage.getItem(PENDING_KEY)); } });
  await login({ osm, storage, env: ENV, tab: "t1", now: () => 100 });
  assert.deepEqual(osm.calls[0], ["login", { mode: "popup", clientId: "client", redirectUrl: ENV.redirectUrl, scopes: ["read_prefs", "write_api"] }]);
  assert.deepEqual(pendingDuringLogin, { env: "dev", apiUrl: ENV.apiUrl, ts: 100, tab: "t1" });
  assert.equal(storage.getItem(ENV_KEY), "dev");
  assert.equal(storage.getItem(PENDING_KEY), null);
});

test("a failed login leaves no environment marker and no pending marker", async () => {
  const { login, ENV_KEY, PENDING_KEY } = await load("auth.js");
  const storage = memoryStorage();
  const osm = fakeOsm({ loginImpl: () => { throw new Error("access_denied"); } });
  await assert.rejects(login({ osm, storage, env: ENV, tab: "t1", now: () => 100 }), /access_denied/);
  assert.equal(storage.getItem(ENV_KEY), null);
  assert.equal(storage.getItem(PENDING_KEY), null);
});

test("only another tab's fresh login blocks a new one", async () => {
  const { login, markPending } = await load("auth.js");
  const fresh = memoryStorage();
  markPending({ storage: fresh, env: "dev", apiUrl: ENV.apiUrl, now: 100, tab: "other" });
  await assert.rejects(login({ osm: fakeOsm(), storage: fresh, env: ENV, tab: "me", now: () => 500 }), /login-pending/);

  const mine = memoryStorage();
  markPending({ storage: mine, env: "dev", apiUrl: ENV.apiUrl, now: 100, tab: "me" });
  await login({ osm: fakeOsm(), storage: mine, env: ENV, tab: "me", now: () => 500 });

  const stale = memoryStorage();
  markPending({ storage: stale, env: "dev", apiUrl: ENV.apiUrl, now: 100, tab: "other" });
  await login({ osm: fakeOsm(), storage: stale, env: ENV, tab: "me", now: () => 5000 });
});

test("a tab keeps its id across reloads", async () => {
  const { tabId } = await load("auth.js");
  const session = memoryStorage();
  const first = tabId(session, () => "abc");
  assert.equal(first, "abc");
  assert.equal(tabId(session, () => "zzz"), "abc");
});

test("being logged in requires a token issued for this environment", async () => {
  const { isLoggedIn, ENV_KEY } = await load("auth.js");
  const osm = fakeOsm();
  assert.equal(isLoggedIn({ osm, storage: memoryStorage({ [ENV_KEY]: "dev" }), env: ENV }), true);
  assert.equal(isLoggedIn({ osm, storage: memoryStorage({ [ENV_KEY]: "prod" }), env: ENV }), false);
  assert.equal(isLoggedIn({ osm, storage: memoryStorage(), env: ENV }), false);
});

test("logout removes the token and the environment marker", async () => {
  const { logout, AUTH_KEY, ENV_KEY } = await load("auth.js");
  const storage = memoryStorage({ [AUTH_KEY]: "{}", [ENV_KEY]: "dev" });
  const osm = fakeOsm();
  logout({ osm, storage });
  assert.deepEqual(osm.calls, [["logout"]]);
  assert.deepEqual(storage.dump(), {});
});

test("the whitelist keeps residential roads without any sidewalk key", async () => {
  const { isEditableCandidate } = await load("whitelist.js");
  assert.equal(isEditableCandidate({ highway: "residential", name: "Rue A" }), true);
  assert.equal(isEditableCandidate({ highway: "residential", sidewalk: "no" }), false);
  assert.equal(isEditableCandidate({ highway: "residential", "sidewalk:left": "separate" }), false);
  assert.equal(isEditableCandidate({ highway: "residential", "sidewalk:both": "separate" }), false);
  assert.equal(isEditableCandidate({ highway: "residential", "sidewalk:right:surface": "asphalt" }), false);
  assert.equal(isEditableCandidate({ highway: "residential", sidewalks: "x" }), true);
  assert.equal(isEditableCandidate({ highway: "tertiary" }), false);
  assert.equal(isEditableCandidate({ highway: "service" }), false);
  assert.equal(isEditableCandidate(undefined), false);
});

test("candidates are built from live map data only when every node is known", async () => {
  const { candidatesFromMapData } = await load("candidates.js");
  const features = [
    { type: "node", id: 1, lat: 50.80, lon: 4.50 },
    { type: "node", id: 2, lat: 50.81, lon: 4.51 },
    { type: "node", id: 3, lat: 50.82, lon: 4.52 },
    { type: "way", id: 10, version: 3, nodes: [1, 2], tags: { highway: "residential", name: "Rue A" } },
    { type: "way", id: 11, version: 1, nodes: [2, 3], tags: { highway: "residential", "sidewalk:both": "no" } },
    { type: "way", id: 12, version: 1, nodes: [2, 3], tags: { highway: "tertiary" } },
    { type: "way", id: 13, version: 1, nodes: [2, 99], tags: { highway: "residential" } },
    { type: "way", id: 14, version: 1, nodes: [1, 3], tags: { highway: "residential" }, visible: false },
    { type: "way", id: 15, version: 1, nodes: [1], tags: { highway: "residential" } },
    { type: "relation", id: 20, members: [], tags: { type: "route" } },
  ];
  const collection = candidatesFromMapData(features);
  assert.equal(collection.type, "FeatureCollection");
  assert.deepEqual(collection.features, [{
    type: "Feature",
    geometry: { type: "LineString", coordinates: [[4.50, 50.80], [4.51, 50.81]] },
    properties: { osm_id: 10, version: 3, highway: "residential", name: "Rue A" },
  }]);
  assert.deepEqual(candidatesFromMapData(undefined).features, []);
});

test("the map bbox is sent as west,south,east,north", async () => {
  const { bboxString } = await load("candidates.js");
  const bounds = { getWest: () => 4.5, getSouth: () => 50.8, getEast: () => 4.51, getNorth: () => 50.81 };
  assert.equal(bboxString(bounds), "4.5000000,50.8000000,4.5100000,50.8100000");
});

test("the way detail escapes live tag values and links to the environment's site", async () => {
  const { detailView } = await load("panel.js");
  const out = String(detailView({
    kind: "way",
    editable: true,
    way: { id: 42, version: 7, user: "<b>u</b>", timestamp: "2026-11-09T10:00:00Z", tags: { name: `"><img src=x onerror=alert(1)>`, highway: "residential" } },
  }, i18nFor("fr"), "https://master.apis.dev.openstreetmap.org"));
  assert.match(out, /href="https:\/\/master\.apis\.dev\.openstreetmap\.org\/way\/42"/);
  assert.doesNotMatch(out, /<img/);
  assert.doesNotMatch(out, /<b>u<\/b>/);
  assert.match(out, />7</);
  assert.match(out, /éditable/);
});

test("the panel speaks every published language without a missing key", async () => {
  const { authView, detailView, statusView } = await load("panel.js");
  for (const lang of ["en", "fr", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const outputs = [
      ...["disabled", "unconfigured", "anonymous", "pending", "waiting"].map(kind => authView({ kind }, i18n)),
      authView({ kind: "logged", name: "x" }, i18n),
      statusView({ kind: "zoom", minZoom: 17 }, i18n),
      statusView({ kind: "loading" }, i18n),
      statusView({ kind: "ready", count: 1 }, i18n),
      statusView({ kind: "ready", count: 3 }, i18n),
      statusView({ kind: "error", message: "x" }, i18n),
      detailView({ kind: "loading" }, i18n, "https://x"),
      detailView({ kind: "error", message: "x" }, i18n, "https://x"),
      detailView({ kind: "way", editable: false, way: { id: 1, version: 1, tags: {} } }, i18n, "https://x"),
    ].map(String);
    for (const text of outputs) assert.doesNotMatch(text, /\bedit\.[a-z]+\.[A-Za-z_]+/, `${lang}: ${text}`);
    assert.deepEqual(warnings, []);
  }
});

test("a login started from another tab disables the button", async () => {
  const { authView } = await load("panel.js");
  assert.match(String(authView({ kind: "pending" }, i18nFor("fr"))), /data-edit-action="login" disabled/);
  assert.doesNotMatch(String(authView({ kind: "waiting" }, i18nFor("fr"))), /disabled/);
});

test("no OSM call can run before the environment guard", () => {
  const src = fs.readFileSync(path.join(EDIT, "main.js"), "utf8");
  const guard = src.indexOf("guardEnvironment({");
  const firstCall = src.search(/\bosm\.\w+\(/);
  assert.ok(guard > 0);
  assert.ok(firstCall > guard, "an osm.* call appears before guardEnvironment");
  assert.doesNotMatch(src.slice(0, guard), /\bOSM\.\w+\(/);
  assert.doesNotMatch(fs.readFileSync(path.join(EDIT, "land.js"), "utf8"), /\bOSM\b/);
});
