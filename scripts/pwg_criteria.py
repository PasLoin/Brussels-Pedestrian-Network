from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "pwg" / "schema.yaml"
OVERRIDES_PATH = ROOT / "pwg" / "overrides.yaml"

_OVERRIDE_FIELDS = frozenset({"enabled", "tier", "values", "elements", "keys", "reason"})
_FEATURE_FIELDS = frozenset({"enabled", "reason"})
_ADD_FIELDS = frozenset({"id", "feature", "keys", "elements", "tier", "values", "reason", "description"})
_ADD_REQUIRED = frozenset({"id", "feature", "keys", "tier", "reason"})


class PwgConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Criterion:
    id: str
    feature: str
    keys: tuple[str, ...]
    elements: tuple[str, ...]
    tier: str
    values: tuple[str, ...]
    origin: str
    enabled: bool = True
    reason: str = ""
    overridden: tuple[str, ...] = ()
    levels: dict = field(default_factory=dict, compare=False, hash=False)


def _as_str(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _str_tuple(value, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bool, int, float)):
        value = [value]
    if not isinstance(value, list):
        raise PwgConfigError(f"{label}: liste attendue, reçu {type(value).__name__}")
    return tuple(_as_str(v) for v in value)


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise PwgConfigError(f"{path}: un objet YAML est attendu à la racine")
    return data


def _check_fields(entry: dict, allowed: frozenset, label: str) -> None:
    if not isinstance(entry, dict):
        raise PwgConfigError(f"{label}: objet attendu")
    unknown = set(entry) - allowed
    if unknown:
        raise PwgConfigError(f"{label}: champ(s) inconnu(s) {sorted(unknown)}")


def _check_tier(tier, tiers: tuple[str, ...], label: str) -> str:
    tier = _as_str(tier)
    if tier not in tiers:
        raise PwgConfigError(f"{label}: tier {tier!r} invalide (attendu: {list(tiers)})")
    return tier


def _require_reason(entry: dict, label: str) -> str:
    reason = str(entry.get("reason") or "").strip()
    if not reason:
        raise PwgConfigError(f"{label}: 'reason' est obligatoire pour toute dérogation")
    return reason


def _schema_criteria(schema: dict) -> list[Criterion]:
    out: list[Criterion] = []
    for slug, feature in (schema.get("features") or {}).items():
        for raw in feature.get("criteria") or []:
            levels = raw.get("levels") or {}
            values: list[str] = []
            for level in levels.values():
                for v in level.get("values") or []:
                    v = _as_str(v)
                    if v not in values:
                        values.append(v)
            out.append(Criterion(
                id=raw["id"],
                feature=slug,
                keys=_str_tuple(raw.get("keys") or [], raw["id"]),
                elements=_str_tuple(raw.get("elements") or [], raw["id"]),
                tier=raw["tier"],
                values=tuple(values),
                origin="pwg",
                levels=levels,
            ))
    return out


def _apply_override(crit: Criterion, entry: dict, tiers: tuple[str, ...]) -> Criterion:
    label = f"overrides.criteria[{crit.id!r}]"
    _check_fields(entry, _OVERRIDE_FIELDS, label)
    reason = _require_reason(entry, label)
    changes: dict = {"reason": reason}
    touched: list[str] = []
    if "enabled" in entry:
        if not isinstance(entry["enabled"], bool):
            raise PwgConfigError(f"{label}.enabled: booléen attendu")
        changes["enabled"] = entry["enabled"]
        touched.append("enabled")
    if "tier" in entry:
        changes["tier"] = _check_tier(entry["tier"], tiers, f"{label}.tier")
        touched.append("tier")
    for name in ("values", "elements", "keys"):
        if name in entry:
            changes[name] = _str_tuple(entry[name], f"{label}.{name}")
            touched.append(name)
    changes["overridden"] = tuple(touched)
    return replace(crit, **changes)


