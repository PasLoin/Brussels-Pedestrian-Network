const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../../lang.js");

function fakeWindow({ settings, saved = null, hash = "" }) {
  const store = new Map(saved ? [[L.STORAGE_KEY, saved]] : []);
  const visits = [];
  return {
    visits,
    store,
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) },
    location: { hash, replace: url => visits.push(["replace", url]), assign: url => visits.push(["assign", url]) },
    document: {
      documentElement: { lang: settings.current },
      getElementById: id => (id === "i18n-languages" ? { textContent: JSON.stringify(settings) } : null),
    },
  };
}

const ROOT_EN = {
  current: "en",
  isRoot: true,
  languages: [
    { lang: "en", name: "English", href: "./stats.html", banner: {} },
    { lang: "fr", name: "Français", href: "./fr/stats.html", banner: {} },
  ],
};
const FR_PAGE = { ...ROOT_EN, current: "fr", isRoot: false };

test("primaryBrowserLang keeps the first preference only", () => {
  assert.equal(L.primaryBrowserLang(["fr-BE", "en"]), "fr");
  assert.equal(L.primaryBrowserLang(["NL"]), "nl");
  assert.equal(L.primaryBrowserLang([]), null);
  assert.equal(L.primaryBrowserLang(undefined), null);
});

test("suggestedLang proposes the browser language when the page differs", () => {
  const base = { pageLang: "en", available: ["en", "fr"], savedChoice: null };
  assert.equal(L.suggestedLang({ ...base, browserLanguages: ["fr-BE"] }), "fr");
  assert.equal(L.suggestedLang({ ...base, browserLanguages: ["en-GB"] }), null);
  assert.equal(L.suggestedLang({ ...base, browserLanguages: ["nl-BE", "fr"] }), null);
  assert.equal(L.suggestedLang({ ...base, browserLanguages: ["fr"], savedChoice: "en" }), null);
});

test("redirectTarget only acts on root pages with a different saved choice", () => {
  const base = { pageLang: "en", available: ["en", "fr"] };
  assert.equal(L.redirectTarget({ ...base, isRoot: true, savedChoice: "fr" }), "fr");
  assert.equal(L.redirectTarget({ ...base, isRoot: false, savedChoice: "fr" }), null);
  assert.equal(L.redirectTarget({ ...base, isRoot: true, savedChoice: "en" }), null);
  assert.equal(L.redirectTarget({ ...base, isRoot: true, savedChoice: "de" }), null);
  assert.equal(L.redirectTarget({ ...base, isRoot: true, savedChoice: null }), null);
});

test("a root page sends a returning visitor to the saved language and keeps the hash", () => {
  const win = fakeWindow({ settings: ROOT_EN, saved: "fr", hash: "#14/50.85/4.35" });
  assert.equal(L.redirectToSavedLanguage(win), true);
  assert.deepEqual(win.visits, [["replace", "./fr/stats.html#14/50.85/4.35"]]);
});

test("a language page never redirects, so shared links keep their language", () => {
  const win = fakeWindow({ settings: FR_PAGE, saved: "en" });
  assert.equal(L.redirectToSavedLanguage(win), false);
  assert.deepEqual(win.visits, []);
});

test("unreadable storage behaves like no saved choice", () => {
  const win = fakeWindow({ settings: ROOT_EN });
  win.localStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(L.redirectToSavedLanguage(win), false);
});
