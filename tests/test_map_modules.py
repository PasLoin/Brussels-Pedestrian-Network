import json
import re

import build_site
from front_contract import ROOT, page_text

MAP_DIR = ROOT / "map"
IMPORT = re.compile(r'^\s*(?:import|export)\b[^;]*?\bfrom\s+"([^"]+)"', re.M | re.S)


def _modules():
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(MAP_DIR.glob("*.js"))}


def _imports(src):
    return IMPORT.findall(src)


def test_every_import_is_a_local_module_that_exists():
    modules = _modules()
    for name, src in modules.items():
        for target in _imports(src):
            assert target.startswith("./") and target.endswith(".js"), (name, target)
            assert target[2:] in modules, (name, target)


def test_every_module_is_reachable_from_the_entry_point():
    modules = _modules()
    seen, todo = set(), ["main.js"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo += [target[2:] for target in _imports(modules[name])]
    assert seen == set(modules)


def test_map_page_loads_only_the_entry_point_as_a_module():
    html = page_text("index.html")
    modules = re.findall(r'<script type="module" src="\./([^"]+)"', html)
    assert modules == ["map/main.js"]
    assert html.index('src="./popups.js"') < html.index('src="./map/main.js"')


def test_modules_touch_window_only_to_expose_the_test_api():
    for name, src in _modules().items():
        assignments = re.findall(r"\bwindow\.(\w+)\s*=", src)
        assert assignments == (["BPNMap"] if name == "main.js" else []), name


def test_node_treats_the_map_folder_as_es_modules():
    assert json.loads((MAP_DIR / "package.json").read_text(encoding="utf-8")) == {"type": "module"}


def test_site_publishes_every_module_and_nothing_else_from_the_folder(tmp_path):
    build_site.build(tmp_path, lastmod="2026-11-08")
    published = sorted(p.name for p in (tmp_path / "map").iterdir())
    assert published == sorted(_modules())
