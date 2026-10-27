#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import yaml

WIKI_BASE = "https://wiki.openstreetmap.org"
API_URL = f"{WIKI_BASE}/w/api.php"
DEFAULT_PAGE = "PWG_Schema"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "pwg" / "schema.yaml"
USER_AGENT = (
    "Brussels-Pedestrian-Network/pwg-schema "
    "(+https://github.com/PasLoin/Brussels-Pedestrian-Network)"
)
FORMAT_VERSION = 1
TIERS = ("bronze", "silver", "gold", "diamond")
GUIDELINES_SECTION = "tagging guidelines"
ELEMENT_TYPES = ("node", "way", "area", "relation")

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
_TAG_RE = re.compile(r"^\s*([^\s=]+)\s*=\s*([^\s]+)\s*$")
_TAG_IN_TEXT_RE = re.compile(r"([A-Za-z_][\w:()|]*)=([\w*:;|.-]+)")
_ALTERNATION_RE = re.compile(r"\(([^()]+)\)")


class PwgStructureError(RuntimeError):
    pass


class _Cell:
    __slots__ = ("header", "colspan", "rowspan", "parts", "codes", "alts")

    def __init__(self, header: bool, colspan: int, rowspan: int) -> None:
        self.header = header
        self.colspan = colspan
        self.rowspan = rowspan
        self.parts: list[str] = []
        self.codes: list[str] = []
        self.alts: list[str] = []

    @property
    def text(self) -> str:
        lines = "".join(self.parts).split("\n")
        cleaned = (" ".join(line.split()) for line in lines)
        return "\n".join(line for line in cleaned if line)


def _span(value: str | None) -> int:
    try:
        return max(1, int(value or 1))
    except ValueError:
        return 1


class _WikiCollector(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self._headings = {"h2": "", "h3": ""}
        self._heading_tag: str | None = None
        self._heading_buf: list[str] = []
        self._skip_tag: str | None = None
        self._skip_depth = 0
        self._stack: list[dict] = []
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._code_depth = 0
        self._code_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        attrs = dict(attrs)
        if "mw-editsection" in (attrs.get("class") or "").split():
            self._skip_tag = tag
            self._skip_depth = 1
            return
        if tag in ("h2", "h3") and self._cell is None:
            self._heading_tag = tag
            self._heading_buf = []
        elif tag == "table":
            self._stack.append({
                "h2": self._headings["h2"],
                "h3": self._headings["h3"],
                "rows": [],
            })
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = _Cell(
                tag == "th", _span(attrs.get("colspan")), _span(attrs.get("rowspan")),
            )
        elif self._cell is not None:
            if tag == "code":
                self._code_depth += 1
                if self._code_depth == 1:
                    self._code_buf = []
            elif tag == "img":
                alt = (attrs.get("alt") or "").strip()
                if alt:
                    self._cell.alts.append(alt)
            elif tag in ("br", "li", "p"):
                self._cell.parts.append("\n")

    def handle_endtag(self, tag):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag == self._heading_tag:
            text = " ".join("".join(self._heading_buf).split())
            self._headings[tag] = text
            if tag == "h2":
                self._headings["h3"] = ""
            self._heading_tag = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())
        elif tag == "tr" and self._row is not None:
            if self._row and self._stack:
                self._stack[-1]["rows"].append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
            self._code_depth = 0
        elif tag == "code" and self._cell is not None and self._code_depth:
            self._code_depth -= 1
            if self._code_depth == 0:
                code = " ".join("".join(self._code_buf).split())
                if code:
                    self._cell.codes.append(code)

    def handle_data(self, data):
        if self._skip_tag:
            return
        if self._heading_tag and self._cell is None:
            self._heading_buf.append(data)
        if self._cell is not None:
            self._cell.parts.append(data)
            if self._code_depth:
                self._code_buf.append(data)


def _grid(rows: list[list[_Cell]]) -> list[list[_Cell | None]]:
    grid: list[list[_Cell | None]] = []
    carry: dict[int, tuple[int, _Cell]] = {}
    for row in rows:
        line: list[_Cell | None] = []
        cells = iter(row)
        col = 0
        while True:
            if col in carry:
                remaining, cell = carry[col]
                line.append(cell)
                if remaining <= 1:
                    del carry[col]
                else:
                    carry[col] = (remaining - 1, cell)
                col += 1
                continue
            cell = next(cells, None)
            if cell is None:
                if any(k > col for k in carry):
                    line.append(None)
                    col += 1
                    continue
                break
            for _ in range(cell.colspan):
                line.append(cell)
                if cell.rowspan > 1:
                    carry[col] = (cell.rowspan - 1, cell)
                col += 1
        grid.append(line)
    return grid


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _expand_key(key: str) -> list[str]:
    match = _ALTERNATION_RE.search(key)
    if not match:
        return [key]
    head, tail = key[:match.start()], key[match.end():]
    out: list[str] = []
    for option in match.group(1).split("|"):
        out.extend(_expand_key(f"{head}{option.strip()}{tail}"))
    return out


