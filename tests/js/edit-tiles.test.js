const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: key => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: key => data.delete(key),
    dump: () => Object.fromEntries(data),
  };
}

const piece = (osm_id, coordinates, extra = {}) => ({
  geometry: { type: "LineString", coordinates },
  properties: { osm_id, sw: "unknown", highway: "residential", name: "rue test", ...extra },
});

test("tile pieces of one way become one candidate, the others are filtered out", async () => {
  const { candidatesFromTiles } = await load("candidates.js");
  const out = candidatesFromTiles([
    piece(101, [[4.0, 50.0], [4.001, 50.0]]),
    piece(101, [[4.001, 50.0], [4.002, 50.0]]),
    piece("102", [[4.0, 50.001], [4.001, 50.001]]),
    piece(103, [[4.0, 50.002], [4.001, 50.002]], { sw: "documented" }),
    piece(104, [[4.0, 50.003], [4.001, 50.003]], { highway: "tertiary" }),
    piece(0, [[4.0, 50.004], [4.001, 50.004]]),
    piece(105, [[4.0, 50.005]]),
    { geometry: { type: "Point", coordinates: [4, 50] }, properties: { osm_id: 106, sw: "unknown", highway: "residential" } },
    { geometry: { type: "MultiLineString", coordinates: [[[4.0, 50.006], [4.001, 50.006]], [[4.002, 50.006], [4.003, 50.006]]] }, properties: { osm_id: 107, sw: "unknown", highway: "residential" } },
  ]);
  const byId = new Map(out.features.map(f => [f.properties.osm_id, f]));
  assert.deepEqual([...byId.keys()].sort((a, b) => a - b), [101, 102, 107]);
  assert.equal(byId.get(101).geometry.type, "MultiLineString");
  assert.equal(byId.get(101).geometry.coordinates.length, 2);
  assert.equal(byId.get(102).geometry.type, "LineString");
  assert.deepEqual(byId.get(102).properties, { osm_id: 102, highway: "residential", name: "rue test" });
  assert.deepEqual(byId.get(107).properties, { osm_id: 107, highway: "residential", name: "" });
});

test("tile candidates keep only what lies in the box and leave out handled ways", async () => {
  const { candidatesFromTiles } = await load("candidates.js");
  const features = [piece(101, [[4.0, 50.0], [4.001, 50.0]]), piece(102, [[4.1, 50.1], [4.101, 50.1]]), piece(103, [[4.0, 50.0005], [4.001, 50.0005]])];
  const out = candidatesFromTiles(features, { box: [3.99, 49.99, 4.01, 50.01], exclude: id => id === 103 });
  assert.deepEqual(out.features.map(f => f.properties.osm_id), [101]);
  assert.deepEqual(candidatesFromTiles(null).features, []);
});

test("multi-part candidates are counted, merged and centred like single lines", async () => {
  const { pointsOf, countInBox, mergeCandidates } = await load("candidates.js");
  const { featureCenter } = await load("next.js");
  const multi = { type: "Feature", geometry: { type: "MultiLineString", coordinates: [[[4.0, 50.0], [4.002, 50.0]], [[4.002, 50.0], [4.004, 50.002]]] }, properties: { osm_id: 1 } };
  const single = { type: "Feature", geometry: { type: "LineString", coordinates: [[5.0, 51.0], [5.002, 51.0]] }, properties: { osm_id: 2 } };
  assert.equal(pointsOf(multi.geometry).length, 4);
  assert.deepEqual(pointsOf(null), []);
  const [cx, cy] = featureCenter(multi);
  assert.ok(Math.abs(cx - 4.002) < 1e-9 && Math.abs(cy - 50.001) < 1e-9, [cx, cy]);
  assert.equal(countInBox([multi, single], [3.9, 49.9, 4.1, 50.1]), 1);
  const merged = mergeCandidates(new Map([[1, multi], [2, single]]), { features: [] }, [3.9, 49.9, 4.1, 50.1]);
  assert.deepEqual([...merged.keys()], [2]);
  const capped = mergeCandidates(new Map(), { features: [multi, single] }, [3.9, 49.9, 4.1, 50.1], { max: 1 });
  assert.deepEqual([...capped.keys()], [1]);
});

