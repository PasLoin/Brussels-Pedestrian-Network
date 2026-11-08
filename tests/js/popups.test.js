const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../../popups.js");
const { LANGUAGES, i18nFor } = require("./dictionaries.js");

const fr = i18nFor("fr");
const en = i18nFor("en");

const palette = {
  flowColors: { pedestrian: "#16a34a", road: "#ef4444" },
  sidewalkStatuses: [{ value: "separate", color: "#22c55e" }, { value: "partial", color: "#f5700b" }],
  highwayLayers: [{ id: "footway", color: "#22c55e" }, { id: "steps", color: "#166534" }],
  elevatorColor: "#4338ca",
  elevatorLayerIds: ["highway-elevator", "highway-elevator-line"],
};

const { hover, click } = P.makePopupLayers(palette, fr);
const entries = [...hover.map(e => ["hover", e]), ...click.map(e => ["click", e])];
const clickFormat = id => click.find(c => c.ids.includes(id)).format;
const hoverFormat = id => hover.find(h => h.ids.includes(id)).format;

const PAYLOADS = [
  `"><img src=x onerror=alert(1)>`,
  `42" onmouseover="alert(1)`,
  `javascript:alert(1)`,
  `</div><script>alert(1)</script>`,
];

const TYPES = [
  undefined, "missing_way", "missing_tag", "wrong_tag",
  "unjoined", "isolated", "level", "kerb_missing", "kerb_untagged",
];

function readKeys(format) {
  const keys = new Set();
  format(new Proxy({}, { get: (_, k) => { if (typeof k === "string") keys.add(k); return undefined; } }));
  return keys;
}

function hostile(keys, payload, type) {
  const p = { [payload]: payload };
  for (const k of keys) p[k] = payload;
  if (type !== undefined) p.type = type;
  return p;
}