def _parse_tags(cell: _Cell | None) -> list[tuple[str, str]]:
    if cell is None:
        return []
    tags = [m.groups() for m in map(_TAG_RE.match, cell.codes) if m]
    if not tags:
        tags = _TAG_IN_TEXT_RE.findall(cell.text)
    return [(k, v) for k, v in tags]


def _parse_elements(cell: _Cell | None) -> list[str]:
    if cell is None:
        return []
    found: list[str] = []
    for token in [*cell.alts, *cell.text.lower().split()]:
        token = token.strip().lower()
        if token in ELEMENT_TYPES and token not in found:
            found.append(token)
    return found


def _header_columns(header: list[_Cell | None]) -> tuple[int | None, int | None, dict[str, int]]:
    tag_col = element_col = None
    tier_cols: dict[str, int] = {}
    for idx, cell in enumerate(header):
        if cell is None:
            continue
        label = cell.text.lower()
        if tag_col is None and label in ("tag", "tags", "key", "keys"):
            tag_col = idx
        elif element_col is None and label in ("element", "elements", "type"):
            element_col = idx
        else:
            for tier in TIERS:
                if tier in label.split() and tier not in tier_cols:
                    tier_cols[tier] = idx
    return tag_col, element_col, tier_cols


def _parse_table(table: dict, warnings: list[str]) -> list[dict]:
    grid = _grid(table["rows"])
    header_idx = next(
        (i for i, row in enumerate(grid) if row and all(c is not None and c.header for c in row)),
        None,
    )
    if header_idx is None:
        return []
    tag_col, element_col, tier_cols = _header_columns(grid[header_idx])
    if tag_col is None or not tier_cols:
        return []

    width = len(grid[header_idx])
    rows: list[dict] = []
    for line in grid[header_idx + 1:]:
        def at(idx: int | None) -> _Cell | None:
            return line[idx] if idx is not None and idx < len(line) else None

        tags = _parse_tags(at(tag_col))
        if not tags:
            continue
        if len(line) != width:
            label = " + ".join(f"{k}={v}" for k, v in tags)
            warnings.append(
                f"{table['h3']}: la ligne {label} couvre {len(line)} colonnes sur {width}, "
                "le tier déduit peut être décalé"
            )
        levels: dict[str, dict] = {}
        previous: _Cell | None = None
        for tier in TIERS:
            if tier not in tier_cols:
                continue
            cell = at(tier_cols[tier])
            if cell is previous:
                continue
            previous = cell
            if cell is None or not cell.text:
                continue
            values = []
            for code in cell.codes:
                if "=" not in code and code not in values:
                    values.append(code)
            levels[tier] = {"description": cell.text, "values": values}
        if not levels:
            continue
        rows.append({
            "tags": tags,
            "elements": _parse_elements(at(element_col)),
            "tier": next(t for t in TIERS if t in levels),
            "levels": levels,
        })
    return rows


def _build_feature(title: str, rows: list[dict]) -> dict:
    slug = _slug(title)
    selector_rows = [r for r in rows if all(v != "*" for _, v in r["tags"])]
    if not selector_rows:
        selector_rows = rows[:1]
    selector_ids = {id(r) for r in selector_rows}
    criterion_rows = [r for r in rows if id(r) not in selector_ids]

    selectors = []
    for row in selector_rows:
        selectors.append({
            "tags": {k: v for k, v in row["tags"]},
            "elements": row["elements"],
            "tier": row["tier"],
            "description": row["levels"][row["tier"]]["description"],
        })

    key_counts: dict[str, int] = {}
    for row in criterion_rows:
        key = row["tags"][0][0]
        key_counts[key] = key_counts.get(key, 0) + 1

    criteria = []
    for row in criterion_rows:
        raw_key, raw_value = row["tags"][0]
        crit_id = f"{slug}.{raw_key}"
        if key_counts[raw_key] > 1:
            crit_id += "@" + "+".join(row["elements"] or ["any"])
        keys: list[str] = []
        for k, _ in row["tags"]:
            for expanded in _expand_key(k):
                if expanded not in keys:
                    keys.append(expanded)
        criteria.append({
            "id": crit_id,
            "tag": " + ".join(f"{k}={v}" for k, v in row["tags"]),
            "keys": keys,
            "value": raw_value,
            "elements": row["elements"],
            "tier": row["tier"],
            "levels": row["levels"],
        })

    ids = [c["id"] for c in criteria]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise PwgStructureError(f"Identifiants de critères dupliqués dans {title!r}: {dupes}")

    return {"title": title, "selectors": selectors, "criteria": criteria}


