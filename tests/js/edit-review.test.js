const test = require("node:test");
const assert = require("node:assert/strict");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");
const { loadEdit: load, memoryStorage } = require("./helpers.js");

globalThis.html = html;

test("a street seen whole stays seen for its version until the flag expires", async () => {
  const { createReviewStore, reviewKey } = await load("review.js");
  const storage = memoryStorage();
  let clock = 1000;
  const store = createReviewStore({ storage, env: "dev", ttlMs: 500, now: () => clock });
  assert.equal(store.seenWhole(7, 3), false);
  store.markWhole(7, 3);
  assert.equal(store.seenWhole(7, 3), true);
  assert.equal(store.seenDetail(7, 3), false);
  assert.equal(store.seenWhole(7, 4), false);
  const again = createReviewStore({ storage, env: "dev", ttlMs: 500, now: () => clock });
  assert.equal(again.seenWhole(7, 3), true);
  assert.ok(storage.getItem(reviewKey("dev")).includes("\"7\""));
  clock = 1600;
  assert.equal(again.seenWhole(7, 3), false);
});

test("a new version of the way must be looked at again", async () => {
  const { createReviewStore } = await load("review.js");
  const store = createReviewStore({ storage: memoryStorage(), env: "dev", ttlMs: 1e9 });
  store.markWhole(7, 3);
  store.markDetail(7, 3);
  store.markWhole(7, 4);
  assert.equal(store.seenDetail(7, 4), false);
  assert.equal(store.seenWhole(7, 3), false);
});

test("the review list keeps only the most recent streets", async () => {
  const { createReviewStore } = await load("review.js");
  let clock = 0;
  const store = createReviewStore({ storage: memoryStorage(), env: "dev", ttlMs: 1e9, now: () => ++clock, max: 2 });
  store.markWhole(1, 1);
  store.markWhole(2, 1);
  store.markWhole(3, 1);
  assert.deepEqual([1, 2, 3].map(id => store.seenWhole(id, 1)), [false, true, true]);
});

test("samples follow the street every few metres and keep its ends", async () => {
  const { samplesAlong } = await load("review.js");
  const coords = [[4.4, 50.8], [4.4007, 50.8]];
  const samples = samplesAlong(coords, 5);
  assert.deepEqual(samples[0], coords[0]);
  assert.deepEqual(samples.at(-1), coords[1]);
  assert.ok(samples.length >= 10 && samples.length <= 12, String(samples.length));
});

test("only samples inside the free part of the map count as seen", async () => {
  const { coveredIndexes } = await load("review.js");
  const free = { left: 0, top: 0, right: 600, bottom: 400 };
  assert.deepEqual(coveredIndexes([{ x: 10, y: 10 }, { x: 700, y: 10 }, { x: 598, y: 200 }], free, 4), [0]);
});

test("the review zoom setting accepts only sensible zoom levels", async () => {
  const { parseReviewZoom } = await load("review.js");
  assert.equal(parseReviewZoom("18.6"), 18.6);
  assert.equal(parseReviewZoom("abc"), null);
  assert.equal(parseReviewZoom("30"), null);
  assert.equal(parseReviewZoom(""), null);
  assert.equal(parseReviewZoom(null), null);
});

