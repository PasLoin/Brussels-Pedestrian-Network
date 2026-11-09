import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
I18N_DIR = ROOT / "i18n"
LANGUAGES_FILE = I18N_DIR / "languages.json"
SITE_URL = "https://pasloin.github.io/Brussels-Pedestrian-Network/"
PAGES = ("index.html", "stats.html", "evolution.html", "about.html")
STATIC = (
    "robots.txt", "favicon.svg", "app.css", "style.json",
    "i18n.js", "lang.js", "html.js", "nav.js", "filters.js", "popups.js", "stats.js", "evolution.js",
)
STATIC_DIRS = ("map",)
STATIC_DIR_IGNORE = ("package.json",)
SITEMAP_ENTRIES = {
    "index.html": ("daily", "1.0"),
    "stats.html": ("daily", "0.8"),
    "evolution.html": ("daily", "0.8"),
    "about.html": ("monthly", "0.7"),
}
NOT_FOUND = "404.html"
CSP = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "https://unpkg.com", "https://cdn.jsdelivr.net"],
    "style-src": ["'self'", "https://unpkg.com", "'unsafe-inline'"],
    "img-src": ["'self'", "https://tiles.openfreemap.org", "https://www.openstreetmap.org", "data:"],
    "connect-src": ["'self'", "https://tiles.openfreemap.org", "https://unpkg.com"],
    "worker-src": ["blob:"],
    "child-src": ["blob:"],
    "font-src": ["https://tiles.openfreemap.org"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "upgrade-insecure-requests": [],
}
CSP_ADDITIONS = {
    "index.html": {
        "img-src": ["https://pasloin.github.io", "blob:"],
        "connect-src": ["https://pasloin.github.io", "https://protomaps.github.io"],
    },
}
CSP_NOT_FOUND = {
    "default-src": ["'none'"],
    "img-src": ["'self'"],
    "style-src": ["'unsafe-inline'"],
    "base-uri": ["'none'"],
    "form-action": ["'none'"],
}
SITEMAP = "sitemap.xml"
LANGUAGE_FIELDS = {"path", "locale", "og", "name", "published"}
LANG_PATH = re.compile(r"[a-z]{2}/")
PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")
BRANCH_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*")
LEAF_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_(?:" + "|".join(PLURAL_CATEGORIES) + r"))?")
PLURAL_SUFFIX = re.compile(r"_(?:" + "|".join(PLURAL_CATEGORIES) + r")$")
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
PSEUDO_LANG = "en-XA"
PSEUDO_CONF = {"path": "pseudo/", "locale": "en-GB", "og": "en_GB", "name": "Pseudo", "published": False}
PSEUDO_OPEN, PSEUDO_CLOSE = "\u27e6", "\u27e7"
PSEUDO_LETTERS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "\u00e5\u0180\u00e7\u00f0\u00e9\u0192\u011d\u0125\u00ee\u0135\u0137\u013c\u0271\u00f1\u00f6\u00fe\u01eb\u0155\u0161\u0163\u00fb\u1e7d\u0175\u1e8b\u00fd\u017e"
    "\u00c5\u0181\u00c7\u00d0\u00c9\u0191\u011c\u0124\u00ce\u0134\u0136\u013b\u1e40\u00d1\u00d6\u00de\u01ea\u0154\u0160\u0162\u00db\u1e7c\u0174\u1e8a\u00dd\u017d",
)


def validate_languages(config):
    langs = config.get("languages") or {}
    errors = []
    if config.get("reference") not in langs:
        errors.append("the reference language must be listed in languages")
    for lang, conf in langs.items():
        missing = LANGUAGE_FIELDS - set(conf)
        if missing:
            errors.append(f"{lang}: missing {', '.join(sorted(missing))}")
            continue
        if conf["path"] and not LANG_PATH.fullmatch(conf["path"]):
            errors.append(f"{lang}: invalid path {conf['path']!r}")
    paths = [conf.get("path") for conf in langs.values()]
    if len(paths) != len(set(paths)):
        errors.append("two languages share the same path")
    roots = [lang for lang, conf in langs.items() if conf.get("path") == "" and conf.get("published")]
    if len(roots) != 1:
        errors.append("exactly one published language must live at the root (empty path)")
    if errors:
        raise ValueError(f"{LANGUAGES_FILE.name}: " + "; ".join(errors))
    return config


def load_languages(path=LANGUAGES_FILE):
    return validate_languages(json.loads(path.read_text(encoding="utf-8")))


def root_language(config):
    return next(lang for lang, conf in config["languages"].items() if conf["path"] == "" and conf["published"])


