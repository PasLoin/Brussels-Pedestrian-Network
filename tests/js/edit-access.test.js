const test = require("node:test");
const assert = require("node:assert/strict");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");
const { loadEdit: load } = require("./helpers.js");

globalThis.html = html;

const DEV_API = "https://master.apis.dev.openstreetmap.org";
const PROD_API = "https://api.openstreetmap.org";

function fakeDocument(dataset) {
  return { location: { href: "https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/devtest.html" }, documentElement: { dataset: { editEnv: "dev", ...dataset } } };
}

test("allowed uids are read as positive integers, once each, and anything else is ignored", async () => {
  const { parseAllowedUids } = await load("access.js");
  assert.deepEqual(parseAllowedUids("12 34,56;12"), [12, 34, 56]);
  assert.deepEqual(parseAllowedUids(""), []);
  assert.deepEqual(parseAllowedUids(undefined), []);
  assert.deepEqual(parseAllowedUids("0 -3 1.5 abc 007 9999999999999 42"), [42]);
  assert.ok(Object.isFrozen(parseAllowedUids("1")));
});

test("the page is open unless the allowlist attribute says exactly on", async () => {
  const { accessFromDataset } = await load("access.js");
  assert.deepEqual(accessFromDataset({}), { restricted: false, uids: [] });
  assert.deepEqual(accessFromDataset({ editAllowlist: "off", editAllowedUids: "1 2" }), { restricted: false, uids: [] });
  assert.deepEqual(accessFromDataset({ editAllowlist: "on", editAllowedUids: "7 8" }), { restricted: true, uids: [7, 8] });
  assert.deepEqual(accessFromDataset({ editAllowlist: "on" }), { restricted: true, uids: [] });
});

test("with the allowlist on, only listed uids may write; with it off, everyone may", async () => {
  const { isAllowedUid } = await load("access.js");
  const open = { restricted: false, uids: [] };
  const closed = { restricted: true, uids: [77, 1234] };
  assert.equal(isAllowedUid(open, 5), true);
  assert.equal(isAllowedUid(open, null), true);
  assert.equal(isAllowedUid(closed, 77), true);
  assert.equal(isAllowedUid(closed, "1234"), true);
  assert.equal(isAllowedUid(closed, 78), false);
  assert.equal(isAllowedUid(closed, null), false);
  assert.equal(isAllowedUid(closed, undefined), false);
  assert.equal(isAllowedUid({ restricted: true, uids: [] }, 77), false);
});

test("the page environment carries the access read from the html attributes", async () => {
  const { envFromDocument } = await load("env.js");
  assert.deepEqual(envFromDocument(fakeDocument({})).access, { restricted: false, uids: [] });
  const env = envFromDocument(fakeDocument({ editAllowlist: "on", editAllowedUids: "77 12" }));
  assert.deepEqual(env.access, { restricted: true, uids: [77, 12] });
  assert.ok(Object.isFrozen(env.access));
});

test("only writes to the API of the page are writes: reads, OAuth and other hosts are not", async () => {
  const { isApiWrite } = await load("access.js");
  assert.equal(isApiWrite(`${DEV_API}/api/0.6/changeset/create`, "PUT", DEV_API), true);
  assert.equal(isApiWrite(`${DEV_API}/api/0.6/changeset/9/upload`, "post", DEV_API), true);
  assert.equal(isApiWrite(`${DEV_API}/api/0.6/changeset/9/close`, "PUT", DEV_API), true);
  assert.equal(isApiWrite(`${DEV_API}/api/0.6/map.json?bbox=1,2,3,4`, "GET", DEV_API), false);
  assert.equal(isApiWrite(`${DEV_API}/api/0.6/user/details.json`, undefined, DEV_API), false);
  assert.equal(isApiWrite(`${DEV_API}/oauth2/revoke`, "POST", DEV_API), false);
  assert.equal(isApiWrite(`${DEV_API}/oauth2/token`, "POST", DEV_API), false);
  assert.equal(isApiWrite(`${PROD_API}/api/0.6/changeset/create`, "PUT", DEV_API), false);
  assert.equal(isApiWrite(undefined, "PUT", DEV_API), false);
});

