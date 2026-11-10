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

test("the map only moves when the selected way is hidden or too close to the edge", async () => {
  const { freeRect, recenterOffset } = await load("viewport.js");
  const canvas = { width: 1000, height: 700 };
  const free = freeRect(canvas, { left: 688, right: 988, top: 100, bottom: 500 }, "right");
  assert.equal(recenterOffset(canvas, free, { minX: 300, maxX: 500, minY: 300, maxY: 320 }), null);
  assert.deepEqual(recenterOffset(canvas, free, { minX: 700, maxX: 900, minY: 300, maxY: 320 }), [-162, 0]);
  assert.deepEqual(recenterOffset(canvas, free, { minX: 10, maxX: 200, minY: 300, maxY: 320 }), [-162, 0]);
  const below = freeRect(canvas, { left: 220, right: 780, top: 400, bottom: 650 }, "bottom");
  assert.deepEqual(recenterOffset(canvas, below, { minX: 400, maxX: 600, minY: 500, maxY: 520 }), [0, -156]);
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
