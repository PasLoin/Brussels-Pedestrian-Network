import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coverage_summary", ROOT / ".github" / "scripts" / "coverage_summary.py")
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


def record(name, hit, found):
    return f"SF:{name}\nLF:{found}\nLH:{hit}\nend_of_record\n"


def write_tree(tmp_path, names):
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export {};\n")


def test_floors_pass_when_every_edit_module_is_exercised(tmp_path):
    write_tree(tmp_path, ["edit/osm.js", "edit/app/upload.js", "map/main.js"])
    lcov = tmp_path / "lcov.info"
    lcov.write_text(record("edit/osm.js", 99, 100) + record("edit/app/upload.js", 90, 100) + record("map/main.js", 0, 10))
    files = summary.parse_lcov(lcov, tmp_path)
    assert summary.floor_failures(files, summary.js_sources(tmp_path)) == []


def test_an_untested_edit_module_or_a_drop_below_the_floor_fails(tmp_path):
    write_tree(tmp_path, ["edit/osm.js", "edit/new.js", "edit/app/upload.js", "edit/app/thin.js"])
    lcov = tmp_path / "lcov.info"
    lcov.write_text(record(str(tmp_path / "edit/osm.js"), 99, 100) + record("edit/app/upload.js", 80, 100) + record("edit/app/thin.js", 50, 100))
    files = summary.parse_lcov(lcov, tmp_path)
    assert "edit/osm.js" in files
    failures = summary.floor_failures(files, summary.js_sources(tmp_path))
    assert any("`edit/new.js` : jamais chargé" in f for f in failures)
    assert any(f.startswith("`edit/app/` :") for f in failures)
    assert any(f.startswith("`edit/app/thin.js` :") for f in failures)