test("the write guard refuses API writes until the account is allowed, and lets everything else through", async () => {
  const { guardWrites, EditNotAllowedError } = await load("access.js");
  const calls = [];
  let allowed = false;
  const fetchImpl = async (input, init) => { calls.push([typeof input === "string" ? input : input.url, init && init.method]); return { ok: true }; };
  const guarded = guardWrites(fetchImpl, { apiUrl: DEV_API, allowed: () => allowed });
  await assert.rejects(guarded(`${DEV_API}/api/0.6/changeset/create`, { method: "PUT" }), EditNotAllowedError);
  await assert.rejects(guarded({ url: `${DEV_API}/api/0.6/changeset/3/upload`, method: "POST" }), err => err.name === "EditNotAllowedError");
  await guarded(`${DEV_API}/api/0.6/way/1/full.json`);
  await guarded(`${DEV_API}/oauth2/revoke`, { method: "POST" });
  assert.deepEqual(calls, [[`${DEV_API}/api/0.6/way/1/full.json`, undefined], [`${DEV_API}/oauth2/revoke`, "POST"]]);
  allowed = true;
  await guarded(`${DEV_API}/api/0.6/changeset/create`, { method: "PUT" });
  assert.equal(calls.length, 3);
});

test("installing the write guard wraps window.fetch and can be undone", async () => {
  const { installWriteGuard } = await load("access.js");
  const original = async () => ({ ok: true });
  const target = { fetch: original };
  const undo = installWriteGuard(target, { apiUrl: DEV_API, allowed: () => false });
  await assert.rejects(target.fetch(`${DEV_API}/api/0.6/changeset/create`, { method: "PUT" }));
  undo();
  assert.deepEqual(await target.fetch(`${DEV_API}/api/0.6/changeset/create`, { method: "PUT" }), { ok: true });
});

test("a blocked write is reported as not allowed, never as a network error", async () => {
  const { EditNotAllowedError } = await load("access.js");
  const { errorKind, errorMessage } = await load("errors.js");
  const err = new EditNotAllowedError(`${DEV_API}/api/0.6/changeset/create`);
  assert.equal(errorKind(err), "notAllowed");
  for (const lang of ["fr", "nl", "en"]) {
    const warnings = [];
    const text = errorMessage(err, i18nFor(lang, warnings).t);
    assert.ok(text && !/edit\.error/.test(text), lang);
    assert.deepEqual(warnings, [], lang);
  }
});

test("the login panel tells a restricted beta, an allowed account and a refused account apart", async () => {
  const { authView } = await load("panel.js");
  for (const lang of ["fr", "nl", "en"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const anonymous = String(authView({ kind: "anonymous", restricted: true }, i18n));
    const open = String(authView({ kind: "anonymous", restricted: false }, i18n));
    const allowed = String(authView({ kind: "logged", name: "Ann", restricted: true }, i18n));
    const refused = String(authView({ kind: "forbidden", name: "Bob", uid: 4242, restricted: true }, i18n));
    assert.match(anonymous, /data-edit-access="restricted"/, lang);
    assert.doesNotMatch(open, /data-edit-access/, lang);
    assert.match(allowed, /data-edit-access="allowed"/, lang);
    assert.match(refused, /data-edit-access="forbidden"[^>]*>[^<]*4242/, lang);
    assert.match(refused, /data-edit-action="logout"/, lang);
    assert.doesNotMatch(refused, /data-edit-action="login"/, lang);
    assert.deepEqual(warnings, [], lang);
  }
});

test("a refused account sees why the send button stays disabled", async () => {
  const { queueView } = await load("panel.js");
  const intent = { wayId: 5, set: { "sidewalk:both": "no" }, name: "Rue A" };
  const form = { remark: "", sources: ["survey"], sourceOther: "", hashtags: "", review: false };
  const base = { items: [intent], form, busy: false, loggedIn: true, result: null, comments: ["x"],
    plan: { ready: [{}], groups: [{}], tooMany: false, max: 3, dropped: [] } };
  const refused = String(queueView({ ...base, notAllowed: true }, i18nFor("fr"), "https://dev", { sourcePresets: ["survey"] }));
  const allowed = String(queueView({ ...base, notAllowed: false }, i18nFor("fr"), "https://dev", { sourcePresets: ["survey"] }));
  assert.match(refused, /data-edit-access="send-blocked"/);
  assert.match(refused, /data-edit-action="send" disabled/);
  assert.doesNotMatch(allowed, /data-edit-access="send-blocked"/);
  assert.doesNotMatch(allowed, /data-edit-action="send" disabled/);
});
