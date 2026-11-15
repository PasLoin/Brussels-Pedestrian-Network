const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");

globalThis.html = html;

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);
const key = (k, extra = {}) => ({ key: k, target: { tagName: "BODY" }, ...extra });

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return { getItem: k => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: k => data.delete(k) };
}

test("keys map to editing actions and Tab is never taken", async () => {
  const { shortcutFor } = await load("shortcuts.js");
  assert.deepEqual(shortcutFor(key("s")), { type: "value", value: "separate" });
  assert.deepEqual(shortcutFor(key("Y")), { type: "value", value: "yes" });
  assert.deepEqual(shortcutFor(key("n")), { type: "value", value: "no" });
  assert.deepEqual(shortcutFor(key("d")), { type: "mode", mode: "sides" });
  assert.deepEqual(shortcutFor(key("b")), { type: "mode", mode: "both" });
  assert.deepEqual(shortcutFor(key("p")), { type: "skip" });
  assert.deepEqual(shortcutFor(key("ArrowRight")), { type: "next" });
  assert.deepEqual(shortcutFor(key("Escape")), { type: "deselect" });
  for (const other of ["Tab", "Enter", " ", "ArrowLeft", "ArrowUp", "ArrowDown", "x", "1"]) assert.equal(shortcutFor(key(other)), null, other);
});

test("shortcuts stay silent while typing, with modifiers or on key repeat", async () => {
  const { shortcutFor } = await load("shortcuts.js");
  for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) assert.equal(shortcutFor(key("s", { target: { tagName } })), null);
  assert.equal(shortcutFor(key("s", { target: { tagName: "DIV", isContentEditable: true } })), null);
  assert.equal(shortcutFor(key("ArrowRight", { target: { tagName: "INPUT" } })), null);
  for (const modifier of ["ctrlKey", "metaKey", "altKey", "repeat"]) assert.equal(shortcutFor(key("s", { [modifier]: true })), null, modifier);
  assert.deepEqual(shortcutFor(key("s", { target: { tagName: "BUTTON" } })), { type: "value", value: "separate" });
  assert.equal(shortcutFor(undefined), null);
});

test("in different-sides mode a value key fills the left side first, then the right", async () => {
  const { sideForValue } = await load("shortcuts.js");
  assert.equal(sideForValue({ mode: "both", both: "", left: "", right: "" }), "both");
  assert.equal(sideForValue({ mode: "sides", both: "", left: "", right: "" }), "left");
  assert.equal(sideForValue({ mode: "sides", both: "", left: "yes", right: "" }), "right");
  assert.equal(sideForValue({ mode: "sides", both: "", left: "yes", right: "no" }), "left");
});

const line = (id, x, y) => ({ type: "Feature", properties: { osm_id: id }, geometry: { type: "LineString", coordinates: [[x - 0.0002, y], [x + 0.0002, y]] } });

test("the next candidate is the nearest one not excluded, with a stable tie-break", async () => {
  const { nextCandidate, featureCenter } = await load("next.js");
  const pool = [line(5, 4.3020, 50.80), line(3, 4.3010, 50.80), line(9, 4.3050, 50.80), line(4, 4.2990, 50.80)];
  const from = [4.30, 50.80];
  assert.equal(nextCandidate(pool, from, new Set()).properties.osm_id, 3);
  assert.equal(nextCandidate([...pool].reverse(), from, new Set()).properties.osm_id, 3);
  assert.equal(nextCandidate(pool, from, new Set([3, 4])).properties.osm_id, 5);
  assert.equal(nextCandidate(pool, from, new Set([3, 4, 5, 9])), null);
  assert.equal(nextCandidate([], from, new Set()), null);
  const c = featureCenter(line(1, 4.30, 50.80));
  assert.ok(Math.abs(c[0] - 4.30) < 1e-9 && Math.abs(c[1] - 50.80) < 1e-9);
});

test("skipped streets are remembered per environment, capped and resettable", async () => {
  const { createSkipList, skippedKey } = await load("skipped.js");
  const storage = memoryStorage();
  const list = createSkipList({ storage, env: "dev", max: 3 });
  for (const id of [1, 2, 3, 2, 4]) list.add(id);
  assert.deepEqual(list.list(), [3, 2, 4]);
  assert.equal(list.has(1), false);
  assert.deepEqual(createSkipList({ storage, env: "dev" }).list(), [3, 2, 4]);
  assert.equal(createSkipList({ storage, env: "prod" }).size(), 0);
  list.remove(2);
  assert.deepEqual(list.list(), [3, 4]);
  list.clear();
  assert.equal(createSkipList({ storage, env: "dev" }).size(), 0);
  storage.setItem(skippedKey("dev"), "{broken");
  assert.equal(createSkipList({ storage, env: "dev" }).size(), 0);
});

