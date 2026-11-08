import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TAG = re.compile(r"[\w:]+=[\w*:;|.-]+|<code>.*?</code>|\{\{\s*\w+\s*\}\}", re.S)
MARKUP = re.compile(r"<[^>]+>")
JARGON = {
    r"\bmapp\w*": "« cartographier » plutôt que « mapper »",
    r"\bmapping\b": "« cartographie » plutôt que « mapping »",
    r"\b[Ss]napshots?\b": "« relevé » plutôt que « snapshot »",
    r"\b[Kk]erbs?\b": "« bordure » plutôt que « kerb » hors tag",
    r"\bCrossings?\b": "« traversée » plutôt que « crossing » hors tag",
    r"\bFootways?\b": "« chemin piéton » plutôt que « footway » hors tag",
    r"\bCycleways?\b": "« piste cyclable » plutôt que « cycleway » hors tag",
    r"\bQA\b": "« contrôle qualité » plutôt que « QA »",
    r"\bany tag\b": "« tout tag » plutôt que « any tag »",
    r"\bRatio\b": "formulation anglaise",
    r"\bNoeuds?\b": "« nœud » s'écrit avec œ",
    r"\b(?:la|une|cette) way\b": "« way » est masculin",
    r"\bway (?:contiguë|exclue|connectée|séparée)\b": "« way » est masculin",
}


def _flatten(tree, prefix=""):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _flatten(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", value


def _french_texts():
    dictionary = json.loads((ROOT / "i18n" / "fr.json").read_text(encoding="utf-8"))
    yield from _flatten(dictionary)
    for fragment in sorted((ROOT / "templates").glob("*/fr.html")):
        yield fragment.relative_to(ROOT).as_posix(), fragment.read_text(encoding="utf-8")


@pytest.mark.parametrize("pattern, advice", JARGON.items())
def test_french_wording_follows_the_osm_jargon_convention(pattern, advice):
    offenders = []
    for where, text in _french_texts():
        plain = MARKUP.sub(" ", TAG.sub(" ", text))
        for match in re.finditer(pattern, plain):
            offenders.append(f"{where}: {match.group(0)}")
    assert offenders == [], advice


def test_convention_check_ignores_tags_and_code():
    plain = MARKUP.sub(" ", TAG.sub(" ", "Nœud barrier=kerb ou kerb=no et <code>footway=crossing</code>"))
    assert not re.search(r"\b[Kk]erbs?\b", plain)
    assert not re.search(r"[Ss]napshot", MARKUP.sub(" ", TAG.sub(" ", "Relevé {{snapshot}} et {{ snapshots }}")))
