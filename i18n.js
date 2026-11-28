(function (global) {
  const PLACEHOLDER = /\{\{\s*(\w+)\s*\}\}/g;
  const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

  function createI18n({
    lang = "en",
    locale = lang,
    timeZone,
    root = "./",
    dict = {},
    warn = () => {},
  } = {}) {
    const pluralRules = new Intl.PluralRules(locale);
    const numberFormats = new Map();

    function number(value, options = {}) {
      const cacheKey = JSON.stringify(options);
      if (!numberFormats.has(cacheKey)) numberFormats.set(cacheKey, new Intl.NumberFormat(locale, options));
      return numberFormats.get(cacheKey).format(value);
    }

    function percent(value, options = {}) {
      return number(value / 100, { style: "percent", maximumFractionDigits: 1, ...options });
    }

    function date(value, options = {}) {
      const when = value instanceof Date ? value : new Date(value);
      return new Intl.DateTimeFormat(locale, { timeZone, ...options }).format(when);
    }

    function interpolate(text, vars) {
      if (!vars) return text;
      return text.replace(PLACEHOLDER, (match, name) => {
        if (!hasOwn(vars, name)) return match;
        const value = vars[name];
        return typeof value === "number" ? number(value) : String(value);
      });
    }

    function lookup(key, vars) {
      if (vars && typeof vars.count === "number") {
        const exact = `${key}_${pluralRules.select(vars.count)}`;
        if (hasOwn(dict, exact)) return dict[exact];
        if (hasOwn(dict, `${key}_other`)) return dict[`${key}_other`];
      }
      return hasOwn(dict, key) ? dict[key] : undefined;
    }

    function t(key, vars) {
      const text = lookup(key, vars);
      if (text === undefined) {
        warn(`[i18n] missing key (${lang}): ${key}`);
        return key;
      }
      return interpolate(text, vars);
    }

    function has(key) {
      return hasOwn(dict, key) || hasOwn(dict, `${key}_other`);
    }

    function dataUrl(name) {
      return root + name;
    }

    return { lang, locale, timeZone, root, t, has, number, percent, date, dataUrl };
  }

  function fromDocument(doc = global.document) {
    const html = doc.documentElement;
    const node = doc.getElementById("i18n-dict");
    const host = doc.location ? doc.location.hostname : "";
    const local = host === "localhost" || host === "127.0.0.1";
    return createI18n({
      lang: html.lang || "en",
      locale: html.dataset.locale || html.lang || "en",
      timeZone: html.dataset.timeZone || undefined,
      root: html.dataset.root || "./",
      dict: node ? JSON.parse(node.textContent) : {},
      warn: local ? message => console.warn(message) : () => {},
    });
  }

  const api = { createI18n, fromDocument };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.I18N = api;
})(typeof window !== "undefined" ? window : globalThis);
