import argparse
import json
from pathlib import Path


def python_total(path: Path) -> float | None:
    if not path.exists():
        return None
    return float(json.loads(path.read_text())["totals"]["percent_covered"])


def parse_lcov(path: Path) -> dict[str, dict[str, int]]:
    files: dict[str, dict[str, int]] = {}
    if not path.exists():
        return files
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("SF:"):
            current = Path(line[3:]).as_posix()
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-json", type=Path, default=Path("coverage.json"))
    parser.add_argument("--lcov", type=Path, default=Path("lcov.info"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    py = python_total(args.python_json)
    js_files = parse_lcov(args.lcov)
    root = args.root.resolve()
    measured = {Path(f).name for f in js_files}
    unmeasured = sorted(p.name for p in root.glob("*.js") if p.name not in measured)

    lf = sum(f["LF"] for f in js_files.values())
    lh = sum(f["LH"] for f in js_files.values())
    js = 100.0 * lh / lf if lf else None

    out = ["## Couverture de code (informatif)", ""]
    out.append(f"- **Python** (`scripts/`, lignes + branches) : {f'{py:.1f} %' if py is not None else 'n/a'}")
    out.append(f"- **JavaScript** (modules chargés par `node --test`, lignes) : {f'{js:.1f} %' if js is not None else 'n/a'}")
    if unmeasured:
        out.append(f"- JS non mesuré (jamais chargé par les tests node) : {', '.join(f'`{n}`' for n in unmeasured)}")
    out.append("")
    if js_files:
        out += ["### JavaScript", "", "| Fichier | Lignes | Branches | Fonctions |", "|---|---:|---:|---:|"]
        for name, f in sorted(js_files.items()):
            out.append(f"| `{name}` | {pct(f['LH'], f['LF'])} | {pct(f['BRH'], f['BRF'])} | {pct(f['FNH'], f['FNF'])} |")
        out.append("")
    print("\n".join(out))


if __name__ == "__main__":
    main()
