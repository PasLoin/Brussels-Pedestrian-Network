import json

import pytest

import check_i18n

LANGUAGES = {
    "reference": "en",
    "timeZone": "Europe/Brussels",
    "languages": {
        "en": {"path": "", "locale": "en-GB", "og": "en_GB", "name": "English", "published": True},
        "fr": {"path": "fr/", "locale": "fr-BE", "og": "fr_BE", "name": "Français", "published": True},
        "nl": {"path": "nl/", "locale": "nl-BE", "og": "nl_BE", "name": "Nederlands", "published": False},
    },
}

EN = {
    "route": {"noRoute": "No route found", "walkTime": "≈ {{minutes}} min walk"},
    "map": {"trips_one": "One simulated trip", "trips_other": "{{count}} simulated trips"},
}
FR = {
    "route": {"noRoute": "Aucun itinéraire", "walkTime": "≈ {{minutes}} min à pied"},
    "map": {"trips_one": "{{count}} trajet simulé", "trips_other": "{{count}} trajets simulés"},
}
SOURCE = """
const label = t("route.noRoute");
const walk = t('route.walkTime', { minutes });
const trips = tx(`map.trips`, { count });
const LAYERS = [{ dataKey: "type", labelKey: "route.noRoute" }];
"""


@pytest.fixture
def project(tmp_path):
    i18n = tmp_path / "i18n"
    templates = tmp_path / "templates"
    i18n.mkdir()
    templates.mkdir()
    source = tmp_path / "app.js"
    source.write_text(SOURCE, encoding="utf-8")

    def write(languages=LANGUAGES, **dictionaries):
        (i18n / "languages.json").write_text(json.dumps(languages), encoding="utf-8")
        for lang, tree in {"en": EN, "fr": FR, "nl": {}, **dictionaries}.items():
            path = i18n / f"{lang}.json"
            if tree is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(json.dumps(tree), encoding="utf-8")

    checker = check_i18n.run

    def run(sources=None):
        return checker(i18n, templates, [source] if sources is None else sources)

    write()
    return tmp_path, write, run


def _one(messages, needle):
    return [m for m in messages if needle in m]


def test_repository_translations_pass():
    report = check_i18n.run()
    assert report.errors == []


def test_complete_translations_pass(project):
    _, _, run = project
    report = run()
    assert report.errors == []
    assert _one(report.warnings, "nl.json: 3 missing key(s)")


def test_missing_key_blocks_a_published_language(project):
    _, write, run = project
    write(fr={"route": {"walkTime": "≈ {{minutes}} min"}, "map": FR["map"]})
    assert _one(run().errors, "fr.json: 1 missing key(s): route.noRoute")


def test_missing_keys_only_warn_for_an_unpublished_language(project):
    _, write, run = project
    write(nl={"route": {"noRoute": "Geen route"}})
    report = run()
    assert not _one(report.errors, "nl.json")
    assert _one(report.warnings, "nl.json: 2 missing key(s): map.trips, route.walkTime (not published yet)")


def test_unknown_key_is_rejected(project):
    _, write, run = project
    write(fr={**FR, "extra": {"key": "x"}})
    assert _one(run().errors, "fr.json: extra.key does not exist in the reference dictionary")


def test_missing_dictionary_is_rejected(project):
    _, write, run = project
    write(nl=None)
    assert _one(run().errors, "missing dictionary nl.json")


def test_invalid_languages_file_is_reported(project):
    _, write, run = project
    write(languages={"reference": "xx", "timeZone": "Europe/Brussels", "languages": {}})
    assert _one(run().errors, "reference language")


def test_variables_must_match_the_reference(project):
    _, write, run = project
    write(fr={**FR, "route": {"noRoute": "Aucun itinéraire {{extra}}", "walkTime": "≈ {{min}} min"}})
    errors = run().errors
    assert _one(errors, "route.noRoute variables differ from the reference (unknown extra)")
    assert _one(errors, "route.walkTime variables differ from the reference (missing minutes; unknown min)")


def test_plural_forms_may_omit_count(project):
    _, write, run = project
    write(fr={**FR, "map": {"trips_one": "Un trajet", "trips_other": "{{count}} trajets"}})
    assert run().errors == []


