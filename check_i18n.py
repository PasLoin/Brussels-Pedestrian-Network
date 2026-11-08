import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import build_site
from build_site import I18N_DIR, PLACEHOLDER, ROOT, TEMPLATES_DIR, base_key

DOTTED_KEY = r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+"
KEY_CALL = re.compile(r"""\b(?:t|tx)\(\s*(["'`])(""" + DOTTED_KEY + r""")\1""")
KEY_PROPERTY = re.compile(r"""\b[a-z]\w*Key\s*:\s*(["'`])(""" + DOTTED_KEY + r""")\1""")
UNSUPPORTED = (
    (re.compile(r"\$t\("), "nested $t() calls are not supported"),
    (re.compile(r"\{\{\s*-"), "unescaped {{- }} interpolation is not supported"),
    (re.compile(r"\{\{\s*\w+\s*,"), "formatted {{value, format}} interpolation is not supported"),
    (re.compile(r"</?[A-Za-z][^>]*>|&[A-Za-z]+;|&#\d+;"), "HTML markup is not allowed: values are plain text, escaped where they are inserted"),
)
FRAGMENT_ID = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")
FRAGMENT_CODE = re.compile(r"<code\b")
MISSING_PREVIEW = 5


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)


def families(flat):
    grouped = {}
    for key, value in flat.items():
        grouped.setdefault(base_key(key), {})[key] = value
    return grouped


def is_plural(base, forms):
    return any(key != base for key in forms)


def family_variables(base, forms):
    found = set()
    for value in forms.values():
        found |= set(PLACEHOLDER.findall(value))
    return found - {"count"} if is_plural(base, forms) else found


def check_values(name, flat, report):
    for key, value in flat.items():
        if not value.strip():
            report.error(f"{name}: {key} is empty")
        if value.count("{{") != len(PLACEHOLDER.findall(value)):
            report.error(f"{name}: {key} has a malformed {{{{placeholder}}}}")
        for pattern, reason in UNSUPPORTED:
            if pattern.search(value):
                report.error(f"{name}: {key}: {reason}")
    for base, forms in families(flat).items():
        if not is_plural(base, forms):
            continue
        if base in forms:
            report.error(f"{name}: {base} is both a plain key and a plural family")
        if f"{base}_other" not in forms:
            report.error(f"{name}: plural family {base} has no {base}_other form")


def check_translation(name, published, reference, translated, report):
    ref_families = families(reference)
    tr_families = families(translated)
    for base in sorted(set(tr_families) - set(ref_families)):
        report.error(f"{name}: {base} does not exist in the reference dictionary")
    missing = sorted(set(ref_families) - set(tr_families))
    if missing:
        preview = ", ".join(missing[:MISSING_PREVIEW]) + (" …" if len(missing) > MISSING_PREVIEW else "")
        message = f"{name}: {len(missing)} missing key(s): {preview}"
        if published:
            report.error(message)
        else:
            report.warn(f"{message} (not published yet)")
    for base in sorted(set(ref_families) & set(tr_families)):
        expected = family_variables(base, ref_families[base])
        found = family_variables(base, tr_families[base])
        if expected != found:
            details = []
            if expected - found:
                details.append("missing " + ", ".join(sorted(expected - found)))
            if found - expected:
                details.append("unknown " + ", ".join(sorted(found - expected)))
            report.error(f"{name}: {base} variables differ from the reference ({'; '.join(details)})")


def site_sources(templates_dir=TEMPLATES_DIR, root=ROOT):
    scripts = [Path(root) / name for name in build_site.STATIC if name.endswith(".js")]
    return scripts + [Path(root) / "build_site.py"] + sorted(Path(templates_dir).rglob("*.j2"))


def used_keys(sources):
    used = {}
    for path in sources:
        for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            for pattern in (KEY_CALL, KEY_PROPERTY):
                for match in pattern.finditer(line):
                    used.setdefault(match.group(2), []).append(f"{Path(path).name}:{number}")
    return used


def check_usage(reference, sources, report):
    ref_families = families(reference)
    used = used_keys(sources)
    for key in sorted(used):
        if base_key(key) not in ref_families:
            report.error(f"{used[key][0]}: key {key} is not in the reference dictionary")
    used_bases = {base_key(key) for key in used}
    for base in sorted(set(ref_families) - used_bases):
        report.warn(f"reference key {base} is never used")


def fragment_signature(text):
    return sorted(FRAGMENT_ID.findall(text)), len(FRAGMENT_CODE.findall(text))


def check_fragments(config, templates_dir, report):
    reference = config["reference"]
    for folder in sorted(p for p in Path(templates_dir).iterdir() if p.is_dir()):
        sources = {p.stem: p for p in folder.glob("*.html")}
        if not sources:
            continue
        if reference not in sources:
            report.error(f"{folder.name}/: missing reference fragment {reference}.html")
            continue
        expected_ids, expected_codes = fragment_signature(sources[reference].read_text(encoding="utf-8"))
        for lang, conf in config["languages"].items():
            name = f"{folder.name}/{lang}.html"
            if lang not in sources:
                if conf["published"]:
                    report.error(f"{name} is missing")
                else:
                    report.warn(f"{name} is missing (not published yet)")
                continue
            ids, codes = fragment_signature(sources[lang].read_text(encoding="utf-8"))
            if ids != expected_ids:
                report.error(f"{name}: anchors differ from {reference}.html ({', '.join(sorted(set(ids) ^ set(expected_ids))) or 'order or count'})")
            if codes != expected_codes:
                report.error(f"{name}: {codes} <code> element(s), {expected_codes} in {reference}.html")
        for lang in sorted(set(sources) - set(config["languages"])):
            report.error(f"{folder.name}/{lang}.html: language {lang} is not declared")


def run(i18n_dir=I18N_DIR, templates_dir=TEMPLATES_DIR, sources=None):
    report = Report()
    try:
        config = build_site.load_languages(Path(i18n_dir) / "languages.json")
    except (ValueError, KeyError, OSError) as e:
        report.error(str(e))
        return report
    dictionaries = {}
    for lang in config["languages"]:
        try:
            dictionaries[lang] = build_site.load_dictionary(lang, i18n_dir)
        except ValueError as e:
            report.error(str(e))
    for lang, flat in dictionaries.items():
        check_values(f"{lang}.json", flat, report)
    reference_lang = config["reference"]
    if reference_lang not in dictionaries:
        return report
    reference = dictionaries[reference_lang]
    for lang, flat in dictionaries.items():
        if lang != reference_lang:
            check_translation(f"{lang}.json", config["languages"][lang]["published"], reference, flat, report)
    check_usage(reference, site_sources(templates_dir) if sources is None else sources, report)
    check_fragments(config, templates_dir, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check translation dictionaries, used keys and translated fragments.")
    parser.add_argument("--quiet", action="store_true", help="hide warnings")
    args = parser.parse_args(argv)
    report = run()
    if not args.quiet:
        for message in report.warnings:
            print(f"[WARN] {message}")
    for message in report.errors:
        print(f"[ERROR] {message}", file=sys.stderr)
    if report.errors:
        print(f"[FAIL] {len(report.errors)} error(s)", file=sys.stderr)
        return 1
    print(f"[OK] i18n checked, {len(report.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