def _added_criterion(entry: dict, tiers: tuple[str, ...], index: int) -> Criterion:
    label = f"overrides.add[{index}]"
    _check_fields(entry, _ADD_FIELDS, label)
    missing = _ADD_REQUIRED - set(entry)
    if missing:
        raise PwgConfigError(f"{label}: champ(s) manquant(s) {sorted(missing)}")
    description = str(entry.get("description") or "").strip()
    tier = _check_tier(entry["tier"], tiers, f"{label}.tier")
    values = _str_tuple(entry.get("values") or [], f"{label}.values")
    return Criterion(
        id=str(entry["id"]),
        feature=str(entry["feature"]),
        keys=_str_tuple(entry["keys"], f"{label}.keys"),
        elements=_str_tuple(entry.get("elements") or [], f"{label}.elements"),
        tier=tier,
        values=values,
        origin="local",
        reason=_require_reason(entry, label),
        levels={tier: {"description": description, "values": list(values)}},
    )


def merge_criteria(schema: dict, overrides: dict | None = None) -> list[Criterion]:
    overrides = overrides or {}
    _check_fields(overrides, frozenset({"criteria", "features", "add"}), "overrides")
    tiers = tuple(schema.get("tiers") or ())
    if not tiers:
        raise PwgConfigError("schema: liste 'tiers' absente")

    criteria = _schema_criteria(schema)
    by_id = {c.id: i for i, c in enumerate(criteria)}

    for crit_id, entry in (overrides.get("criteria") or {}).items():
        if crit_id not in by_id:
            raise PwgConfigError(
                f"overrides.criteria: {crit_id!r} n'existe pas dans le schéma PWG "
                "(identifiant erroné ou critère retiré du wiki)"
            )
        idx = by_id[crit_id]
        criteria[idx] = _apply_override(criteria[idx], entry, tiers)

    known_features = set((schema.get("features") or {}).keys())
    for slug, entry in (overrides.get("features") or {}).items():
        label = f"overrides.features[{slug!r}]"
        if slug not in known_features:
            raise PwgConfigError(f"{label}: section inconnue du schéma PWG")
        _check_fields(entry, _FEATURE_FIELDS, label)
        reason = _require_reason(entry, label)
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise PwgConfigError(f"{label}.enabled: booléen attendu")
        if enabled:
            continue
        for i, crit in enumerate(criteria):
            if crit.feature == slug and crit.enabled:
                criteria[i] = replace(
                    crit,
                    enabled=False,
                    reason=crit.reason or reason,
                    overridden=crit.overridden + ("feature",),
                )

    for index, entry in enumerate(overrides.get("add") or []):
        crit = _added_criterion(entry, tiers, index)
        if any(c.id == crit.id for c in criteria):
            raise PwgConfigError(f"overrides.add[{index}]: l'identifiant {crit.id!r} existe déjà")
        criteria.append(crit)

    return criteria


def load_criteria(
    schema_path: Path = SCHEMA_PATH,
    overrides_path: Path | None = OVERRIDES_PATH,
    *,
    include_disabled: bool = False,
) -> list[Criterion]:
    if not Path(schema_path).exists():
        raise PwgConfigError(
            f"{schema_path} introuvable : lancer scripts/pwg_schema_fetch.py pour le générer"
        )
    schema = _read_yaml(Path(schema_path))
    overrides = (
        _read_yaml(Path(overrides_path))
        if overrides_path is not None and Path(overrides_path).exists()
        else {}
    )
    criteria = merge_criteria(schema, overrides)
    if include_disabled:
        return criteria
    return [c for c in criteria if c.enabled]


def up_to_tier(criteria: list[Criterion], tier: str, tiers: tuple[str, ...] = ("bronze", "silver", "gold", "diamond")) -> list[Criterion]:
    if tier not in tiers:
        raise PwgConfigError(f"tier {tier!r} invalide (attendu: {list(tiers)})")
    rank = {t: i for i, t in enumerate(tiers)}
    return [c for c in criteria if rank.get(c.tier, len(tiers)) <= rank[tier]]


def main() -> None:
    criteria = load_criteria(include_disabled=True)
    for crit in criteria:
        flags = []
        if not crit.enabled:
            flags.append("désactivé")
        if crit.origin == "local":
            flags.append("ajout local")
        elif crit.overridden:
            flags.append("dérogation: " + ", ".join(crit.overridden))
        suffix = f"  [{'; '.join(flags)}]" if flags else ""
        print(f"{crit.tier:8} {crit.id}{suffix}")
    active = sum(1 for c in criteria if c.enabled)
    print(f"\n{active}/{len(criteria)} critères actifs")


if __name__ == "__main__":
    main()
