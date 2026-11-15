const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { html } = require("../../html.js");
const { i18nFor } = require("./dictionaries.js");

globalThis.html = html;

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);

function square(x0, y0, size) {
  return [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]];
}

const COMMUNES = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", properties: { name: "Woluwe-Saint-Lambert - Sint-Lambrechts-Woluwe", name_fr: "Woluwe-Saint-Lambert", name_nl: "Sint-Lambrechts-Woluwe" },
      geometry: { type: "Polygon", coordinates: [square(4.40, 50.83, 0.04), square(4.41, 50.84, 0.005)] } },
    { type: "Feature", properties: { name: "", name_fr: "Etterbeek", name_nl: "Etterbeek" },
      geometry: { type: "MultiPolygon", coordinates: [[square(4.37, 50.83, 0.02)]] } },
    { type: "Feature", properties: { name: "", name_fr: "Ixelles", name_nl: "Elsene" },
      geometry: { type: "Polygon", coordinates: [square(4.35, 50.80, 0.02)] } },
  ],
};

function entry(id, tags, center) {
  const [x, y] = center;
  return { intent: { wayId: id, bbox: [x - 0.0005, y - 0.0005, x + 0.0005, y + 0.0005] }, way: { id, tags } };
}

const PAUWELS = { highway: "residential", name: "Avenue Henri Pauwels - Henri Pauwelslaan", "name:fr": "Avenue Henri Pauwels", "name:nl": "Henri Pauwelslaan" };
const street = (fr, nl) => ({ highway: "residential", name: `${fr} - ${nl}`, "name:fr": fr, "name:nl": nl });

test("street labels follow the Brussels fr/nl practice", async () => {
  const { streetLabel } = await load("places.js");
  assert.equal(streetLabel(PAUWELS), "Avenue Henri Pauwels/Henri Pauwelslaan");
  assert.equal(streetLabel({ name: "Rue X", "name:fr": "Rue X", "name:nl": "Rue X" }), "Rue X");
  assert.equal(streetLabel({ name: "Clos du Bois" }), "Clos du Bois");
  assert.equal(streetLabel({ "name:nl": "Bosstraat" }), "Bosstraat");
  assert.equal(streetLabel({}), "");
  assert.equal(streetLabel(undefined), "");
});

test("a point is matched to its municipality, holes and outside points excluded", async () => {
  const { indexCommunes, communeAt } = await load("places.js");
  const index = indexCommunes(COMMUNES);
  assert.equal(communeAt([4.43, 50.86], index), "Woluwe-Saint-Lambert - Sint-Lambrechts-Woluwe");
  assert.equal(communeAt([4.4125, 50.8425], index), null);
  assert.equal(communeAt([4.38, 50.84], index), "Etterbeek");
  assert.equal(communeAt([4.36, 50.81], index), "Ixelles - Elsene");
  assert.equal(communeAt([4.59, 50.83], index), null);
  assert.deepEqual(indexCommunes(null), []);
  assert.deepEqual(indexCommunes({ features: [{ properties: {}, geometry: null }] }), []);
});

test("one street gives the street then the action", async () => {
  const { indexCommunes, describeGroup, composeComment } = await load("places.js");
  const index = indexCommunes(COMMUNES);
  const d = describeGroup([entry(1, PAUWELS, [4.43, 50.86]), entry(2, PAUWELS, [4.431, 50.861])], index);
  assert.equal(composeComment(d), "Avenue Henri Pauwels/Henri Pauwelslaan - add sidewalk tags");
});

test("several streets in one municipality give the municipality then the action", async () => {
  const { indexCommunes, describeGroup, composeComment } = await load("places.js");
  const index = indexCommunes(COMMUNES);
  const entries = [];
  for (let i = 0; i < 9; i++) entries.push(entry(i + 1, street(`Rue ${i}`, `${i}straat`), [4.42 + i * 0.001, 50.86]));
  entries.push(entry(99, street("Rue 0", "0straat"), [4.43, 50.865]));
  const d = describeGroup(entries, index);
  assert.equal(d.count, 9);
  assert.equal(composeComment(d), "Woluwe-Saint-Lambert - Sint-Lambrechts-Woluwe : add sidewalk tags on 9 residential streets");
});

test("a group across two municipalities names both, outside Brussels only the action", async () => {
  const { indexCommunes, describeGroup, composeComment } = await load("places.js");
  const index = indexCommunes(COMMUNES);
  const across = describeGroup([entry(1, street("Rue A", "Astraat"), [4.38, 50.84]), entry(2, street("Rue B", "Bstraat"), [4.36, 50.81])], index);
  assert.equal(composeComment(across), "Etterbeek / Ixelles - Elsene : add sidewalk tags on 2 residential streets");
  const outside = describeGroup([entry(1, street("Rue A", "Astraat"), [4.59, 50.83]), entry(2, { highway: "residential" }, [4.591, 50.83])], index);
  assert.equal(composeComment(outside), "Add sidewalk tags on 2 residential streets");
  const unnamed = describeGroup([entry(1, { highway: "residential" }, [4.59, 50.83])], index);
  assert.equal(composeComment(unnamed), "Add sidewalk tags on 1 residential street");
  assert.equal(composeComment(describeGroup([entry(1, PAUWELS, [4.43, 50.86])], [])), "Avenue Henri Pauwels/Henri Pauwelslaan - add sidewalk tags");
});

