const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");

globalThis.html = html;

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);

function parsed(ways, extraNodes = []) {
  const nodes = new Map([[1, [4.4, 50.8]], [2, [4.4005, 50.8]], [3, [4.40005, 50.8]], ...extraNodes]);
  return { nodes, ways, latest: "" };
}
const way = (id, tags, refs = [1, 2]) => ({ id, version: 1, tags, refs });

test("dev ways become sidewalk features with their dev id, like the production tiles", async () => {
  const { sidewalkRoadsFromOsm } = await load("dev-data.js");
  const { features } = sidewalkRoadsFromOsm(parsed([
    way(4307569310, { highway: "residential", name: "Rue Stevens-Delannoy - Stevens-Delannoystraat", "@id": "1052304744" }),
    way(4307569311, { highway: "residential", "sidewalk:both": "separate" }),
  ]));
  assert.equal(features.length, 2);
  const [first, second] = features;
  assert.equal(first.id, 4307569310);
  assert.deepEqual(first.properties, { sw: "unknown", name: "rue stevens-delannoy - stevens-delannoystraat", osm_id: 4307569310, highway: "residential", length_m: 35.1 });
  assert.equal(second.properties.sw, "separate");
});

test("service roads, areas, short ways, broken ways and other highways are left out", async () => {
  const { sidewalkRoadsFromOsm } = await load("dev-data.js");
  const { features } = sidewalkRoadsFromOsm(parsed([
    way(1, { highway: "service" }),
    way(2, { highway: "footway" }),
    way(3, { highway: "residential", area: "yes" }),
    way(4, { highway: "residential" }, [1, 3]),
    way(5, { highway: "residential" }, [1, 99]),
    way(6, { highway: "Tertiary " }),
    way(7, { highway: "residential" }, [1]),
  ]));
  assert.deepEqual(features.map(f => f.id), [6]);
  assert.equal(features[0].properties.highway, "tertiary");
});

test("a file with no usable street is refused", async () => {
  const { sidewalkRoadsFromOsm, DevDataError } = await load("dev-data.js");
  assert.throws(() => sidewalkRoadsFromOsm(parsed([way(1, { highway: "service" })])), e => e instanceof DevDataError && e.code === "empty");
});

test("sidewalk statuses follow the pipeline rules", async () => {
  const { sidewalkStatus } = await load("dev-data.js");
  const cases = [
    [{}, "unknown"],
    [{ "sidewalk:both": "separate", sidewalk: "no" }, "separate"],
    [{ "sidewalk:both": "both" }, "yes"],
    [{ "sidewalk:both": "no" }, "documented"],
    [{ "sidewalk:left": "separate", "sidewalk:right": "separate" }, "separate"],
    [{ "sidewalk:left": "separate", "sidewalk:right": "no" }, "documented"],
    [{ sidewalk: " Right " }, "partial"],
    [{ sidewalk: "no" }, "documented"],
    [{ "sidewalk:right": "yes" }, "partial"],
  ];
  for (const [tags, expected] of cases) assert.equal(sidewalkStatus(tags), expected, JSON.stringify(tags));
});

test("the data panel shows the loaded export, the errors and the way back, in every language", async () => {
  const { devDataView } = await load("panel.js");
  for (const lang of ["fr", "en", "nl"]) {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const empty = String(devDataView({ active: null }, i18n));
    assert.match(empty, /data-edit-action="data-load"/);
    assert.doesNotMatch(empty, /data-reset/);
    const loaded = String(devDataView({ active: { count: 4847, name: "map.osm", latest: "2026-05-20T04:45:43Z" } }, i18n));
    assert.match(loaded, /data-edit-action="data-reset"/);
    assert.match(loaded, /map\.osm/);
    for (const error of ["notOsm", "unsaved", "empty", "tooBig", "read"]) {
      assert.match(String(devDataView({ active: null, error, size: 80 }, i18n)), /role="alert"/);
    }
    assert.match(String(devDataView({ active: null, loading: "map.osm" }, i18n)), /data-edit-action="data-load" disabled/);
    assert.deepEqual(warnings, []);
  }
  assert.match(String(devDataView({ active: { count: 4847, name: "map.osm" } }, i18nFor("fr"))), /4\D?847 rues chargées depuis map\.osm/);
});
