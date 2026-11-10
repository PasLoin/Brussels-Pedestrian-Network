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