test("the dock position is one of three fixed places and defaults to the right", async () => {
  const { readDockPosition, DOCK_KEY, DOCK_POSITIONS } = await load("viewport.js");
  assert.deepEqual([...DOCK_POSITIONS], ["right", "left", "bottom"]);
  assert.equal(readDockPosition(memoryStorage()), "right");
  assert.equal(readDockPosition(memoryStorage({ [DOCK_KEY]: "left" })), "left");
  assert.equal(readDockPosition(memoryStorage({ [DOCK_KEY]: "bottom" })), "bottom");
  assert.equal(readDockPosition(memoryStorage({ [DOCK_KEY]: "center" })), "right");
  assert.equal(readDockPosition({ getItem() { throw new Error("blocked"); } }), "right");
});

test("the free map area excludes the side taken by the panel", async () => {
  const { freeRect } = await load("viewport.js");
  const canvas = { width: 1000, height: 700 };
  assert.deepEqual(freeRect(canvas, null, "right"), { left: 0, top: 0, right: 1000, bottom: 700 });
  assert.deepEqual(freeRect(canvas, { left: 688, right: 988, top: 100, bottom: 500 }, "right"), { left: 0, top: 0, right: 676, bottom: 700 });
  assert.deepEqual(freeRect(canvas, { left: 12, right: 312, top: 60, bottom: 500 }, "left"), { left: 324, top: 0, right: 1000, bottom: 700 });
  assert.deepEqual(freeRect(canvas, { left: 220, right: 780, top: 400, bottom: 650 }, "bottom"), { left: 0, top: 0, right: 1000, bottom: 388 });
});

test("a way counts as visible only when all of it lies inside the free map area", async () => {
  const { boxOf, boxVisible, freeRect } = await load("viewport.js");
  const canvas = { width: 1000, height: 700 };
  const free = freeRect(canvas, { left: 688, right: 988, top: 100, bottom: 500 }, "right");
  assert.deepEqual(boxOf([{ x: 300, y: 320 }, { x: 500, y: 300 }]), { minX: 300, maxX: 500, minY: 300, maxY: 320 });
  assert.equal(boxVisible(free, { minX: 300, maxX: 500, minY: 300, maxY: 320 }, 40), true);
  assert.equal(boxVisible(free, { minX: 300, maxX: 700, minY: 300, maxY: 320 }), false);
  assert.equal(boxVisible(free, { minX: -20, maxX: 500, minY: 300, maxY: 320 }), false);
  assert.equal(boxVisible(free, { minX: 300, maxX: 650, minY: 300, maxY: 320 }, 40), false);
  assert.equal(boxVisible(free, { minX: 300, maxX: 650, minY: 300, maxY: 320 }, 4), true);
  const below = freeRect(canvas, { left: 220, right: 780, top: 400, bottom: 650 }, "bottom");
  assert.equal(boxVisible(below, { minX: 400, maxX: 600, minY: 300, maxY: 420 }), false);
});

test("fitting a way keeps it clear of the panel and never asks for more room than there is", async () => {
  const { fitPadding, freeRect } = await load("viewport.js");
  const canvas = { width: 1000, height: 700 };
  assert.deepEqual(fitPadding(canvas, freeRect(canvas, { left: 688, right: 988, top: 100, bottom: 500 }, "right")), { left: 40, top: 40, right: 364, bottom: 40 });
  assert.deepEqual(fitPadding(canvas, freeRect(canvas, { left: 12, right: 312, top: 60, bottom: 500 }, "left")), { left: 364, top: 40, right: 40, bottom: 40 });
  assert.deepEqual(fitPadding(canvas, freeRect(canvas, { left: 0, right: 1000, top: 560, bottom: 700 }, "bottom")), { left: 40, top: 40, right: 40, bottom: 192 });
  const tight = fitPadding({ width: 400, height: 300 }, { left: 0, top: 0, right: 400, bottom: 60 });
  assert.deepEqual(tight, { left: 15, top: 15, right: 15, bottom: 255 });
});