test("the remark and hashtags follow the generated text without duplicates", async () => {
  const { indexCommunes, describeGroup, composeComment } = await load("places.js");
  const d = describeGroup([entry(1, PAUWELS, [4.43, 50.86])], indexCommunes(COMMUNES));
  assert.equal(composeComment(d, { remark: " vérifié sur place ", hashtags: ["#bpn", "#test"] }),
    "Avenue Henri Pauwels/Henri Pauwelslaan - add sidewalk tags - vérifié sur place #bpn #test");
  assert.equal(composeComment(d, { remark: "voir #bpn", hashtags: ["#bpn"] }),
    "Avenue Henri Pauwels/Henri Pauwelslaan - add sidewalk tags - voir #bpn");
});

test("a comment never exceeds 255 characters and falls back to shorter forms", async () => {
  const { composeComment, MAX_COMMENT } = await load("places.js");
  const long = { streets: ["S".repeat(240)], unnamed: 0, communes: ["Ixelles - Elsene"], count: 1 };
  const out = composeComment(long, { hashtags: ["#bpn"] });
  assert.equal(out, "Ixelles - Elsene : add sidewalk tags on 1 residential street #bpn");
  const huge = { streets: ["a", "b"], unnamed: 0, communes: ["C".repeat(300)], count: 2 };
  assert.equal(composeComment(huge, { remark: "r".repeat(120) }), `Add sidewalk tags on 2 residential streets - ${"r".repeat(120)}`);
  assert.equal(composeComment(huge), "Add sidewalk tags on 2 residential streets");
  const overflow = composeComment(huge, { remark: "r".repeat(250), hashtags: ["#bpn"] });
  assert.equal(overflow, "Add sidewalk tags on 2 residential streets #bpn");
  for (const text of [out, composeComment(huge), overflow]) assert.ok(text.length <= MAX_COMMENT);
});

test("changesets of one upload each get a comment about their own ways", async () => {
  const { indexCommunes, describeGroup, composeComment } = await load("places.js");
  const index = indexCommunes(COMMUNES);
  const north = [1, 2, 3].map(i => entry(i, street(`Rue ${i}`, `${i}straat`), [4.42 + i * 0.002, 50.86]));
  const south = [entry(4, street("Rue Sud", "Zuidstraat"), [4.36, 50.81])];
  assert.deepEqual([north, south].map(g => composeComment(describeGroup(g, index), { hashtags: ["#test"] })), [
    "Woluwe-Saint-Lambert - Sint-Lambrechts-Woluwe : add sidewalk tags on 3 residential streets #test",
    "Rue Sud/Zuidstraat - add sidewalk tags #test",
  ]);
});

test("the plan shows one comment per changeset and the remark field replaces the free comment", async () => {
  const { queueView } = await load("panel.js");
  const intent = { wayId: 5, set: { "sidewalk:both": "no" }, name: "Rue A" };
  const form = { remark: "<b>ok</b>", sources: [], sourceOther: "", hashtags: "", review: false };
  const out = String(queueView({
    items: [intent], form, busy: false, loggedIn: true, result: null,
    plan: { ready: [{}, {}], groups: [{}, {}], tooMany: false, max: 3, dropped: [] },
    comments: ["Rue A/Astraat - add sidewalk tags", "Ixelles - Elsene : add sidewalk tags on 3 residential streets <x>"],
  }, i18nFor("fr"), "https://dev", { sourcePresets: [] }));
  assert.match(out, /name="cs-remark"/);
  assert.doesNotMatch(out, /cs-comment/);
  assert.doesNotMatch(out, /<b>ok<\/b>/);
  assert.match(out, /Commentaire du changeset 1[\s\S]*data-comment-group="0">Rue A\/Astraat - add sidewalk tags</);
  assert.match(out, /data-comment-group="1">Ixelles - Elsene : add sidewalk tags on 3 residential streets &lt;x&gt;</);
});

test("results report the automatic retry and the ways dropped for changed geometry", async () => {
  const { queueView } = await load("panel.js");
  const form = { remark: "", sources: [], sourceOther: "", hashtags: "", review: false };
  const out = String(queueView({
    items: [], form, plan: null, busy: false, loggedIn: true,
    result: { done: [{ changesetIds: [7], wayIds: [1] }], failed: null, conflictWayId: null, closed: [3], retried: 1,
      dropped: [{ intent: { wayId: 2, name: "Rue B" }, reason: "geometry_changed" }] },
  }, i18nFor("fr"), "https://dev", { sourcePresets: [] }));
  assert.match(out, /le groupe a été relu et renvoyé une fois/);
  assert.match(out, /Rue B \(w2\) : géométrie modifiée depuis/);
  assert.match(out, /1 changeset vide fermé/);
});
