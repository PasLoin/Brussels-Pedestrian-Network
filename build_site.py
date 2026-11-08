import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
I18N_DIR = ROOT / "i18n"
LANGUAGES_FILE = I18N_DIR / "languages.json"
SITE_URL = "https://pasloin.github.io/Brussels-Pedestrian-Network/"
PAGES = ("index.html", "stats.html", "evolution.html", "about.html")
STATIC = (
    "robots.txt", "favicon.svg", "app.css", "style.json",
    "i18n.js", "app.js", "nav.js", "filters.js", "popups.js", "stats.js", "evolution.js",
)
SITEMAP = "sitemap.xml"
LASTMOD_PLACEHOLDER = "__LASTMOD__"
LANGUAGE_FIELDS = {"path", "locale", "og", "name", "published"}
LANG_PATH = re.compile(r"[a-z]{2}/")
PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")
BRANCH_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*")
LEAF_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_(?:" + "|".join(PLURAL_CATEGORIES) + r"))?")
PLURAL_SUFFIX = re.compile(r"_(?:" + "|".join(PLURAL_CATEGORIES) + r")$")
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


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


def dictionary_json(dictionary):
    text = json.dumps(dictionary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Markup(text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def translator(dictionary):
    def t(key, **variables):
        if key not in dictionary:
            raise KeyError(f"missing translation key {key!r}")

        def fill(match):
            name = match.group(1)
            if name not in variables:
                raise KeyError(f"{key}: missing variable {name!r}")
            return str(variables[name])

        return PLACEHOLDER.sub(fill, dictionary[key])

    return t


def page_root(conf):
    depth = conf["path"].count("/")
    return "../" * depth if depth else "./"


def page_url(conf, page):
    return SITE_URL + conf["path"] + ("" if page == "index.html" else page)


def environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
    )


def render_page(lang, page, config=None, env=None, dictionary=None):
    config = config or load_languages()
    env = env or environment()
    dictionary = page_dictionary(config, lang) if dictionary is None else dictionary
    conf = config["languages"][lang]
    return env.get_template(f"{page}.j2").render(
        lang=lang,
        locale=conf["locale"],
        time_zone=config["timeZone"],
        root=page_root(conf),
        page=page,
        canonical=page_url(conf, page),
        t=translator(dictionary),
        dictionary_json=dictionary_json(dictionary),
    )


def selected_languages(config, requested=None):
    langs = config["languages"]
    if not requested:
        return [lang for lang, conf in langs.items() if conf["published"]]
    unknown = sorted(set(requested) - set(langs))
    if unknown:
        raise ValueError(f"unknown language(s): {', '.join(unknown)}")
    return [lang for lang in langs if lang in requested]


def write_sitemap(out, lastmod):
    text = (ROOT / SITEMAP).read_text(encoding="utf-8")
    (out / SITEMAP).write_text(text.replace(LASTMOD_PLACEHOLDER, lastmod), encoding="utf-8")


def build(out, langs=None, lastmod=None):
    out = Path(out).resolve()
    if out == ROOT or out in ROOT.parents:
        raise ValueError(f"refusing to wipe {out}")
    config = load_languages()
    built = selected_languages(config, langs)
    env = environment()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for lang in built:
        dictionary = page_dictionary(config, lang)
        target = out / config["languages"][lang]["path"]
        target.mkdir(parents=True, exist_ok=True)
        for page in PAGES:
            (target / page).write_text(render_page(lang, page, config, env, dictionary), encoding="utf-8")
    for name in STATIC:
        shutil.copy2(ROOT / name, out / name)
    write_sitemap(out, lastmod or datetime.now(timezone.utc).date().isoformat())
    return built


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render the static site into an output folder.")
    parser.add_argument("--out", default="_site", help="output folder, wiped before the build")
    parser.add_argument("--lang", action="append", help="language to build, repeatable; default: every published language")
    parser.add_argument("--lastmod", help="sitemap lastmod date (YYYY-MM-DD); default: today in UTC")
    args = parser.parse_args(argv)
    try:
        built = build(Path(args.out), args.lang, args.lastmod)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    print(f"[OK] site rendered in {args.out}: {', '.join(built)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