test("the edit form is locked until the whole street is on screen", async () => {
  const { detailView, editLock } = await load("panel.js");
  const base = { kind: "way", editable: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  assert.equal(editLock({ ...base, seenWhole: false }), "hidden");
  assert.equal(editLock({ ...base, visible: true, fitting: true }), "moving");
  const moving = String(detailView({ ...base, fitting: true }, i18nFor("fr"), "https://dev", { autoQueue: true }));
  assert.match(moving, /Affichage de toute la rue/);
  assert.match(moving, /data-value="yes"[^>]*disabled/);
  assert.equal(editLock({ ...base, visible: true }), null);
  assert.equal(editLock(base), null);
  const hidden = String(detailView({ ...base, seenWhole: false }, i18nFor("fr"), "https://dev", { autoQueue: true }));
  assert.match(hidden, /pas encore été vue en entier/);
  assert.match(hidden, /data-edit-action="fit"/);
  assert.match(hidden, /data-value="separate"[^>]*disabled/);
  assert.doesNotMatch(hidden, /découp/);
  const shown = String(detailView({ ...base, visible: true }, i18nFor("fr"), "https://dev", { autoQueue: true }));
  assert.doesNotMatch(shown, /disabled|data-edit-action="fit"/);
});

test("a street that would need one changeset too many cannot be edited until the queue is sent", async () => {
  const { detailView, editLock } = await load("panel.js");
  const base = { kind: "way", editable: true, visible: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } };
  const full = { zones: 3, after: 4, max: 3, fits: false };
  assert.equal(editLock({ ...base, room: full }), "full");
  assert.equal(editLock({ ...base, room: { ...full, after: 3, fits: true } }), null);
  assert.equal(editLock({ ...base, room: full, queued: { wayId: 5, set: { "sidewalk:both": "no" } } }), null);
  const out = String(detailView({ ...base, room: full }, i18nFor("fr"), "https://dev", { autoQueue: false }));
  assert.match(out, /au-delà des 3 changesets autorisés/);
  assert.match(out, /data-edit-action="plan"/);
  assert.match(out, /data-value="no"[^>]*disabled/);
  assert.match(out, /data-edit-action="queue" disabled/);
});

test("the queue counts its zones against the per-upload limit", async () => {
  const { zonesFor, queueRoom } = await load("osm.js");
  const settings = { maxWaysPerChangeset: 2, maxChangesetSpanM: 1000, maxChangesetsPerUpload: 2 };
  const at = (wayId, lon) => ({ wayId, bbox: [lon, 50.80, lon + 0.0005, 50.8005] });
  const queue = [at(1, 4.30), at(2, 4.3005), at(3, 4.40)];
  assert.equal(zonesFor(queue, settings), 2);
  assert.equal(zonesFor([...queue, { wayId: 9 }], settings), 2);
  assert.deepEqual(queueRoom(queue, at(4, 4.4002), settings), { zones: 2, after: 2, max: 2, fits: true });
  assert.deepEqual(queueRoom(queue, at(5, 4.50), settings), { zones: 2, after: 3, max: 2, fits: false });
  assert.deepEqual(queueRoom(queue, at(6, 4.3001), settings), { zones: 2, after: 3, max: 2, fits: false });
  assert.equal(queueRoom(queue, at(3, 4.50), settings).fits, true);
});

test("the queue shows how many changesets it will need and warns at the limit", async () => {
  const { queueView } = await load("panel.js");
  const form = { remark: "", sources: [], sourceOther: "", hashtags: "", review: false };
  const items = [{ wayId: 1, set: { "sidewalk:both": "no" }, name: "Rue A" }];
  const base = { items, form, plan: null, result: null, busy: false, loggedIn: true };
  const some = String(queueView({ ...base, zones: 2, maxZones: 3 }, i18nFor("fr"), "https://dev", { sourcePresets: [] }));
  assert.match(some, /2 changesets sur 3 au plus par envoi/);
  assert.doesNotMatch(some, /Limite atteinte/);
  assert.match(String(queueView({ ...base, zones: 3, maxZones: 3 }, i18nFor("fr"), "https://dev", { sourcePresets: [] })), /Limite atteinte/);
  assert.doesNotMatch(String(queueView({ ...base, items: [], zones: 0, maxZones: 3 }, i18nFor("fr"), "https://dev", { sourcePresets: [] })), /au plus par envoi/);
});

