# Translating Brussels Pedestrian Network

The site is built once per language from the same templates. English is the reference: every other language is checked against it.

| Language | Status | Folder on the site | Dictionary | Methodology |
| --- | --- | --- | --- | --- |
| English (reference) | published | `/` | `i18n/en.json` | `templates/about/en.html` |
| French | published | `/fr/` | `i18n/fr.json` | `templates/about/fr.html` |
| Dutch | draft, awaiting native review | `/nl/` once published | `i18n/nl.json` | `templates/about/nl.html` |

A language with `"published": false` in `i18n/languages.json` is checked and tested in CI but never deployed: it has no pages online and no entry in the language menu, the language banner, the `hreflang` links or the sitemap. Publishing it is a one-line change once the review is done.

## What to translate

- **`i18n/<lang>.json`** holds every short text of the interface: map, legend, popups, statistics, trends, page titles. Copy the structure of `en.json` and translate the values only, never the keys.
- **`templates/about/<lang>.html`** is the methodology page. Translate the prose and keep the HTML as it is: the same `id` anchors and the same number of `<code>` elements as `en.html`.

Text that must stay as it is:

- OSM tags and values: `footway=crossing`, `sidewalk=yes`, `separate`;
- product names: OpenStreetMap, OSM, iD, JOSM, PMTiles, OpenFreeMap, Liberty, ZinnekeTiles;
- variables written `{{name}}`, which the site replaces with a number, a date or a street name.

## Dictionary format

The dictionaries follow the [i18next JSON v4](https://www.i18next.com/misc/json-format) format, which tools such as Weblate read natively.

```json
{
  "route": {
    "walkTime": "≈ {{minutes}} min walk"
  },
  "map": {
    "tripsSimulated_one": "{{count}} simulated trip",
    "tripsSimulated_other": "{{count}} simulated trips"
  }
}
```

- **Variables** keep the same names as in English. Numbers are formatted for your language automatically.
- **Plurals** use the suffixes `_zero`, `_one`, `_two`, `_few`, `_many` and `_other` from the [CLDR plural rules](https://www.unicode.org/cldr/charts/latest/supplemental/language_plural_rules.html). Provide the forms your language needs; `_other` is always required.
- **No HTML** in values: write plain text, the site escapes it where it is inserted.

## Adding a language

1. Add the language to `i18n/languages.json` with `"published": false`, for example `"nl": { "path": "nl/", "locale": "nl-BE", "og": "nl_BE", "name": "Nederlands", "published": false }`.
2. Copy `i18n/en.json` to `i18n/nl.json` and `templates/about/en.html` to `templates/about/nl.html`, then translate.
3. Open a pull request. The checks build the new language, render every page and popup in it, and report what is still missing, without blocking while the language is unpublished.
4. Once a native speaker has reviewed it, set `"published": true`. The language menu, the language banner, the `hreflang` links and the sitemap pick it up automatically.

## Checking your work

```sh
pip install "jinja2>=3.1"
python3 check_i18n.py
python3 build_site.py --lang en --lang nl
python3 -m http.server -d _site
```

- **`check_i18n.py`** reports missing or unknown keys, variables that differ from English, plural families without `_other`, HTML in values and methodology pages whose anchors or `<code>` elements differ from English.
- **`build_site.py --pseudo`** also renders the `en-XA` pseudo-locale in `/pseudo/`, where every translated text looks like `⟦Ļéĝéñð⟧`. Any plain text left on those pages is hardcoded and needs a key.
- On `localhost`, a missing key shows in the browser console as `[i18n] missing key`.

## French conventions

- OSM object types keep their technical names: « nœud » and « way » (masculine: « le way », « contigu »).
- Everyday notions are in French: bordure (kerb), traversée (crossing), piste cyclable (cycleway), chemin piéton (footway).
- « Cartographier » rather than « mapper »; « tag » and « taguer » are fine.

`tests/test_french_wording.py` enforces these rules.

## Dutch draft

The Dutch files are a complete first draft for Belgian Dutch (`nl-BE`). They follow the same logic as French and need a review by a native speaker f before publication. Terms to confirm:

| Concept | Draft | Alternative to consider |
| --- | --- | --- |
| sidewalk | trottoir | voetpad (common in Belgium, but clashes with footway) |
| footway | voetpad | voetgangerspad |
| crossing | oversteekplaats | zebrapad (only for marked crossings) |
| kerb | stoeprand | boordsteen |
| tactile paving | geleidetegels | ribbeltegels, noppentegels |
| way, node | way, knoop | weg, knooppunt |
| to map | karteren | in kaart brengen |

To preview the draft locally, run `python3 build_site.py --lang en --lang nl` and open `/nl/`.
