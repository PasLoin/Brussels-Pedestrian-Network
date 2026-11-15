const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);
const API = "https://dev.example";

function memoryStorage() {
  const data = new Map();
  return { getItem: k => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)) };
}

test("every OSM API path osm-api and the editor use gets its own counter", async () => {
  const { classifyApiCall } = await load("api-meter.js");
  const cases = [
    ["/api/0.6/map.json?bbox=1,2,3,4", "GET", "map"],
    ["/api/0.6/way/12/full.json", "GET", "wayFull"],
    ["/api/0.6/way/12.json", "GET", "way"],
    ["/api/0.6/ways.json?ways=1,2", "GET", "ways"],
    ["/api/0.6/nodes.json?nodes=1,2", "GET", "nodes"],
    ["/api/0.6/changeset/create", "PUT", "changesetCreate"],
    ["/api/0.6/changeset/5/upload", "POST", "upload"],
    ["/api/0.6/changeset/5/close", "PUT", "changesetClose"],
    ["/api/0.6/changesets.json?user=1&open=true", "GET", "changesets"],
    ["/api/0.6/user/details.json", "GET", "user"],
    ["/oauth2/token?code=x", "POST", "oauth"],
    ["/api/0.6/capabilities.json", "GET", "other"],
  ];
  for (const [p, method, kind] of cases) assert.equal(classifyApiCall(API + p, method), kind, p);
  assert.equal(classifyApiCall("not a url"), "other");
});

test("the meter counts calls, the last minute, the peaks and the failures, and survives a reload", async () => {
  const { createApiMeter } = await load("api-meter.js");
  const storage = memoryStorage();
  let clock = 1000;
  const meter = createApiMeter({ storage, env: "dev", apiUrl: API, now: () => clock });
  const pending = [];
  const fake = (url) => new Promise(resolve => pending.push(() => resolve({ status: url.includes("509") ? 509 : 200 })));
  const f = meter.wrap(fake);
  const a = f(`${API}/api/0.6/map.json?bbox=1`);
  const b = f(`${API}/api/0.6/way/1/full.json`);
  const c = f(`${API}/api/0.6/map.json?509`);
  assert.equal(meter.stats().inFlight, 3);
  pending.splice(0).forEach(r => r());
  await Promise.all([a, b, c]);
  const s = meter.stats();
  assert.equal(s.total, 3);
  assert.deepEqual(s.byKind, { map: 2, wayFull: 1 });
  assert.deepEqual(s.byStatus, { 509: 1 });
  assert.equal(s.peakInFlight, 3);
  assert.equal(s.lastMinute, 3);
  assert.equal(s.peakPerMinute, 3);
  assert.equal(s.inFlight, 0);
  clock += 61 * 1000;
  assert.equal(meter.stats().lastMinute, 0);
  const again = createApiMeter({ storage, env: "dev", apiUrl: API, now: () => clock });
  assert.equal(again.stats().total, 3);
  assert.equal(again.stats().peakInFlight, 3);
  again.reset();
  assert.equal(again.stats().total, 0);
});

test("other hosts are not counted and a network failure is", async () => {
  const { createApiMeter, installApiMeter } = await load("api-meter.js");
  const meter = createApiMeter({ storage: memoryStorage(), env: "dev", apiUrl: API });
  const target = { fetch: async url => { if (url.includes("down")) throw new TypeError("offline"); return { status: 200 }; } };
  const uninstall = installApiMeter(target, meter);
  await target.fetch("https://tiles.example/x.pbf");
  await assert.rejects(target.fetch(`${API}/api/0.6/map.json?down`));
  assert.equal(meter.stats().total, 1);
  assert.deepEqual(meter.stats().byStatus, { network: 1 });
  uninstall();
  await target.fetch(`${API}/api/0.6/map.json`);
  assert.equal(meter.stats().total, 1);
});

test("the meter panel speaks every language and flags more than two calls at once", async () => {
  globalThis.html = require("../../html.js").html;
  const { i18nFor } = require("./dictionaries.js");
  const { meterView } = await load("panel.js");
  const stats = { since: 0, total: 5, lastMinute: 2, peakPerMinute: 4, peakInFlight: 3, inFlight: 0, failures: 1,
    byKind: { map: 3, wayFull: 2 }, byStatus: { 509: 1 } };
  for (const lang of ["fr", "en", "nl"]) {
    const warnings = [];
    const out = String(meterView(stats, i18nFor(lang, warnings), { apiMeterWarnPerMinute: 30 }));
    assert.match(out, /<code>map<\/code><\/th><td>3/);
    assert.match(out, /way\/…\/full/);
    assert.match(out, /509 × 1/);
    assert.match(out, /<summary class="edit-warn">/);
    assert.match(out, /data-edit-action="meter-reset"/);
    assert.deepEqual(warnings, []);
  }
  const calm = String(meterView({ ...stats, peakInFlight: 2, byStatus: {} }, i18nFor("fr"), { apiMeterWarnPerMinute: 30 }));
  assert.match(calm, /<summary class="">/);
  assert.doesNotMatch(calm, /Réponses en erreur/);
  assert.equal(meterView(null, i18nFor("fr")), "");
});

test("with editing disabled every OSM API call is refused before leaving the page", async () => {
  const { blockApi, ApiBlockedError } = await load("api-meter.js");
  const seen = [];
  const target = { fetch: async url => { seen.push(url); return { status: 200 }; } };
  const unblock = blockApi(target, API);
  await assert.rejects(target.fetch(`${API}/api/0.6/map.json?bbox=1`), ApiBlockedError);
  await assert.rejects(target.fetch({ url: `${API}/api/0.6/user/details.json` }), ApiBlockedError);
  await target.fetch("https://tiles.example/1.pbf");
  assert.deepEqual(seen, ["https://tiles.example/1.pbf"]);
  unblock();
  await target.fetch(`${API}/api/0.6/map.json`);
  assert.equal(seen.length, 2);
});