def _detect_version(tables: list[dict], title: str) -> str | None:
    tail = title.rsplit("/", 1)[-1]
    if _VERSION_RE.match(tail):
        return tail
    for table in tables:
        if not table["rows"]:
            continue
        first = " ".join(c.text.lower() for c in table["rows"][0])
        if "schema" not in first or "release" not in first:
            continue
        for row in table["rows"][1:]:
            for cell in row:
                if _VERSION_RE.match(cell.text):
                    return cell.text
    return None


def parse_schema_html(html: str, *, title: str = "", revision: int | None = None) -> dict:
    collector = _WikiCollector()
    collector.feed(html)
    collector.close()
    if collector._stack:
        open_table = collector._stack[-1]
        where = open_table["h3"] or open_table["h2"] or "début de page"
        raise PwgStructureError(
            f"HTML incomplet : {len(collector._stack)} tableau(x) non fermé(s), "
            f"dernier ouvert dans la section {where!r}. "
            "Le fichier est probablement tronqué."
        )

    features: dict[str, dict] = {}
    warnings: list[str] = []
    for table in collector.tables:
        if table["h2"].lower() != GUIDELINES_SECTION or not table["h3"]:
            continue
        rows = _parse_table(table, warnings)
        if not rows:
            continue
        slug = _slug(table["h3"])
        if slug in features:
            raise PwgStructureError(f"Section dupliquée: {table['h3']!r}")
        features[slug] = _build_feature(table["h3"], rows)

    if not features:
        raise PwgStructureError(
            f"Aucun tableau exploitable sous la section {GUIDELINES_SECTION!r}: "
            "la structure de la page wiki a probablement changé."
        )

    source = {"wiki": WIKI_BASE, "page": title or None, "revision": revision}
    if revision is not None:
        source["url"] = f"{WIKI_BASE}/w/index.php?oldid={revision}"
    version = _detect_version(collector.tables, title)
    if title.startswith("Draft:"):
        source["pwg_version"] = None
        source["draft"] = True
        source["latest_release"] = version
    else:
        source["pwg_version"] = version

    return {
        "format_version": FORMAT_VERSION,
        "source": source,
        "tiers": list(TIERS),
        "warnings": warnings,
        "features": features,
    }


def fetch_page(page: str, timeout: float = 60.0) -> tuple[str, str, int]:
    params = {
        "action": "parse",
        "page": page,
        "prop": "text|revid",
        "redirects": "1",
        "disableeditsection": "1",
        "disabletoc": "1",
        "format": "json",
        "formatversion": "2",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if "error" in payload:
        raise PwgStructureError(f"Erreur API wiki: {payload['error']}")
    parsed = payload["parse"]
    return parsed["text"], parsed["title"], int(parsed["revid"])


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


def dump_yaml(document: dict) -> str:
    return yaml.dump(
        document, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000,
    )


def _summary(document: dict) -> str:
    lines = []
    for slug, feature in document["features"].items():
        by_tier: dict[str, int] = {}
        for crit in feature["criteria"]:
            by_tier[crit["tier"]] = by_tier.get(crit["tier"], 0) + 1
        detail = ", ".join(f"{t}={by_tier[t]}" for t in TIERS if t in by_tier)
        lines.append(f"  {slug}: {len(feature['selectors'])} sélecteur(s), "
                     f"{len(feature['criteria'])} critère(s) [{detail}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extrait le schéma PWG du wiki OSM vers un fichier YAML.",
    )
    parser.add_argument("--page", default=DEFAULT_PAGE,
                        help="Page wiki (ex. PWG_Schema, PWG_Schema_Draft, "
                             ".../Schema/1.0.1)")
    parser.add_argument("--html", type=Path,
                        help="Parser un fichier HTML local au lieu d'appeler l'API")
    parser.add_argument("--revision", type=int,
                        help="Numéro de révision à indiquer avec --html")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="Ne rien écrire ; code de sortie 1 si le fichier diffère")
    args = parser.parse_args(argv)

    if args.html:
        html = args.html.read_text(encoding="utf-8")
        title, revision = args.page, args.revision
    else:
        html, title, revision = fetch_page(args.page)

    document = parse_schema_html(html, title=title, revision=revision)
    text = dump_yaml(document)
    src = document["source"]
    label = "brouillon" if src.get("draft") else (src["pwg_version"] or "?")
    print(f"PWG {label} — {src['page']} (rev {src['revision']})")
    print(_summary(document))
    for warning in document["warnings"]:
        print(f"  ⚠ {warning}")

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != text:
            print(f"{args.output} n'est pas à jour.")
            return 1
        print(f"{args.output} est à jour.")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"Écrit: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
