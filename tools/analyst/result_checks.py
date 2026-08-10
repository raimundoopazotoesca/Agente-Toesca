"""Deterministic sanity checks over query results, using invariants
declared in semantic/metrics/*.yaml. Intentionally supports only simple
numeric-bound expressions in this phase — no general expression evaluator."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.analyst.semantic_loader import SemanticCatalog, load_semantic_catalog

_RANGE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*<=\s*value\s*<=\s*(-?\d+(?:\.\d+)?)\s*$")
_GE_RE = re.compile(r"^\s*value\s*>=\s*(-?\d+(?:\.\d+)?)\s*$")
_LE_RE = re.compile(r"^\s*value\s*<=\s*(-?\d+(?:\.\d+)?)\s*$")


@dataclass
class CheckResult:
    passed: bool
    violated: list[str] = field(default_factory=list)


def _invariant_holds(invariant: str, value: float) -> bool:
    m = _RANGE_RE.match(invariant)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        return low <= value <= high
    m = _GE_RE.match(invariant)
    if m:
        return value >= float(m.group(1))
    m = _LE_RE.match(invariant)
    if m:
        return value <= float(m.group(1))
    raise ValueError(f"Invariante no soportado en esta fase: {invariant!r}")


def check_result(metric_name: str, value: float, catalog: SemanticCatalog | None = None) -> CheckResult:
    catalog = catalog or load_semantic_catalog()
    metric = catalog.metrics[metric_name]  # KeyError si no existe, intencional
    invariants = metric.get("invariants", [])
    violated = [inv for inv in invariants if not _invariant_holds(inv, value)]
    return CheckResult(passed=not violated, violated=violated)
