const test = require("node:test");
const assert = require("node:assert/strict");
const { parseHTML } = require("linkedom");
const L = require("../../lang.js");

const SETTINGS = {
  current: "fr",
  isRoot: true,
  languages: [
    { lang: "fr", href: "/fr/", banner: { text: "Version française", switch: "Passer en français", dismiss: "Fermer" } },
    { lang: "nl", href: "/nl/", banner: { text: "Nederlandse versie", switch: "Naar het Nederlands", dismiss: "Sluiten" } },
  ],
};

function page({ saved = null, languages = ["nl-BE", "fr"], settings = SETTINGS, banner = true, readyState = "complete", hash = "#17/50.8/4.4" } = {}) {
  const { document } = parseHTML(`<!doctype html><html lang="${settings.current}"><body>
    <script type="application/json" id="i18n-languages">${JSON.stringify(settings)}</script>
    ${banner ? `<div id="lang-banner" hidden><span id="lang-banner-text"></span><a id="lang-banner-switch" href="#"></a><button id="lang-banner-close"></button></div>` : ""}
    <nav class="lang-switch"><a data-lang="nl" href="/nl/">NL</a><a data-lang="fr" href="/fr/">FR</a></nav>
  </body></html>`);
  Object.defineProperty(document, "readyState", { value: readyState, configurable: true });
  const store = new Map(saved ? [[L.STORAGE_KEY, saved]] : []);
  const visits = [];
  const win = {
    document,
    visits,
    store,
    navigator: { languages },
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) },
    location: { hash, replace: url => visits.push(["replace", url]), assign: url => visits.push(["assign", url]) },
  };
  return win;
}

const click = el => el.dispatchEvent(new el.ownerDocument.defaultView.Event("click", { cancelable: true }));

test("a Dutch browser on the French page gets a banner in Dutch that switches and remembers", () => {
  const win = page();
  assert.equal(L.initLanguageBanner(win), true);
  const doc = win.document;
  const banner = doc.getElementById("lang-banner");
  assert.equal(banner.hidden, false);
  assert.equal(banner.lang, "nl");
  assert.equal(doc.getElementById("lang-banner-text").textContent, "Nederlandse versie");
  const link = doc.getElementById("lang-banner-switch");
  assert.equal(link.getAttribute("href"), "/nl/");
  assert.equal(link.getAttribute("hreflang"), "nl");
  assert.equal(doc.getElementById("lang-banner-close").getAttribute("aria-label"), "Sluiten");
  click(link);
  assert.equal(win.store.get(L.STORAGE_KEY), "nl");
  assert.deepEqual(win.visits, [["assign", "/nl/#17/50.8/4.4"]]);
});

test("closing the banner keeps the page language and the banner stays away", () => {
  const win = page();
  L.initLanguageBanner(win);
  click(win.document.getElementById("lang-banner-close"));
  assert.equal(win.document.getElementById("lang-banner").hidden, true);
  assert.equal(win.store.get(L.STORAGE_KEY), "fr");
  const again = page({ saved: "fr" });
  assert.equal(L.initLanguageBanner(again), false);
  assert.equal(again.document.getElementById("lang-banner").hidden, true);
});

test("no banner without a banner element, for the same language or an unavailable one", () => {
  assert.equal(L.initLanguageBanner(page({ banner: false })), false);
  assert.equal(L.initLanguageBanner(page({ languages: ["fr-BE"] })), false);
  assert.equal(L.initLanguageBanner(page({ languages: ["de-DE"] })), false);
  assert.equal(L.initLanguageBanner(page({ languages: [] })), false);
});

test("the language links remember the choice and keep the map position", () => {
  const win = page();
  L.initLanguageLinks(win);
  click(win.document.querySelector('.lang-switch [data-lang="nl"]'));
  assert.equal(win.store.get(L.STORAGE_KEY), "nl");
  assert.deepEqual(win.visits, [["assign", "/nl/#17/50.8/4.4"]]);
});

test("start redirects a returning visitor before wiring anything", () => {
  const win = page({ saved: "nl" });
  L.start(win);
  assert.deepEqual(win.visits, [["replace", "/nl/#17/50.8/4.4"]]);
  assert.equal(win.document.getElementById("lang-banner").hidden, true);
});

test("start waits for the document when it is still loading", () => {
  const win = page({ readyState: "loading" });
  L.start(win);
  assert.equal(win.document.getElementById("lang-banner").hidden, true);
  win.document.dispatchEvent(new win.document.defaultView.Event("DOMContentLoaded"));
  assert.equal(win.document.getElementById("lang-banner").hidden, false);
});

test("a page without language settings falls back to its own language and does nothing", () => {
  const { document } = parseHTML('<!doctype html><html lang="en"><body><div id="lang-banner" hidden></div></body></html>');
  const win = { document, navigator: { languages: ["nl"] }, localStorage: { getItem: () => "nl", setItem() {} }, location: { hash: "" } };
  assert.equal(L.redirectToSavedLanguage(win), false);
  assert.equal(L.initLanguageBanner(win), false);
});

test("a browser that only reports navigator.language still gets its banner", () => {
  const win = page({ languages: undefined });
  win.navigator = { language: "nl" };
  assert.equal(L.initLanguageBanner(win), true);
});