def test_plural_family_needs_an_other_form(project):
    _, write, run = project
    write(fr={**FR, "map": {"trips_one": "{{count}} trajet"}})
    assert _one(run().errors, "fr.json: plural family map.trips has no map.trips_other form")


def test_plain_key_and_plural_family_cannot_share_a_name(project):
    _, write, run = project
    write(en={**EN, "map": {**EN["map"], "trips": "Trips"}})
    assert _one(run().errors, "en.json: map.trips is both a plain key and a plural family")


@pytest.mark.parametrize("value, reason", [
    ("  ", "is empty"),
    ("{{minutes} min", "malformed"),
    ("$t(route.noRoute)", "nested $t()"),
    ("{{- minutes}} min", "unescaped"),
    ("{{minutes, number}} min", "formatted"),
])
def test_invalid_values_are_rejected(project, value, reason):
    _, write, run = project
    write(fr={**FR, "route": {**FR["route"], "walkTime": value}})
    assert _one(run().errors, reason)


def test_used_keys_must_exist_in_the_reference(project):
    root, _, run = project
    extra = root / "extra.js"
    extra.write_text('el.textContent = t("route.unknown");\nconst L = [{ titleKey: "legend.title" }];\n', encoding="utf-8")
    errors = run([root / "app.js", extra]).errors
    assert _one(errors, "extra.js:1: key route.unknown is not in the reference dictionary")
    assert _one(errors, "extra.js:2: key legend.title is not in the reference dictionary")


def test_data_property_names_are_not_mistaken_for_keys(project):
    _, _, run = project
    assert not _one(run().errors, "key type ")


def test_unused_reference_keys_are_reported(project):
    root, _, run = project
    only_one = root / "one.js"
    only_one.write_text('t("route.noRoute");\n', encoding="utf-8")
    warnings = run([only_one]).warnings
    assert _one(warnings, "reference key map.trips is never used")
    assert _one(warnings, "reference key route.walkTime is never used")


def _fragments(root, **files):
    folder = root / "templates" / "about"
    folder.mkdir(exist_ok=True)
    for lang, text in files.items():
        (folder / f"{lang}.html").write_text(text, encoding="utf-8")


FRAGMENT = '<h2 id="routing">Routing</h2><p><code>highway=*</code></p><h2 id="indicators">Indicators</h2>'


def test_matching_fragments_pass(project):
    root, _, run = project
    _fragments(root, en=FRAGMENT, fr=FRAGMENT.replace("Routing", "Routage"))
    report = run()
    assert report.errors == []
    assert _one(report.warnings, "about/nl.html is missing (not published yet)")


def test_fragment_anchors_must_match_the_reference(project):
    root, _, run = project
    _fragments(root, en=FRAGMENT, fr=FRAGMENT.replace('id="indicators"', 'id="indicateurs"'))
    assert _one(run().errors, "about/fr.html: anchors differ from en.html (indicateurs, indicators)")


def test_fragment_code_elements_must_match_the_reference(project):
    root, _, run = project
    _fragments(root, en=FRAGMENT, fr=FRAGMENT.replace("<code>highway=*</code>", "highway=*"))
    assert _one(run().errors, "about/fr.html: 0 <code> element(s), 1 in en.html")


def test_published_language_needs_every_fragment(project):
    root, _, run = project
    _fragments(root, en=FRAGMENT)
    assert _one(run().errors, "about/fr.html is missing")


def test_fragment_folder_needs_the_reference(project):
    root, _, run = project
    _fragments(root, fr=FRAGMENT)
    assert _one(run().errors, "about/: missing reference fragment en.html")


def test_fragment_of_an_undeclared_language_is_rejected(project):
    root, _, run = project
    _fragments(root, en=FRAGMENT, fr=FRAGMENT, de=FRAGMENT)
    assert _one(run().errors, "about/de.html: language de is not declared")


def test_cli_exit_codes(project, monkeypatch, capsys):
    _, write, run = project
    monkeypatch.setattr(check_i18n, "run", lambda: run())
    assert check_i18n.main([]) == 0
    assert "[OK]" in capsys.readouterr().out
    write(fr={"route": FR["route"]})
    assert check_i18n.main(["--quiet"]) == 1
    captured = capsys.readouterr()
    assert "[FAIL] 1 error(s)" in captured.err
    assert "[WARN]" not in captured.out
