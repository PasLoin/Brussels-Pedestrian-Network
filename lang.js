(function (global) {
  const STORAGE_KEY = "bpn-lang";

  function readChoice(storage) {
    try { return storage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }

  function saveChoice(storage, lang) {
    try { storage.setItem(STORAGE_KEY, lang); } catch (e) {}
  }

  function primaryBrowserLang(languages) {
    const first = (languages || [])[0];
    return first ? first.slice(0, 2).toLowerCase() : null;
  }

  function suggestedLang({ pageLang, available, browserLanguages, savedChoice }) {
    if (savedChoice) return null;
    const primary = primaryBrowserLang(browserLanguages);
    if (!primary || primary === pageLang || !available.includes(primary)) return null;
    return primary;
  }

  function redirectTarget({ pageLang, isRoot, savedChoice, available }) {
    if (!isRoot || !savedChoice || savedChoice === pageLang || !available.includes(savedChoice)) return null;
    return savedChoice;
  }

  function readSettings(doc) {
    const node = doc.getElementById("i18n-languages");
    return node ? JSON.parse(node.textContent) : { current: doc.documentElement.lang, isRoot: false, languages: [] };
  }

  function byLang(settings) {
    return Object.fromEntries(settings.languages.map(l => [l.lang, l]));
  }

  function redirectToSavedLanguage(win = global) {
    const settings = readSettings(win.document);
    const languages = byLang(settings);
    const target = redirectTarget({
      pageLang: settings.current,
      isRoot: settings.isRoot,
      savedChoice: readChoice(win.localStorage),
      available: Object.keys(languages),
    });
    if (!target) return false;
    win.location.replace(languages[target].href + win.location.hash);
    return true;
  }

  function initLanguageLinks(win = global) {
    const doc = win.document;
    doc.querySelectorAll(".lang-switch [data-lang]").forEach(link => {
      link.addEventListener("click", e => {
        e.preventDefault();
        saveChoice(win.localStorage, link.dataset.lang);
        win.location.assign(link.getAttribute("href") + win.location.hash);
      });
    });
  }

  function initLanguageBanner(win = global) {
    const doc = win.document;
    const banner = doc.getElementById("lang-banner");
    if (!banner) return false;
    const settings = readSettings(doc);
    const languages = byLang(settings);
    const target = suggestedLang({
      pageLang: settings.current,
      available: Object.keys(languages),
      browserLanguages: win.navigator.languages || [win.navigator.language],
      savedChoice: readChoice(win.localStorage),
    });
    if (!target) return false;
    const { href, banner: strings } = languages[target];
    const switchLink = doc.getElementById("lang-banner-switch");
    const close = doc.getElementById("lang-banner-close");
    banner.lang = target;
    doc.getElementById("lang-banner-text").textContent = strings.text;
    switchLink.textContent = strings.switch;
    switchLink.setAttribute("href", href);
    switchLink.setAttribute("hreflang", target);
    close.title = strings.dismiss;
    close.setAttribute("aria-label", strings.dismiss);
    switchLink.addEventListener("click", e => {
      e.preventDefault();
      saveChoice(win.localStorage, target);
      win.location.assign(href + win.location.hash);
    });
    close.addEventListener("click", () => {
      saveChoice(win.localStorage, settings.current);
      banner.hidden = true;
    });
    banner.hidden = false;
    return true;
  }

  function start(win = global) {
    if (redirectToSavedLanguage(win)) return;
    const ready = () => {
      initLanguageLinks(win);
      initLanguageBanner(win);
    };
    if (win.document.readyState === "loading") win.document.addEventListener("DOMContentLoaded", ready);
    else ready();
  }

  const api = { STORAGE_KEY, primaryBrowserLang, suggestedLang, redirectTarget, redirectToSavedLanguage, initLanguageLinks, initLanguageBanner, start };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    global.BPNLang = api;
    start(global);
  }
})(typeof window !== "undefined" ? window : globalThis);
