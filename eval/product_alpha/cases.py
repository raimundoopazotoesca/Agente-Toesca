from __future__ import annotations

from pathlib import Path

import yaml

from eval.product_alpha.models import ProductCase


CASES_DIR = Path(__file__).with_name("cases")
REQUIRED_FIELDS = {"id", "turns", "purpose", "deterministic", "semantic", "prohibited", "tags"}


class CaseValidationError(ValueError):
    pass


def _load_case(path: Path) -> ProductCase:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CaseValidationError(f"{path.name}: expected a YAML mapping")
    missing = REQUIRED_FIELDS - raw.keys()
    if missing:
        raise CaseValidationError(f"{path.name}: missing {', '.join(sorted(missing))}")
    if not isinstance(raw["turns"], list) or not raw["turns"] or not all(isinstance(turn, str) for turn in raw["turns"]):
        raise CaseValidationError(f"{path.name}: turns must be a non-empty list of strings")
    for name in ("deterministic", "semantic", "prohibited"):
        if not isinstance(raw[name], dict):
            raise CaseValidationError(f"{path.name}: {name} must be a mapping")
    if not isinstance(raw["tags"], list) or not all(isinstance(tag, str) for tag in raw["tags"]):
        raise CaseValidationError(f"{path.name}: tags must be a list of strings")
    capabilities = raw.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(isinstance(capability, str) for capability in capabilities):
        raise CaseValidationError(f"{path.name}: capabilities must be a list of strings")
    return ProductCase(
        id=str(raw["id"]), turns=tuple(raw["turns"]), purpose=str(raw["purpose"]),
        deterministic=raw["deterministic"], semantic=raw["semantic"], prohibited=raw["prohibited"],
        capabilities=frozenset(capabilities), tags=tuple(raw["tags"]),
    )


def load_cases(root: Path | None = None) -> list[ProductCase]:
    root = root or CASES_DIR
    cases = [_load_case(path) for path in sorted(root.glob("*.yaml"))]
    seen: set[str] = set()
    for case in cases:
        if not case.id or case.id in seen:
            raise CaseValidationError(f"duplicate or empty case id: {case.id!r}")
        seen.add(case.id)
    return cases