def flatten(tree, source, prefix=""):
    if not isinstance(tree, dict):
        raise ValueError(f"{source}: {prefix.rstrip('.') or 'root'} must be an object")
    flat = {}
    for key, value in tree.items():
        full = prefix + key
        if isinstance(value, dict):
            if not BRANCH_KEY.fullmatch(key):
                raise ValueError(f"{source}: invalid group key {full!r}")
            flat.update(flatten(value, source, full + "."))
        elif isinstance(value, str):
            if not LEAF_KEY.fullmatch(key):
                raise ValueError(f"{source}: invalid key {full!r}")
            flat[full] = value
        else:
            raise ValueError(f"{source}: {full} must be a string or an object")
    return flat


def load_dictionary(lang, directory=I18N_DIR):
    path = Path(directory) / f"{lang}.json"
    if not path.is_file():
        raise ValueError(f"missing dictionary {path.name}")
    return flatten(json.loads(path.read_text(encoding="utf-8")), path.name)


def base_key(key):
    return PLURAL_SUFFIX.sub("", key)


def with_fallback(reference, translated):
    present = {base_key(key) for key in translated}
    merged = {key: value for key, value in reference.items() if base_key(key) not in present}
    merged.update(translated)
    return dict(sorted(merged.items()))


def page_dictionary(config, lang, directory=I18N_DIR):
    reference = load_dictionary(config["reference"], directory)
    if lang == config["reference"]:
        return dict(sorted(reference.items()))
    return with_fallback(reference, load_dictionary(lang, directory))


def pseudo_text(text):
    parts, position = [], 0
    for match in PLACEHOLDER.finditer(text):
        parts += [text[position:match.start()].translate(PSEUDO_LETTERS), match.group(0)]
        position = match.end()
    parts.append(text[position:].translate(PSEUDO_LETTERS))
    return PSEUDO_OPEN + "".join(parts) + PSEUDO_CLOSE


def pseudo_dictionary(reference):
    return {key: pseudo_text(value) for key, value in reference.items()}


def with_pseudo_language(config):
    return {**config, "languages": {**config["languages"], PSEUDO_LANG: PSEUDO_CONF}}


def dictionary_json(dictionary):
    return embedded_json(dictionary)


def translator(dictionary):
    def t(key, **variables):
        if key not in dictionary:
            raise KeyError(f"missing translation key {key!r}")
        text = dictionary[key]
        parts, position = [], 0
        for match in PLACEHOLDER.finditer(text):
            name = match.group(1)
            if name not in variables:
                raise KeyError(f"{key}: missing variable {name!r}")
            parts += [escape(text[position:match.start()]), escape(variables[name])]
            position = match.end()
        parts.append(escape(text[position:]))
        return Markup("".join(parts))

    return t


def page_root(conf):
    depth = conf["path"].count("/")
    return "../" * depth if depth else "./"


def page_url(conf, page):
    return SITE_URL + conf["path"] + ("" if page == "index.html" else page)


def content_security_policy(page=None, base=CSP, additions=CSP_ADDITIONS):
    directives = {name: list(sources) for name, sources in base.items()}
    for name, sources in additions.get(page, {}).items():
        directives.setdefault(name, [])
        directives[name] += [s for s in sources if s not in directives[name]]
    return "; ".join(" ".join([name, *sources]) for name, sources in directives.items()) + ";"


def published_languages(config):
    return [lang for lang, conf in config["languages"].items() if conf["published"]]


def page_dictionaries(config):
    return {lang: page_dictionary(config, lang) for lang in published_languages(config)}


def alternates(config, lang, page, dictionaries):
    here = config["languages"][lang]
    result = []
    for other in published_languages(config):
        conf = config["languages"][other]
        t = translator(dictionaries[other])
        result.append({
            "lang": other,
            "name": conf["name"],
            "og": conf["og"],
            "href": page_root(here) + conf["path"] + ("" if page == "index.html" else page),
            "url": page_url(conf, page),
            "banner": {"text": str(t("lang.banner.text")), "switch": str(t("lang.banner.switch")), "dismiss": str(t("lang.banner.dismiss"))},
        })
    return result


