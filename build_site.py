import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
LANGUAGES_FILE = ROOT / "i18n" / "languages.json"
SITE_URL = "https://pasloin.github.io/Brussels-Pedestrian-Network/"
PAGES = ("index.html", "stats.html", "evolution.html", "about.html")
STATIC = (
    "robots.txt", "favicon.svg", "app.css", "style.json",
    "app.js", "nav.js", "filters.js", "popups.js",
)
SITEMAP = "sitemap.xml"
LASTMOD_PLACEHOLDER = "__LASTMOD__"
LANGUAGE_FIELDS = {"path", "locale", "og", "name", "published"}
LANG_PATH = re.compile(r"[a-z]{2}/")


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


def render_page(lang, page, config=None, env=None):
    config = config or load_languages()
    env = env or environment()
    conf = config["languages"][lang]
    return env.get_template(f"{page}.j2").render(
        lang=lang,
        locale=conf["locale"],
        time_zone=config["timeZone"],
        root="../" * conf["path"].count("/"),
        page=page,
        canonical=page_url(conf, page),
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
        target = out / config["languages"][lang]["path"]
        target.mkdir(parents=True, exist_ok=True)
        for page in PAGES:
            (target / page).write_text(render_page(lang, page, config, env), encoding="utf-8")
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
