const fs = require("node:fs");
const path = require("node:path");
const { createI18n } = require("../../i18n.js");

const I18N_DIR = path.join(__dirname, "..", "..", "i18n");
const LANGUAGES = JSON.parse(fs.readFileSync(path.join(I18N_DIR, "languages.json"), "utf8"));

function flatten(tree, prefix = "") {
  return Object.entries(tree).reduce((flat, [key, value]) => (
    value && typeof value === "object"
      ? { ...flat, ...flatten(value, `${prefix}${key}.`) }
      : { ...flat, [`${prefix}${key}`]: value }
  ), {});
}

function dictionary(lang) {
  const read = code => flatten(JSON.parse(fs.readFileSync(path.join(I18N_DIR, `${code}.json`), "utf8")));
  return lang === LANGUAGES.reference ? read(lang) : { ...read(LANGUAGES.reference), ...read(lang) };
}

function i18nFor(lang, warnings = []) {
  const conf = LANGUAGES.languages[lang];
  return createI18n({
    lang,
    locale: conf.locale,
    timeZone: LANGUAGES.timeZone,
    dict: dictionary(lang),
    warn: message => warnings.push(message),
  });
}

module.exports = { LANGUAGES, dictionary, flatten, i18nFor };