test("an over-long source or hashtag list is reported in the form and blocks sending", async () => {
  const { queueView } = await load("panel.js");
  const form = { remark: "", sources: ["survey"], sourceOther: "", hashtags: "", review: false };
  const items = [{ wayId: 1, set: { "sidewalk:both": "no" }, name: "Rue A" }];
  const plan = { ready: [{}], dropped: [], groups: [{}], tooMany: false, max: 3 };
  const base = { items, form, plan, result: null, busy: false, loggedIn: true };
  const ok = String(queueView({ ...base, tooLong: [] }, i18nFor("fr"), "https://dev", { sourcePresets: ["survey"], maxTagLength: 255 }));
  assert.match(ok, /data-edit-action="send">/);
  assert.match(ok, /name="cs-source-other" maxlength="255"/);
  const bad = String(queueView({ ...base, tooLong: [{ key: "source", length: 300, max: 255 }] }, i18nFor("fr"), "https://dev", { sourcePresets: ["survey"] }));
  assert.match(bad, /data-field-error="source"[^>]*>Sources trop longues : 300 caractères pour 255 au plus/);
  assert.match(bad, /data-edit-action="send" disabled/);
});

test("the form shows the keys and offers to skip or move on", async () => {
  const { detailView, navView } = await load("panel.js");
  const out = String(detailView({ kind: "way", editable: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } },
    i18nFor("fr"), "https://dev", { autoQueue: true }));
  assert.match(out, /data-value="separate"[^>]*><u>s<\/u>eparate</);
  assert.match(out, /data-edit-action="skip">Passer <kbd>p<\/kbd>/);
  assert.match(out, /data-edit-action="next">Suivant <kbd>→<\/kbd>/);
  assert.match(out, /<kbd>d<\/kbd>/);
  assert.match(out, /Touches : s, y, n/);
  const nav = String(navView({ candidates: 4, skipped: 2, selected: false, hint: "" }, i18nFor("fr")));
  assert.match(nav, /Candidat suivant/);
  assert.match(nav, /2 rues passées/);
  assert.match(nav, /data-edit-action="reset-skipped"/);
  assert.doesNotMatch(String(navView({ candidates: 4, skipped: 0, selected: true, hint: "" }, i18nFor("fr"))), /Candidat suivant|rue passée/);
  assert.doesNotMatch(String(navView({ candidates: 0, skipped: 0, selected: false, hint: "" }, i18nFor("fr"))), /Candidat suivant/);
});

test("the new controls speak every published language", async () => {
  const { detailView, navView } = await load("panel.js");
  for (const lang of ["en", "fr", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const outs = [
      detailView({ kind: "way", editable: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "sides", both: "", left: "", right: "" } }, i18n, "https://x", { autoQueue: true }),
      detailView({ kind: "way", editable: true, fitting: true, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } }, i18n, "https://x", { autoQueue: true }),
      detailView({ kind: "way", editable: true, seenWhole: false, way: { id: 5, version: 1, tags: {} }, choice: { mode: "sides", both: "", left: "", right: "" } }, i18n, "https://x", { autoQueue: true }),
      detailView({ kind: "way", editable: true, visible: true, room: { zones: 3, after: 4, max: 3, fits: false }, way: { id: 5, version: 1, tags: {} }, choice: { mode: "both", both: "", left: "", right: "" } }, i18n, "https://x", { autoQueue: true }),
      navView({ candidates: 2, skipped: 1, selected: false, hint: i18n.t("edit.nav.none") }, i18n),
      navView({ candidates: 2, skipped: 3, selected: false, hint: "" }, i18n),
    ].map(String);
    for (const text of outs) assert.doesNotMatch(text, /\bedit\.[a-z]+\.[A-Za-z_]+/, lang);
    assert.deepEqual(warnings, []);
  }
});

test("automatic advance is on by default and can be turned off", async () => {
  const { SETTINGS, resolveEnv } = await load("env.js");
  assert.equal(SETTINGS.autoAdvance, true);
  assert.equal(resolveEnv("dev", "https://x/test-api/devtest.html", { ...SETTINGS, autoAdvance: false }).autoAdvance, false);
});

test("below the candidate zoom the status says the loaded candidates stay", async () => {
  const { statusView } = await load("panel.js");
  for (const lang of ["en", "fr", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    for (const kept of [0, 1, 4]) assert.doesNotMatch(String(statusView({ kind: "zoom", minZoom: 17, kept }, i18n)), /\bedit\.[a-z]+\.[A-Za-z_]+/);
    assert.deepEqual(warnings, []);
  }
  const fr = i18nFor("fr");
  assert.match(statusView({ kind: "zoom", minZoom: 17, kept: 4 }, fr), /les 4 candidats déjà chargés restent affichés/);
  assert.match(statusView({ kind: "zoom", minZoom: 17, kept: 0 }, fr), /^Zoomez au niveau 17 pour charger les candidats/);
});
