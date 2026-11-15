const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { i18nFor } = require("./dictionaries.js");

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);
const apiError = (status, text) => Object.assign(new Error(`OSM API: ${text}`), { cause: status });

test("every OSM failure is sorted into a kind the user can act on", async () => {
  const { errorKind } = await load("errors.js");
  const cases = [
    [apiError(401, "Couldn't authenticate you"), "auth"],
    [apiError(403, "Your access to the API has been blocked"), "forbidden"],
    [apiError(429, "Changeset rate limit exceeded"), "rateLimit"],
    [apiError(509, "You have downloaded too much data"), "bandwidth"],
    [apiError(503, "Database offline for maintenance"), "maintenance"],
    [apiError(500, "Database offline for maintenance"), "maintenance"],
    [apiError(400, "You requested too many nodes (limit is 50000)"), "tooBig"],
    [apiError(400, "The maximum bbox size is 0.25"), "tooBig"],
    [apiError(500, "Internal Server Error"), "server"],
    [apiError(502, ""), "server"],
    [new TypeError("Failed to fetch"), "network"],
    [new Error("NetworkError when attempting to fetch resource."), "network"],
    [apiError(400, "Precondition failed"), "unknown"],
    [apiError(404, ""), "unknown"],
    [undefined, "unknown"],
  ];
  for (const [err, kind] of cases) assert.equal(errorKind(err), kind, String(err && err.message));
});

test("each kind has a clear message in every published language", async () => {
  const { errorMessage } = await load("errors.js");
  const errors = [apiError(401, ""), apiError(403, ""), apiError(429, ""), apiError(509, ""), apiError(503, ""),
    apiError(400, "too many nodes"), apiError(500, ""), new TypeError("Failed to fetch")];
  for (const lang of ["en", "fr", "nl"]) {
    const warnings = [];
    const { t } = i18nFor(lang, warnings);
    const texts = errors.map(e => errorMessage(e, t));
    assert.equal(new Set(texts).size, texts.length, lang);
    for (const text of texts) assert.doesNotMatch(text, /edit\.error|OSM API:/, lang);
    assert.deepEqual(warnings, []);
  }
  const { t } = i18nFor("fr");
  assert.equal(errorMessage(apiError(400, "Precondition failed: Way 7 still used"), t), "Precondition failed: Way 7 still used");
  assert.match(errorMessage(apiError(429, ""), t), /compte récent/);
});

test("candidates are not requested below the zoom threshold or over a too large area", async () => {
  const { tooLargeForCandidates, bboxAreaDeg2 } = await load("candidates.js");
  const box = (w, s, e, n) => ({ getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n });
  const settings = { candidateMinZoom: 17, maxCandidateAreaDeg2: 0.001 };
  assert.equal(tooLargeForCandidates(16.9, box(4.3, 50.8, 4.31, 50.805), settings), "zoom");
  assert.equal(tooLargeForCandidates(17.5, box(4.3, 50.8, 4.31, 50.805), settings), null);
  assert.equal(tooLargeForCandidates(17.5, box(4.3, 50.8, 4.36, 50.83), settings), "tooBig");
  assert.ok(Math.abs(bboxAreaDeg2(box(4.3, 50.8, 4.36, 50.83)) - 0.0018) < 1e-9);
});

test("below the candidate zoom the request covers a window sized like the view at that zoom, around the street", async () => {
  const { candidateRequest, candidateWindow, viewSpanDeg } = await load("candidates.js");
  const bounds = (w, s, e, n) => ({ getWest: () => w, getSouth: () => s, getEast: () => e, getNorth: () => n });
  const settings = { candidateMinZoom: 17, candidateFloorZoom: 15, maxCandidateAreaDeg2: 0.001 };
  const canvas = { width: 1024, height: 512 };
  const span = viewSpanDeg(1024, 512, 17, 0);
  assert.ok(Math.abs(span.lon - 1024 * 360 / (512 * 2 ** 17)) < 1e-12);
  assert.ok(Math.abs(span.lat - span.lon / 2) < 1e-12);
  const view = candidateRequest({ zoom: 17.2, bounds: bounds(4.3, 50.8, 4.31, 50.805), center: [4.305, 50.8025], canvas, settings });
  assert.deepEqual(view, { box: [4.3, 50.8, 4.31, 50.805], around: false });
  assert.deepEqual(candidateRequest({ zoom: 17.2, bounds: bounds(4.3, 50.8, 4.36, 50.83), center: [4.33, 50.815], canvas, settings }), { blocked: "tooBig" });
  assert.deepEqual(candidateRequest({ zoom: 14, bounds: bounds(4.2, 50.7, 4.5, 50.9), center: [4.35, 50.8], canvas, settings }), { blocked: "zoom" });
  const centred = candidateRequest({ zoom: 16, bounds: bounds(4.2, 50.7, 4.5, 50.9), center: [4.35, 50.8], canvas, settings });
  assert.equal(centred.around, true);
  assert.ok(Math.abs((centred.box[0] + centred.box[2]) / 2 - 4.35) < 1e-9);
  const street = [4.30, 50.80, 4.34, 50.801];
  const around = candidateRequest({ zoom: 14, bounds: bounds(4.2, 50.7, 4.5, 50.9), center: [4.35, 50.8], canvas, focus: street, settings });
  assert.ok(around.box[0] < 4.30 && around.box[2] > 4.34);
  assert.ok((around.box[2] - around.box[0]) * (around.box[3] - around.box[1]) <= 0.001 + 1e-12);
  const huge = candidateWindow({ center: [4.35, 50.8], canvas, focus: [4.2, 50.7, 4.5, 50.9], settings });
  assert.ok((huge[2] - huge[0]) * (huge[3] - huge[1]) <= 0.001 + 1e-12);
  const wider = candidateWindow({ center: [4.35, 50.8], canvas, settings, scale: 2 });
  const base = candidateWindow({ center: [4.35, 50.8], canvas, settings });
  assert.ok(Math.abs((wider[2] - wider[0]) - 2 * (base[2] - base[0])) < 1e-12);
});

test("loaded candidates are merged area by area, the reloaded area replacing what it held", async () => {
  const { mergeCandidates, countInBox, boxWithin } = await load("candidates.js");
  const f = (id, x, y) => ({ type: "Feature", geometry: { type: "LineString", coordinates: [[x, y], [x + 0.0001, y]] }, properties: { osm_id: id } });
  const before = new Map([[1, f(1, 4.30, 50.80)], [2, f(2, 4.40, 50.80)], [3, f(3, 4.3005, 50.8005)]]);
  const merged = mergeCandidates(before, { features: [f(4, 4.3002, 50.8002)] }, [4.299, 50.799, 4.301, 50.801]);
  assert.deepEqual([...merged.keys()].sort(), [2, 4]);
  assert.equal(countInBox(merged.values(), [4.39, 50.79, 4.41, 50.81]), 1);
  const capped = mergeCandidates(new Map(), { features: [f(5, 4.30, 50.80), f(6, 4.50, 50.80), f(7, 4.301, 50.80)] }, [4.29, 50.79, 4.31, 50.81], { max: 2 });
  assert.deepEqual([...capped.keys()].sort(), [5, 7]);
  assert.equal(boxWithin([1, 1, 2, 2], [0, 0, 3, 3]), true);
  assert.equal(boxWithin([1, 1, 4, 2], [0, 0, 3, 3]), false);
});
