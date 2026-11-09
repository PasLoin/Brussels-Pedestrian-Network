const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const load = () => import(pathToFileURL(path.join(__dirname, "..", "..", "map", "basemap-styles.js")).href);

test("Liberty keeps its layers, takes local paint and applies the overrides last", async () => {
  const { mergeLibertyStyle } = await load();
  const liberty = { version: 8, layers: [
    { id: "road_minor", paint: { "line-color": "#fff", "line-width": 2 } },
    { id: "water", paint: { "fill-color": "#00f" } },
  ] };
  const local = { layers: [{ id: "road_minor", paint: { "line-width": 3 } }, { id: "water", paint: { "fill-color": "#0f0" } }] };
  const merged = mergeLibertyStyle(liberty, local, { road_minor: { "line-color": "#d5d5d5" } });
  assert.deepEqual(merged.layers[0].paint, { "line-color": "#d5d5d5", "line-width": 3 });
  assert.deepEqual(merged.layers[1].paint, { "fill-color": "#00f" });
  assert.equal(liberty.layers[0].paint["line-color"], "#fff");
});

test("Liberty still gets the overrides without a local style", async () => {
  const { mergeLibertyStyle } = await load();
  const merged = mergeLibertyStyle({ layers: [{ id: "road_minor" }] }, null, { road_minor: { "line-color": "#aaa" } });
  assert.deepEqual(merged.layers[0].paint, { "line-color": "#aaa" });
});

test("Zinneke drops hidden sources and layers, prefixes sources and hides icons", async () => {
  const { adaptZinnekeStyle, ZINNEKE_SOURCE_PREFIX, ZINNEKE_ATTRIBUTION } = await load();
  const style = {
    sources: { base: { type: "vector", url: "tiles/base.pmtiles" }, poi: { type: "vector" }, unused: { type: "vector" } },
    layers: [
      { id: "land", source: "base" },
      { id: "railway-tram-1", source: "base" },
      { id: "shop", source: "poi" },
      { id: "label", source: "base", layout: { "icon-image": "x", "text-field": "{name}" } },
      { id: "background" },
    ],
  };
  const bm = { url: "https://example.org/zt/style.json", hideSources: ["poi"], hideLayers: ["railway-tram*"] };
  const adapted = adaptZinnekeStyle(style, bm);
  assert.deepEqual(adapted.layers.map(l => l.id), ["land", "label", "background"]);
  assert.deepEqual(Object.keys(adapted.sources), [`${ZINNEKE_SOURCE_PREFIX}base`]);
  assert.equal(adapted.sources[`${ZINNEKE_SOURCE_PREFIX}base`].url, "pmtiles://https://example.org/zt/tiles/base.pmtiles");
  assert.equal(adapted.sources[`${ZINNEKE_SOURCE_PREFIX}base`].attribution, ZINNEKE_ATTRIBUTION);
  assert.equal(adapted.layers[0].source, `${ZINNEKE_SOURCE_PREFIX}base`);
  assert.deepEqual(adapted.layers[1].layout, { "text-field": "{name}", visibility: "none" });
  assert.equal(style.layers.length, 5);
});

test("switching base map keeps the overlay sources and layers on top", async () => {
  const { keepOverlays } = await load();
  const prev = {
    sources: { pedestrian: { type: "vector" }, "nav-route": { type: "geojson" }, old: {} },
    layers: [{ id: "old-bg", source: "old" }, { id: "flow", source: "pedestrian" }, { id: "route", source: "nav-route" }],
  };
  const next = { sources: { fresh: {} }, layers: [{ id: "bg", source: "fresh" }] };
  const merged = keepOverlays(prev, next);
  assert.deepEqual(Object.keys(merged.sources).sort(), ["fresh", "nav-route", "pedestrian"]);
  assert.deepEqual(merged.layers.map(l => l.id), ["bg", "flow", "route"]);
  assert.deepEqual(keepOverlays(null, next).layers.map(l => l.id), ["bg"]);
});
