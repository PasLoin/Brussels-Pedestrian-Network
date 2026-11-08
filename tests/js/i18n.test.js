const test = require("node:test");
const assert = require("node:assert/strict");
const { createI18n, fromDocument } = require("../../i18n.js");

const DICT = {
  "route.noRoute": "No route found",
  "route.walkTime": "≈ {{minutes}} min walk",
  "route.spaced": "{{ name }} and {{name}}",
  "map.trips_one": "{{count}} simulated trip",
  "map.trips_other": "{{count}} simulated trips",
  "map.layers_other": "{{count}} layers",
};

function fakeDocument({ lang = "fr", dataset = {}, dict, hostname = "pasloin.github.io" } = {}) {
  return {
    documentElement: { lang, dataset },
    getElementById: id => (id === "i18n-dict" && dict !== undefined ? { textContent: dict } : null),
    location: { hostname },
  };
}

test("t returns the translation of a known key", () => {
  const { t } = createI18n({ dict: DICT });
  assert.equal(t("route.noRoute"), "No route found");
});

test("t returns the key and warns when the key is missing", () => {
  const warnings = [];
  const { t } = createI18n({ lang: "fr", dict: DICT, warn: m => warnings.push(m) });
  assert.equal(t("route.unknown"), "route.unknown");
  assert.deepEqual(warnings, ["[i18n] missing key (fr): route.unknown"]);
});

test("t fills variables written with or without inner spaces", () => {
  const { t } = createI18n({ dict: DICT });
  assert.equal(t("route.spaced", { name: "Ana" }), "Ana and Ana");
});

test("t leaves unknown variables visible instead of hiding them", () => {
  const { t } = createI18n({ dict: DICT });
  assert.equal(t("route.walkTime"), "≈ {{minutes}} min walk");
  assert.equal(t("route.walkTime", { other: 1 }), "≈ {{minutes}} min walk");
});

test("t formats numeric variables with the page locale", () => {
  const fr = createI18n({ locale: "fr-BE", dict: DICT });
  const en = createI18n({ locale: "en-GB", dict: DICT });
  assert.equal(fr.t("route.walkTime", { minutes: 1234.5 }), `≈ ${new Intl.NumberFormat("fr-BE").format(1234.5)} min walk`);
  assert.equal(en.t("route.walkTime", { minutes: 1234.5 }), "≈ 1,234.5 min walk");
  assert.equal(en.t("route.walkTime", { minutes: "12" }), "≈ 12 min walk");
});

test("t picks the plural form from the locale rules", () => {
  const en = createI18n({ locale: "en-GB", dict: DICT });
  const fr = createI18n({ locale: "fr-BE", dict: DICT });
  assert.equal(en.t("map.trips", { count: 1 }), "1 simulated trip");
  assert.equal(en.t("map.trips", { count: 0 }), "0 simulated trips");
  assert.equal(fr.t("map.trips", { count: 0 }), "0 simulated trip");
  assert.equal(en.t("map.trips", { count: 2500 }), "2,500 simulated trips");
});

test("t falls back to the other form when the locale category is missing", () => {
  const { t } = createI18n({ locale: "en-GB", dict: DICT });
  assert.equal(t("map.layers", { count: 1 }), "1 layers");
});

test("t warns about a plural family that has no form at all", () => {
  const warnings = [];
  const { t } = createI18n({ dict: DICT, warn: m => warnings.push(m) });
  assert.equal(t("map.unknown", { count: 3 }), "map.unknown");
  assert.equal(warnings.length, 1);
});

test("has knows plain keys and plural families", () => {
  const { has } = createI18n({ dict: DICT });
  assert.equal(has("route.noRoute"), true);
  assert.equal(has("map.trips"), true);
  assert.equal(has("map.unknown"), false);
});

test("percent takes a value between 0 and 100", () => {
  const fr = createI18n({ locale: "fr-BE" });
  const en = createI18n({ locale: "en-GB" });
  assert.equal(en.percent(45.33), "45.3%");
  assert.equal(fr.percent(45.33), new Intl.NumberFormat("fr-BE", { style: "percent", maximumFractionDigits: 1 }).format(0.4533));
  assert.equal(en.percent(45.33, { maximumFractionDigits: 0 }), "45%");
});

test("number reuses formats and honours options", () => {
  const en = createI18n({ locale: "en-GB" });
  assert.equal(en.number(1234.567, { maximumFractionDigits: 2 }), "1,234.57");
  assert.equal(en.number(1234.567, { maximumFractionDigits: 2 }), "1,234.57");
  assert.equal(en.number(1234.567, { maximumFractionDigits: 0 }), "1,235");
});

test("date uses the configured time zone", () => {
  const brussels = createI18n({ locale: "en-GB", timeZone: "Europe/Brussels" });
  const utc = createI18n({ locale: "en-GB", timeZone: "UTC" });
  assert.equal(brussels.date("2026-11-07T23:30:00Z", { day: "numeric" }), "8");
  assert.equal(utc.date(new Date("2026-11-07T23:30:00Z"), { day: "numeric" }), "7");
});

test("dataUrl points to the shared data from any language folder", () => {
  assert.equal(createI18n().dataUrl("stats.json"), "./stats.json");
  assert.equal(createI18n({ root: "../" }).dataUrl("pedestrian.pmtiles"), "../pedestrian.pmtiles");
});

test("fromDocument reads the page settings and the embedded dictionary", () => {
  const i18n = fromDocument(fakeDocument({
    lang: "fr",
    dataset: { locale: "fr-BE", timeZone: "Europe/Brussels", root: "../" },
    dict: JSON.stringify({ "route.noRoute": "Aucun itinéraire" }),
  }));
  assert.equal(i18n.lang, "fr");
  assert.equal(i18n.locale, "fr-BE");
  assert.equal(i18n.timeZone, "Europe/Brussels");
  assert.equal(i18n.dataUrl("graph.json"), "../graph.json");
  assert.equal(i18n.t("route.noRoute"), "Aucun itinéraire");
});

test("fromDocument falls back to safe defaults without settings or dictionary", () => {
  const i18n = fromDocument(fakeDocument({ lang: "" }));
  assert.equal(i18n.lang, "en");
  assert.equal(i18n.locale, "en");
  assert.equal(i18n.dataUrl("stats.json"), "./stats.json");
  assert.equal(i18n.t("route.noRoute"), "route.noRoute");
});

test("fromDocument warns about missing keys only on a local server", t => {
  const warn = t.mock.method(console, "warn", () => {});
  fromDocument(fakeDocument({ dict: "{}" })).t("a.b");
  assert.equal(warn.mock.callCount(), 0);
  fromDocument(fakeDocument({ dict: "{}", hostname: "localhost" })).t("a.b");
  fromDocument(fakeDocument({ dict: "{}", hostname: "127.0.0.1" })).t("a.b");
  assert.equal(warn.mock.callCount(), 2);
  assert.match(warn.mock.calls[0].arguments[0], /missing key \(fr\): a\.b/);
});
