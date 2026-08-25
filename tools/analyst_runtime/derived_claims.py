"""Stage 5.4b: deterministic arithmetic over already-bound canonical claims.

The model is never trusted to compute or write a derived quantitative value
(a difference, a percent change, a percentage-point difference, a ratio)
itself -- see coverage_guard.py's docstring for why free-text digits are
rejected. Instead the model names an *operation* over two claim_ids it has
already bound to real evidence in the same envelope; this module performs the
arithmetic on the RAW numeric ``value`` fields of those already-verified
facts (never on a rendered/humanized display string) and returns a new,
lineage-carrying claim whose value the caller can bind into the same
claim_ref rendering path as any other claim.

No per-metric or per-fund branching: behaviour is generic across every metric
key, driven only by ``operation`` and the two operand units.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.analytics.formatting import render_derived_value

SUPPORTED_OPERATIONS = frozenset({"difference", "percent_change", "percentage_point_difference", "ratio", "comparison"})

_PERCENT_UNITS = frozenset({"%", "pct_0_100"})


class DerivedClaimError(ValueError):
    """Raised when an operation/operand combination cannot be computed deterministically."""


@dataclass(frozen=True)
class DerivedClaim:
    claim_id: str
    operation: str
    value: float
    unit: str
    lineage: dict[str, Any] = field(default_factory=dict)


def compute_derived_claim(claim_id: str, operation: str, lhs_fact: dict[str, Any], rhs_fact: dict[str, Any],
                           lhs_claim_id: str, rhs_claim_id: str) -> DerivedClaim:
    """Compute one derived claim from two already-bound raw facts.

    ``lhs_fact``/``rhs_fact`` must be the exact dicts coverage_guard already
    bound (raw ``value``, never a display string). Raises
    :class:`DerivedClaimError` -- callers must treat that as fail-closed, the
    same as any other binding_mismatch.
    """
    if operation not in SUPPORTED_OPERATIONS:
        raise DerivedClaimError(f"unsupported operation: {operation}")
    lhs_unit, rhs_unit = lhs_fact.get("unit"), rhs_fact.get("unit")
    if lhs_unit != rhs_unit:
        raise DerivedClaimError("operand unit mismatch")
    try:
        lhs_value, rhs_value = float(lhs_fact["value"]), float(rhs_fact["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DerivedClaimError("non-numeric operand") from exc

    if operation == "difference":
        value, unit = lhs_value - rhs_value, str(lhs_unit)
    elif operation == "percentage_point_difference":
        if lhs_unit not in _PERCENT_UNITS:
            raise DerivedClaimError("percentage_point_difference requires percent-unit operands")
        value, unit = lhs_value - rhs_value, "pp"
    elif operation == "percent_change":
        if lhs_value == 0:
            raise DerivedClaimError("percent_change from a zero baseline is undefined")
        value, unit = (rhs_value - lhs_value) / lhs_value * 100.0, "pct_change"
    elif operation == "ratio":
        if rhs_value == 0:
            raise DerivedClaimError("ratio with a zero denominator is undefined")
        value, unit = lhs_value / rhs_value, "ratio"
    elif operation == "comparison":
        # A qualitative greater/less/equal relation, computed the same way as
        # difference (raw value - raw value), never authored by the model: the
        # sign alone decides which side is "greater". This exists so a
        # narrative comparison ("X tiene mayor vacancia que Y") is always
        # grounded in the real operand values instead of free LLM judgment.
        value, unit = (1.0 if lhs_value > rhs_value else (-1.0 if lhs_value < rhs_value else 0.0)), "comparison"
    else:  # pragma: no cover -- guarded by SUPPORTED_OPERATIONS check above
        raise DerivedClaimError(f"unsupported operation: {operation}")

    return DerivedClaim(
        claim_id=claim_id, operation=operation, value=value, unit=unit,
        lineage={"operation": operation, "lhs_claim_id": lhs_claim_id, "rhs_claim_id": rhs_claim_id,
                 "lhs_value": lhs_value, "rhs_value": rhs_value, "lhs_unit": str(lhs_unit), "rhs_unit": str(rhs_unit)},
    )


def render_derived_claim(claim: DerivedClaim) -> str:
    return render_derived_value(claim.operation, claim.value, claim.unit)
