import argparse
import json
import sys
from pathlib import Path

EDIT_FLOORS = {"edit": 95.0, "edit/app": 85.0}
EDIT_FILE_FLOOR = 70.0


def python_total(path: Path) -> float | None:
    if not path.exists():
        return None
    return float(json.loads(path.read_text())["totals"]["percent_covered"])


def parse_lcov(path: Path, root: Path) -> dict[str, dict[str, int]]:
    files: dict[str, dict[str, int]] = {}
    if not path.exists():
        return files
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("SF:"):
            source = Path(line[3:])
            if source.is_absolute():
                try:
                    source = source.resolve().relative_to(root)
                except ValueError:
                    pass
            current = source.as_posix()
            files[current] = {"LF": 0, "LH": 0, "BRF": 0, "BRH": 0, "FNF": 0, "FNH": 0}
        elif current and ":" in line:
            key, _, value = line.partition(":")
            if key in files[current]:
                files[current][key] = int(value)
        elif line == "end_of_record":
            current = None
    return files


def pct(hit: int, found: int) -> str:
    return f"{100.0 * hit / found:.1f} %" if found else "—"


def ratio(hit: int, found: int) -> float:
    return 100.0 * hit / found if found else 100.0


def folder_totals(files: dict[str, dict[str, int]], folder: str) -> tuple[int, int]:
    inside = [f for name, f in files.items() if Path(name).parent.as_posix() == folder]
    return sum(f["LH"] for f in inside), sum(f["LF"] for f in inside)


def js_sources(root: Path) -> list[str]:
    names = [p.relative_to(root).as_posix() for p in root.glob("*.js") if p.name != "eslint.config.mjs"]
    for folder in ("edit", "edit/app", "map"):
        names += [p.relative_to(root).as_posix() for p in (root / folder).glob("*.js")]
    return sorted(names)


def table(files: dict[str, dict[str, int]]) -> list[str]:
    out = ["| Fichier | Lignes | Branches | Fonctions |", "|---|---:|---:|---:|"]
    for name, f in sorted(files.items()):
        out.append(f"| `{name}` | {pct(f['LH'], f['LF'])} | {pct(f['BRH'], f['BRF'])} | {pct(f['FNH'], f['FNF'])} |")
    return out


def floor_failures(files: dict[str, dict[str, int]], sources: list[str]) -> list[str]:
    failures = []
    for folder, floor in EDIT_FLOORS.items():
        hit, found = folder_totals(files, folder)
        if ratio(hit, found) < floor:
            failures.append(f"`{folder}/` : {pct(hit, found)} de lignes couvertes, seuil {floor:.0f} %")
    for name in sources:
        if Path(name).parent.as_posix() not in EDIT_FLOORS:
            continue
        f = files.get(name)
        if f is None:
            failures.append(f"`{name}` : jamais chargé par les tests")
        elif ratio(f["LH"], f["LF"]) < EDIT_FILE_FLOOR:
            failures.append(f"`{name}` : {pct(f['LH'], f['LF'])} de lignes couvertes, seuil {EDIT_FILE_FLOOR:.0f} % par fichier")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-json", type=Path, default=Path("coverage.json"))
    parser.add_argument("--lcov", type=Path, default=Path("coverage-js/lcov.info"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    files = parse_lcov(args.lcov, root)
    sources = js_sources(root)

    if args.check:
        failures = floor_failures(files, sources)
        for failure in failures:
            print(f"::error::Couverture insuffisante : {failure}")
        if not files:
            print("::error::Rapport de couverture JavaScript absent")
        sys.exit(1 if failures or not files else 0)

    py = python_total(args.python_json)
    lf = sum(f["LF"] for f in files.values())
    lh = sum(f["LH"] for f in files.values())
    unmeasured = [name for name in sources if name not in files or files[name]["LF"] == 0 or files[name]["LH"] == 0]

    out = ["## Couverture de code", ""]
    out.append(f"- **Python** (`scripts/`, lignes + branches, informatif) : {f'{py:.1f} %' if py is not None else 'n/a'}")
    out.append(f"- **JavaScript** (tests `node --test` et scénarios navigateur, lignes) : {pct(lh, lf) if lf else 'n/a'}")
    for folder, floor in EDIT_FLOORS.items():
        hit, found = folder_totals(files, folder)
        out.append(f"- `{folder}/` : {pct(hit, found)} (seuil {floor:.0f} %, et {EDIT_FILE_FLOOR:.0f} % par fichier)")
    if unmeasured:
        out.append(f"- JS jamais exécuté par les tests : {', '.join(f'`{n}`' for n in unmeasured)}")
    out.append("")
    if files:
        out += ["### JavaScript", ""] + table(files) + [""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
