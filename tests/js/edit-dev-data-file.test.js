const test = require("node:test");
const assert = require("node:assert/strict");
const { DOMParser } = require("linkedom");
const { IDBFactory } = require("fake-indexeddb");
const { loadEdit: load } = require("./helpers.js");

function osm(body) {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="test">${body}</osm>`;
}

const NODES = `
  <node id="1" version="1" lat="50.8000" lon="4.4000" timestamp="2026-05-01T10:00:00Z"/>
  <node id="2" version="1" lat="50.8000" lon="4.4010" timestamp="2026-05-20T04:45:43Z"/>
`;

function street(id, tags, extra = "") {
  const tagXml = Object.entries(tags).map(([k, v]) => `<tag k="${k}" v="${v}"/>`).join("");
  return `<way id="${id}" version="3" timestamp="2026-05-02T00:00:00Z"${extra}><nd ref="1"/><nd ref="2"/>${tagXml}</way>`;
}

test("an export of the dev server becomes nodes, ways with tags and the newest timestamp", async () => {
  const { parseOsmXml } = await load("dev-data.js");
  const parsed = parseOsmXml(osm(NODES + street(4307564425, { highway: "residential", name: "Rue des Tilleuls", "@id": "1052304744" })), DOMParser);
  assert.deepEqual([...parsed.nodes.keys()], [1, 2]);
  assert.deepEqual(parsed.nodes.get(2), [4.401, 50.8]);
  assert.deepEqual(parsed.ways, [{ id: 4307564425, version: 3, tags: { highway: "residential", name: "Rue des Tilleuls", "@id": "1052304744" }, refs: [1, 2] }]);
  assert.equal(parsed.latest, "2026-05-20T04:45:43Z");
});

test("deleted objects are skipped and relations are read without breaking anything", async () => {
  const { parseOsmXml } = await load("dev-data.js");
  const parsed = parseOsmXml(osm(NODES + street(10, { highway: "residential" }, ' visible="false"') + '<relation id="7" version="1"><member type="way" ref="10" role=""/></relation><bounds minlat="50" minlon="4" maxlat="51" maxlon="5"/>'), DOMParser);
  assert.deepEqual(parsed.ways, []);
});

test("a JOSM file with objects not yet uploaded is refused", async () => {
  const { parseOsmXml, DevDataError } = await load("dev-data.js");
  const unsaved = e => e instanceof DevDataError && e.code === "unsaved";
  assert.throws(() => parseOsmXml(osm(NODES + street(-5, { highway: "residential" })), DOMParser), unsaved);
  assert.throws(() => parseOsmXml(osm(NODES + street(10, { highway: "residential" }, ' action="modify"')), DOMParser), unsaved);
  assert.throws(() => parseOsmXml(osm(NODES + '<node id="abc" lat="50" lon="4"/>'), DOMParser), unsaved);
  assert.throws(() => parseOsmXml(osm(NODES + '<node id="9007199254740993" lat="50" lon="4"/>'), DOMParser), unsaved);
});

test("a file that is not an OSM export is refused", async () => {
  const { parseOsmXml, DevDataError } = await load("dev-data.js");
  const notOsm = e => e instanceof DevDataError && e.code === "notOsm";
  assert.throws(() => parseOsmXml('<?xml version="1.0"?><gpx><trk/></gpx>', DOMParser), notOsm);
  assert.throws(() => parseOsmXml(osm('<parsererror>bad</parsererror>'), DOMParser), notOsm);
  class EmptyParser {
    parseFromString() {
      return { documentElement: null, getElementsByTagName: () => [] };
    }
  }
  assert.throws(() => parseOsmXml("", EmptyParser), notOsm);
});

test("a whole file gives the sidewalk layer and what the panel shows", async () => {
  const { devDataFromFile, DevDataError } = await load("dev-data.js");
  const text = osm(NODES + street(11, { highway: "residential" }) + street(12, { highway: "footway" }));
  const { collection, meta } = devDataFromFile(text, "map.osm", DOMParser);
  assert.deepEqual(collection.features.map(f => f.id), [11]);
  assert.deepEqual(meta, { name: "map.osm", count: 1, latest: "2026-05-20T04:45:43Z" });
  assert.throws(() => devDataFromFile(osm(NODES), "vide.osm", DOMParser), e => e instanceof DevDataError && e.code === "empty");
});

test("the loaded export is kept per environment and can be cleared", async () => {
  const { createDevDataStore } = await load("dev-data.js");
  const indexedDB = new IDBFactory();
  const dev = createDevDataStore(indexedDB, "dev");
  const prod = createDevDataStore(indexedDB, "prod");
  assert.equal(await dev.load(), undefined);
  await dev.save({ meta: { name: "map.osm" } });
  assert.deepEqual(await dev.load(), { meta: { name: "map.osm" } });
  assert.equal(await prod.load(), undefined);
  await dev.clear();
  assert.equal(await dev.load(), undefined);
});

test("without IndexedDB, or when it fails, the page keeps working without a saved export", async () => {
  const { createDevDataStore } = await load("dev-data.js");
  const none = createDevDataStore(undefined, "dev");
  assert.equal(await none.load(), null);
  assert.equal(await none.save({}), undefined);
  assert.equal(await none.clear(), undefined);
  const refusing = {
    open() {
      const req = {};
      setTimeout(() => { req.error = new Error("blocked"); req.onerror(); });
      return req;
    },
  };
  const broken = createDevDataStore(refusing, "dev");
  assert.equal(await broken.load(), null);
  assert.equal(await broken.save({}), undefined);
  const throwing = { open() { throw new Error("SecurityError"); } };
  assert.equal(await createDevDataStore(throwing, "dev").load(), null);
});

test("a value that cannot be stored is reported as a failure, not thrown", async () => {
  const { createDevDataStore } = await load("dev-data.js");
  const store = createDevDataStore(new IDBFactory(), "dev");
  assert.equal(await store.save({ notCloneable: () => 1 }), undefined);
  assert.equal(await store.load(), undefined);
});