test("the date of the OSM data behind the tiles is read from state.txt", async () => {
  const { parseDataTimestamp } = await load("handled.js");
  assert.equal(parseDataTimestamp('{"timestamp":"2026-11-16T22:30:00Z"}\nbuild_timestamp=2026-11-17T01:15:00Z\n'), Date.parse("2026-11-16T22:30:00Z"));
  assert.equal(parseDataTimestamp("build_timestamp=2026-11-17T01:15:00Z\n"), null);
  assert.equal(parseDataTimestamp('{"timestamp":"not a date"}'), null);
  assert.equal(parseDataTimestamp("{broken"), null);
  assert.equal(parseDataTimestamp("{ nope }"), null);
  assert.equal(parseDataTimestamp(null), null);
});

test("a handled way stays out until the tiles are built from data newer than its handling", async () => {
  const { createHandledList, handledKey } = await load("handled.js");
  let clock = Date.parse("2026-11-17T10:00:00Z");
  const storage = memoryStorage();
  const handled = createHandledList({ storage, env: "prod", now: () => clock });
  handled.add([101, "102"]);
  handled.add(0);
  handled.add("abc");
  assert.equal(handled.size(), 2);
  assert.ok(handled.has(101) && handled.has("102"));
  assert.deepEqual(Object.keys(JSON.parse(storage.dump()[handledKey("prod")])), ["101", "102"]);

  handled.prune(Date.parse("2026-11-16T22:30:00Z"));
  assert.ok(handled.has(101), "tiles older than the edit keep the way out");
  handled.prune(null);
  assert.ok(handled.has(101), "unknown tile date keeps the way out");

  const reloaded = createHandledList({ storage, env: "prod", now: () => clock });
  assert.ok(reloaded.has(102));
  reloaded.prune(Date.parse("2026-11-17T22:30:00Z"));
  assert.equal(reloaded.size(), 0, "tiles built after the edit show the truth again");

  reloaded.add(103);
  clock += 15 * 24 * 60 * 60 * 1000;
  reloaded.prune(null);
  assert.equal(reloaded.has(103), false, "the list never keeps a way more than two weeks");
});

test("the handled list survives broken storage and keeps the newest ways when full", async () => {
  const { createHandledList, handledKey } = await load("handled.js");
  for (const raw of ["not json", "[1,2]", '{"x":1,"5":"later"}', "null"]) {
    const handled = createHandledList({ storage: memoryStorage({ [handledKey("dev")]: raw }), env: "dev" });
    assert.equal(handled.size(), 0, raw);
  }
  const failing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("full"); } };
  const quiet = createHandledList({ storage: failing, env: "dev" });
  quiet.add(1);
  assert.ok(quiet.has(1));
  let clock = 0;
  const small = createHandledList({ storage: memoryStorage(), env: "dev", now: () => (clock += 1), max: 2 });
  small.add(1);
  small.add(2);
  small.add(3);
  assert.deepEqual([small.has(1), small.has(2), small.has(3)], [false, true, true]);
});

test("the nightly candidate index is read defensively", async () => {
  const { parseCandidateIndex, pointsOf } = await load("candidates.js");
  assert.deepEqual(parseCandidateIndex(JSON.stringify({ ways: [[101, 4.35, 50.84], [102, 4.36, 50.85]] })), [
    { id: 101, lon: 4.35, lat: 50.84 },
    { id: 102, lon: 4.36, lat: 50.85 },
  ]);
  const messy = { ways: [[0, 4, 50], [-3, 4, 50], [1.5, 4, 50], ["7", 4, 50], [8, "4", 50], [9, 4], [10, 200, 50], [11, 4, -95], null, [12, 4.1, 50.1]] };
  assert.deepEqual(parseCandidateIndex(JSON.stringify(messy)), [{ id: 12, lon: 4.1, lat: 50.1 }]);
  for (const text of ["", "not json", "null", "[]", '{"ways":{}}', '{"other":[]}']) assert.deepEqual(parseCandidateIndex(text), [], text);
  assert.deepEqual(pointsOf({ type: "Point", coordinates: [4, 50] }), [[4, 50]]);
});
