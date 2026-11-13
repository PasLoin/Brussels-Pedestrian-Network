const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);
const line = (id, coords, tags = {}) => ({ type: "Feature", properties: { osm_id: id, ...tags }, geometry: { type: "LineString", coordinates: coords } });

const street = [[4.4, 50.8], [4.4012, 50.8]];
const shifted = dy => street.map(([x, y]) => [x, y + dy]);

test("the dev way lying on the tile way is chosen even with other ids", async () => {
  const { matchCandidate } = await load("match.js");
  const best = matchCandidate([street], [line(7, shifted(0.00003)), line(8, shifted(0.0004)), line(9, [[4.4, 50.79], [4.4, 50.791]])]);
  assert.equal(best.feature.properties.osm_id, 7);
  assert.ok(best.meanM < 4, String(best.meanM));
  assert.equal(best.cover, 1);
});

test("a parallel street 40 m away is never taken for the clicked one", async () => {
  const { matchCandidate } = await load("match.js");
  assert.equal(matchCandidate([street], [line(8, shifted(0.00036))]), null);
});

test("a dev way covering only half of the tile way is refused", async () => {
  const { matchCandidate } = await load("match.js");
  assert.equal(matchCandidate([street], [line(7, [[4.4, 50.8], [4.4006, 50.8]])]), null);
});

test("tile fragments of one street are matched together, and a longer dev way still matches", async () => {
  const { matchCandidate } = await load("match.js");
  const fragments = [[[4.4, 50.8], [4.4006, 50.8]], [[4.4006, 50.8], [4.4012, 50.8]]];
  const best = matchCandidate(fragments, [line(7, [[4.3994, 50.8], [4.4018, 50.8]])]);
  assert.equal(best.feature.properties.osm_id, 7);
});

test("no geometry, no match", async () => {
  const { matchCandidate, linesOf } = await load("match.js");
  assert.equal(matchCandidate([], [line(7, street)]), null);
  assert.deepEqual(linesOf({ type: "Point", coordinates: [0, 0] }), []);
  assert.equal(linesOf({ type: "MultiLineString", coordinates: [street, street] }).length, 2);
});
