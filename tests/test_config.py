import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

_PARAM_RE = re.compile(r'_(?:float|int|flag)\("(\w+)",\s*"?([^")]+)"?\)')
_ENV_READ_RE = re.compile(r"os\.environ|os\.getenv|\bgetenv\(")


def _config_defaults() -> dict:
    return dict(_PARAM_RE.findall((SCRIPTS / "config.py").read_text()))


def _number(text: str) -> float:
    return float(text.replace("_", "").replace(" ", "").replace("\u202f", ""))


def test_config_declares_parameters():
    assert len(_config_defaults()) >= 29


def test_only_config_reads_environment():
    offenders = [
        p.name for p in sorted(SCRIPTS.glob("*.py"))
        if p.name != "config.py" and _ENV_READ_RE.search(p.read_text())
    ]
    assert offenders == []


def test_build_workflow_sets_no_config_parameter():
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text()
    duplicated = [
        name for name in _config_defaults()
        if re.search(r"^\s+" + name + r"\s*:", workflow, flags=re.M)
    ]
    assert duplicated == []


def test_readme_documents_every_parameter_with_its_value():
    rows = dict(re.findall(r"^\| `(\w+)` \| ([^|]+?) \|", (ROOT / "README.md").read_text(), flags=re.M))
    defaults = _config_defaults()
    assert set(rows) >= set(defaults)
    for name, value in defaults.items():
        assert _number(rows[name]) == _number(value), name