test("an unfinished close look locks the choice and says how much is left", async () => {
  const { detailView, editLock } = await load("panel.js");
  const base = { kind: "way", editable: true, seenWhole: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  assert.equal(editLock({ ...base, review: { zoom: 18.6, percent: 40, done: false } }), "detail");
  assert.equal(editLock({ ...base, review: { zoom: 18.6, percent: 100, done: true } }), null);
  assert.equal(editLock({ ...base, seenWhole: false, review: { zoom: 18.6, percent: 40, done: false } }), "hidden");
  for (const lang of ["fr", "en", "nl"]) {
    const warnings = [];
    const out = String(detailView({ ...base, review: { zoom: 18.6, percent: 40, done: false } }, i18nFor(lang, warnings), "https://x", { autoQueue: true }));
    assert.match(out, /data-edit-action="review-next"/);
    assert.match(out, /<progress class="edit-progress" max="100" value="40">/);
    assert.match(out, /data-value="separate"[^>]*disabled/);
    assert.deepEqual(warnings, []);
  }
  assert.match(String(detailView({ ...base, review: { zoom: 18.6, percent: 40, done: false } }, i18nFor("fr"), "https://x", { autoQueue: true })), /zoom 18,6|zoom 18\.6/);
});

test("by default a street is framed between zoom 17 and 19 and checked close up at zoom 18.7", async () => {
  const { SETTINGS, resolveEnv } = await load("env.js");
  assert.equal(SETTINGS.reviewZoom, 18.7);
  assert.equal(SETTINGS.fitMinZoom, 17);
  assert.equal(SETTINGS.fitMaxZoom, 19);
  assert.equal(resolveEnv("dev", "https://x/test-api/devtest.html").reviewZoom, 18.7);
});

test("the review gate keeps the same shape before and after the close look and sits above the choices", async () => {
  const { detailView } = await load("panel.js");
  const base = { kind: "way", editable: true, seenWhole: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  const shape = (out) => {
    const start = out.indexOf('class="edit-gate');
    assert.ok(start >= 0, out);
    const rest = out.slice(start);
    const end = rest.search(/edit-gate-done|data-edit-action="(fit|review-next)"/);
    return (rest.slice(0, end).match(/<(p|progress|button|div)\b/g) || []).map((tag) => (tag === "<div" ? "<button" : tag)).join(",");
  };
  for (const lang of ["fr", "en", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const pending = String(detailView({ ...base, review: { zoom: 18.6, percent: 40, done: false } }, i18n, "https://x", { autoQueue: true }));
    const done = String(detailView({ ...base, review: { zoom: 18.6, percent: 100, done: true } }, i18n, "https://x", { autoQueue: true }));
    const hidden = String(detailView({ ...base, seenWhole: false, review: { zoom: 18.6, percent: 0, done: false } }, i18n, "https://x", { autoQueue: true }));
    assert.equal(shape(pending), shape(done));
    assert.equal(shape(hidden), shape(done));
    for (const out of [pending, done, hidden]) assert.ok(out.indexOf("edit-gate") < out.indexOf('data-value="yes"'));
    assert.match(done, /<progress class="edit-progress" max="100" value="100">/);
    assert.match(done, /class="btn edit-gate-done" aria-hidden="true"/);
    assert.doesNotMatch(done, /data-edit-action="review-next"/);
    assert.doesNotMatch(done, /data-value="yes"[^>]*disabled/);
    assert.deepEqual(warnings, []);
  }
});

test("without a close look the gate still holds its place once the whole street was seen", async () => {
  const { detailView } = await load("panel.js");
  const base = { kind: "way", editable: true, seenWhole: true, review: null, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  const out = String(detailView(base, i18nFor("en"), "https://x", { autoQueue: true }));
  assert.match(out, /class="edit-gate" role="status"[\s\S]*Whole street seen/);
  assert.doesNotMatch(out, /<progress/);
});

test("each queued street can be reopened from the queue", async () => {
  const { queueView } = await load("panel.js");
  const form = { remark: "", sources: [], sourceOther: "", hashtags: "", review: false };
  const out = String(queueView({
    items: [{ wayId: 5, set: { "sidewalk:both": "no" }, name: "Rue <A>" }], form, plan: null, busy: false, loggedIn: true, result: null,
  }, i18nFor("fr"), "https://dev", { sourcePresets: [] }));
  assert.match(out, /<button type="button" class="edit-open" data-edit-action="open-queued" data-way-id="5" title="[^"]+">Rue &lt;A&gt;/);
  assert.match(out, /data-edit-action="dequeue" data-way-id="5"/);
});