def embedded_json(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Markup(text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
    )


def render_page(lang, page, config=None, env=None, dictionary=None, dictionaries=None):
    config = config or load_languages()
    env = env or environment()
    dictionary = page_dictionary(config, lang) if dictionary is None else dictionary
    dictionaries = page_dictionaries(config) if dictionaries is None else dictionaries
    conf = config["languages"][lang]
    links = alternates(config, lang, page, dictionaries)
    is_root = conf["path"] == ""
    return env.get_template(f"{page}.j2").render(
        lang=lang,
        reference=config["reference"],
        locale=conf["locale"],
        og=conf["og"],
        time_zone=config["timeZone"],
        root=page_root(conf),
        page=page,
        canonical=page_url(conf, page),
        csp=Markup(content_security_policy(page)),
        alternates=links,
        x_default=page_url(config["languages"][root_language(config)], page),
        t=translator(dictionary),
        dictionary_json=dictionary_json(dictionary),
        languages_json=embedded_json({
            "current": lang,
            "isRoot": is_root,
            "languages": [{key: alt[key] for key in ("lang", "name", "href", "banner")} for alt in links],
        }),
    )


def render_not_found(config=None, env=None, dictionaries=None):
    config = config or load_languages()
    env = env or environment()
    dictionaries = page_dictionaries(config) if dictionaries is None else dictionaries
    reference = root_language(config)
    sections = [
        {"lang": lang, "url": page_url(config["languages"][lang], "index.html"), "t": translator(dictionaries[lang])}
        for lang in published_languages(config)
    ]
    return env.get_template(f"{NOT_FOUND}.j2").render(
        lang=reference,
        csp=Markup(content_security_policy(base=CSP_NOT_FOUND, additions={})),
        site_url=SITE_URL,
        sections=sections,
        t=translator(dictionaries[reference]),
    )


def selected_languages(config, requested=None):
    langs = config["languages"]
    if not requested:
        return [lang for lang, conf in langs.items() if conf["published"]]
    unknown = sorted(set(requested) - set(langs))
    if unknown:
        raise ValueError(f"unknown language(s): {', '.join(unknown)}")
    return [lang for lang in langs if lang in requested]


def sitemap_xml(config, lastmod):
    langs = published_languages(config)
    root = config["languages"][root_language(config)]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for page, (changefreq, priority) in SITEMAP_ENTRIES.items():
        for lang in langs:
            lines += [
                "  <url>",
                f"    <loc>{escape(page_url(config['languages'][lang], page))}</loc>",
                f"    <lastmod>{escape(lastmod)}</lastmod>",
                f"    <changefreq>{changefreq}</changefreq>",
                f"    <priority>{priority}</priority>",
            ]
            for other in langs:
                url = escape(page_url(config["languages"][other], page))
                lines.append(f'    <xhtml:link rel="alternate" hreflang="{other}" href="{url}"/>')
            lines.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{escape(page_url(root, page))}"/>')
            lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def write_sitemap(out, config, lastmod):
    (out / SITEMAP).write_text(sitemap_xml(config, lastmod), encoding="utf-8")


def build(out, langs=None, lastmod=None, pseudo=False):
    out = Path(out).resolve()
    if out == ROOT or out in ROOT.parents:
        raise ValueError(f"refusing to wipe {out}")
    config = load_languages()
    built = selected_languages(config, langs)
    env = environment()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    dictionaries = page_dictionaries(config)
    for lang in built:
        dictionary = page_dictionary(config, lang)
        target = out / config["languages"][lang]["path"]
        target.mkdir(parents=True, exist_ok=True)
        for page in PAGES:
            (target / page).write_text(render_page(lang, page, config, env, dictionary, dictionaries), encoding="utf-8")
    if pseudo:
        pseudo_config = with_pseudo_language(config)
        dictionary = pseudo_dictionary(page_dictionary(config, config["reference"]))
        target = out / PSEUDO_CONF["path"]
        target.mkdir(parents=True, exist_ok=True)
        for page in PAGES:
            (target / page).write_text(render_page(PSEUDO_LANG, page, pseudo_config, env, dictionary, dictionaries), encoding="utf-8")
        built.append(PSEUDO_LANG)
    for name in STATIC:
        shutil.copy2(ROOT / name, out / name)
    for name in STATIC_DIRS:
        shutil.copytree(ROOT / name, out / name, ignore=shutil.ignore_patterns(*STATIC_DIR_IGNORE))
    (out / NOT_FOUND).write_text(render_not_found(config, env, dictionaries), encoding="utf-8")
    write_sitemap(out, config, lastmod or datetime.now(timezone.utc).date().isoformat())
    return built


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render the static site into an output folder.")
    parser.add_argument("--out", default="_site", help="output folder, wiped before the build")
    parser.add_argument("--lang", action="append", help="language to build, repeatable; default: every published language")
    parser.add_argument("--lastmod", help="sitemap lastmod date (YYYY-MM-DD); default: today in UTC")
    parser.add_argument("--pseudo", action="store_true", help=f"also render the {PSEUDO_LANG} pseudo-locale in {PSEUDO_CONF['path']}, never published")
    args = parser.parse_args(argv)
    try:
        built = build(Path(args.out), args.lang, args.lastmod, args.pseudo)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    print(f"[OK] site rendered in {args.out}: {', '.join(built)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