function assertInert(html, context) {
  assert.doesNotMatch(html, /<(img|script|svg|iframe)\b/i, context);
  assert.doesNotMatch(html, /\son\w+\s*=\s*"/i, context);
  assert.doesNotMatch(html, /(href|src)\s*=\s*"\s*javascript:/i, context);
  for (const payload of PAYLOADS.filter(x => /[<>"']/.test(x))) {
    assert.ok(!html.includes(payload), `${context}: raw payload ${payload}`);
  }
}

test("escapeHTML escapes the five HTML-sensitive characters", () => {
  assert.equal(P.escapeHTML(`<a href="x">Tom & Jerry's</a>`), "&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&#039;s&lt;/a&gt;");
});

test("escapeHTML keeps empty values and stringifies numbers", () => {
  assert.equal(P.escapeHTML(""), "");
  assert.equal(P.escapeHTML(undefined), undefined);
  assert.equal(P.escapeHTML(0), 0);
  assert.equal(P.escapeHTML(12.5), "12.5");
});

test("popupTitle only draws a swatch when a colour is given", () => {
  assert.match(P.popupTitle("#123456", "T"), /popup-swatch" style="--c:#123456"/);
  assert.doesNotMatch(P.popupTitle(undefined, "T"), /popup-swatch/);
});

test("each layer id has at most one hover and one click popup", () => {
  for (const list of [hover, click]) {
    const ids = list.flatMap(e => e.ids);
    assert.equal(new Set(ids).size, ids.length);
  }
});

test("highway popups cover every highway and elevator layer", () => {
  const ids = hover.flatMap(h => h.ids);
  for (const id of ["highway-footway", "highway-steps", "highway-crossing", ...palette.elevatorLayerIds]) {
    assert.ok(ids.includes(id), id);
  }
});

test("no OSM value can inject markup into any popup", () => {
  for (const [kind, entry] of entries) {
    const keys = readKeys(entry.format);
    for (const payload of PAYLOADS) {
      for (const type of TYPES) {
        const html = entry.format(hostile(keys, payload, type));
        assertInert(html, `${kind} ${entry.ids.join(",") || "highways"} type=${type}`);
      }
    }
  }
});

test("missing crossing popup dispatches wrong_tag to its own formatter", () => {
  const html = clickFormat("missing-crossings")({ type: "wrong_tag", osm_id: 5, way_osm_id: 7, footway_value: "sidewalk", name: "Rue A" });
  assert.match(html, /Traversée taguée footway=sidewalk/);
  assert.match(html, /load_object\?objects=n5,w7/);
  assert.equal(html, P.formatWrongTagCrossing({ type: "wrong_tag", osm_id: 5, way_osm_id: 7, footway_value: "sidewalk", name: "Rue A" }, fr));
});

test("nearest footway=crossing distance is shown for missing tags only", () => {
  const format = clickFormat("missing-crossings");
  assert.match(format({ type: "missing_tag", nearest_tag_m: 2.4, detect_radius: 3, osm_id: 1 }), /2,4 m.*rayon 3 m/s);
  assert.doesNotMatch(format({ type: "missing_way", nearest_tag_m: 2.4, osm_id: 1 }), /le plus proche/);
  assert.doesNotMatch(format({ type: "missing_tag", nearest_tag_m: -1, osm_id: 1 }), /le plus proche/);
});

test("osm ids that are not positive numbers produce no link", () => {
  const html = clickFormat("missing-crossings")({ type: "missing_way", osm_id: "abc" });
  assert.doesNotMatch(html, /openstreetmap\.org\/node/);
});

test("tactile paving popup flags the unchecked side and links the contiguous way", () => {
  const html = clickFormat("tactile-paving-issues")({
    osm_id: 3, way_osm_id: 7, partner_way_osm_id: 8, sides_checked: 1,
    crossing_tp: "yes", kerb1_tp: "no", reason: "value_mismatch",
  });
  assert.match(html, /non vérifié/);
  assert.match(html, /objects=w7,w8/);
  assert.match(html, /tactile_paving du kerb différent/);
});

test("graph island popup builds a JOSM zoom on the bbox with the ways selected", () => {
  const html = clickFormat("graph-islands")({
    type: "isolated", way_ids: "1,2,3,4,5,6,7", gap_m: 12.5, length_m: 40.4,
    bbox_w: 4.35, bbox_s: 50.85, bbox_e: 4.36, bbox_n: 50.86, highways: "footway",
  });
  assert.match(html, /Îlot isolé du réseau/);
  assert.match(html, /load_and_zoom\?left=4\.349500&right=4\.360500&top=50\.860500&bottom=50\.849500&select=w1,w2,w3,w4,w5,w6,w7/);
  assert.match(html, /\+2/);
  assert.match(html, /12,5 m/);
  assert.match(html, /40 m/);
});

test("level discontinuity popup shows the levels and the node", () => {
  const html = clickFormat("graph-islands")({ type: "level", level_values: "0|1", level_missing: "", node_id: 9, way_ids: "4" });
  assert.match(html, /Discontinuité de niveau/);
  assert.match(html, /0 ≠ 1/);
  assert.match(html, /node\/9/);
  assert.doesNotMatch(html, /Écart au réseau/);
});

test("kerb popup links the kerb only when it exists", () => {
  const format = clickFormat("kerb-issues");
  assert.match(format({ type: "kerb_untagged", crossing_osm_id: 1, kerb_osm_id: 2, way_osm_id: 3 }), /node\/2/);
  assert.doesNotMatch(format({ type: "kerb_missing", crossing_osm_id: 1, kerb_osm_id: 2, way_osm_id: 3 }), /node\/2/);
});

test("highway popup hides technical keys and colours elevators", () => {
  const format = hoverFormat("highway-footway");
  const html = format({ highway: "footway", surface: "asphalt", "@id": 12, tippecanoe: { minzoom: 9 } });
  assert.match(html, /surface/);
  assert.doesNotMatch(html, /@id|tippecanoe/);
  assert.match(html, /--c:#22c55e/);
  assert.match(format({ amenity: "elevator" }), new RegExp(`--c:${palette.elevatorColor}`));
});

test("flow popup reads infra_type, highway and flow_pct", () => {
  const html = hoverFormat("flow-road")({ infra_type: "cycleway_no_foot", highway: "cycleway", flow_pct: 0 });
  assert.match(html, /Piste cyclable sans foot=yes/);
  assert.match(html, new RegExp(fr.percent(0)));
});

test("sidewalk status popup translates the status", () => {
  const html = hoverFormat("sidewalk-roads")({ sw: "partial", name: "Rue B" });
  assert.match(html, /Un seul côté documenté/);
  assert.match(html, /--c:#f5700b/);
});

test("formatLevels describes a level that the connected way does not reach", () => {
  assert.equal(P.formatLevels({ level_values: "1;2", level_missing: "1" }, fr), "1;2 : niveau 1 non raccordé");
  assert.equal(P.formatLevels({ level_values: "-2;-1", level_missing: -2 }, fr), "-2;-1 : niveau -2 non raccordé");
});

test("formatLevels lists mismatched levels and names untagged ones", () => {
  assert.equal(P.formatLevels({ level_values: "-1|1", level_missing: "" }, fr), "-1 ≠ 1");
  assert.equal(P.formatLevels({ level_values: "|1", level_missing: "" }, fr), "0 (non tagué) ≠ 1");
  assert.equal(P.formatLevels({ level_values: "", level_missing: "0.5" }, fr), "0 (non tagué) : niveau 0.5 non raccordé");
});

test("formatLevels shows a dash when the feature carries no level data", () => {
  assert.equal(P.formatLevels({}, fr), "—");
  assert.equal(P.formatLevels({ level_values: null }, fr), "—");
});

test("graph island popup escapes level values", () => {
  const html = clickFormat("graph-islands")({ type: "level", level_values: "<b>1</b>", level_missing: "" });
  assert.ok(!html.includes("<b>1</b>"));
  assert.ok(html.includes("&lt;b&gt;1&lt;/b&gt;"));
});

const SAMPLES = [
  ["hover", "sidewalk-gaps", { name: "Rue A" }],
  ["hover", "footway-crossing-candidates", { name: "Rue A", length_m: 12.34 }],
  ...["separate", "yes", "documented", "partial", "unknown"].map(sw => ["hover", "sidewalk-roads", { sw, name: "Rue A" }]),
  ...["pedestrian", "road", "cycleway_foot_yes", "cycleway_no_foot"].map(infra => ["hover", "flow-road", { infra_type: infra, highway: "footway", flow_pct: 42.5 }]),
  ["hover", "highway-footway", { highway: "footway" }],
  ["hover", "highway-elevator", {}],
  ...["missing_way", "missing_tag", "wrong_tag"].map(type => ["click", "missing-crossings", { type, osm_id: 1, way_osm_id: 2, nearest_tag_m: 2.4, detect_radius: 3, name: "Rue A" }]),
  ["click", "footway-crossing-candidates", { osm_id: 3, length_m: 8, name: "Rue A" }],
  ...[1, 2].map(sides => ["click", "tactile-paving-issues", { osm_id: 3, way_osm_id: 4, partner_way_osm_id: 5, sides_checked: sides, crossing_tp: "yes", reason: "value_mismatch" }]),
  ["click", "tactile-paving-issues", { osm_id: 3, reason: "incorrect_not_mixed" }],
  ...["unjoined", "isolated"].map(type => ["click", "graph-islands", { type, way_ids: "1,2", gap_m: 1.5, length_m: 30, bbox_w: 4.35, bbox_s: 50.85, bbox_e: 4.36, bbox_n: 50.86 }]),
  ["click", "graph-islands", { type: "level", level_values: "|1", level_missing: "", node_id: 9, way_ids: "4" }],
  ["click", "graph-islands", { type: "level", level_values: "1;2", level_missing: "1", node_id: 9, way_ids: "4" }],
  ...["kerb_missing", "kerb_untagged"].map(type => ["click", "kerb-issues", { type, crossing_osm_id: 1, kerb_osm_id: 2, way_osm_id: 3, partner_way_osm_id: 4 }]),
];

for (const lang of Object.keys(LANGUAGES.languages)) {
  test(`every popup renders in ${lang} without a missing key`, () => {
    const warnings = [];
    const i18n = i18nFor(lang, warnings);
    const layers = P.makePopupLayers(palette, i18n);
    for (const [kind, id, props] of SAMPLES) {
      const entry = layers[kind].find(e => e.ids.includes(id));
      assert.ok(entry, `${kind} ${id}`);
      const html = entry.format(props);
      assert.doesNotMatch(html, /\b(?:popup|layer)\.[a-z]+\.[A-Za-z.]+/, `${kind} ${id} shows a raw key`);
    }
    assert.deepEqual(warnings, []);
  });
}

test("popups speak English with English number formats", () => {
  const layers = P.makePopupLayers(palette, en);
  const island = layers.click.find(c => c.ids.includes("graph-islands")).format;
  const html = island({ type: "isolated", gap_m: 1234.5, length_m: 40.4, way_ids: "1" });
  assert.match(html, /Island isolated from the network/);
  assert.match(html, /Gap to the network/);
  assert.match(html, /1,234\.5 m/);
  assert.equal(P.formatLevels({ level_values: "1;2", level_missing: "1" }, en), "1;2: level 1 not connected");
  assert.equal(P.formatLevels({ level_values: "|1", level_missing: "" }, en), "0 (untagged) ≠ 1");
});

test("translated wording is escaped like OSM values", () => {
  const layers = P.makePopupLayers(palette, { ...en, t: () => "<img src=x onerror=alert(1)>" });
  const html = layers.hover.find(h => h.ids.includes("sidewalk-gaps")).format({ name: "Rue A" });
  assert.doesNotMatch(html, /<img/);
});

test("measures and shares fall back to the raw value when it is not a number", () => {
  assert.equal(P.formatMeasure(en, "12.345"), "12.3");
  assert.equal(P.formatMeasure(en, "<b>"), "&lt;b&gt;");
  assert.equal(P.formatMeasure(en, undefined), undefined);
  assert.equal(P.formatShare(en, 42.5), "42.5%");
  assert.equal(P.formatShare(en, undefined), "0%");
  assert.equal(P.formatShare(en, "<b>"), "&lt;b&gt; %");
});
