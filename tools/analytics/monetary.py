"""Central, deterministic monetary presentation policy for Analyst claims.

Facts remain native.  A conversion is display-only and is allowed solely when
the fact carries an explicit governed reference value and temporal basis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


PREFERRED_MONETARY_UNIT = "UF"
_MONETARY_UNITS = frozenset({"UF", "CLP", "USD"})


def _unit(value: Any) -> str:
    return "CLP" if isinstance(value, str) and value.casefold() == "clp" else str(value)


@dataclass(frozen=True)
class MonetaryConversionSpec:
    from_unit: str
    to_unit: str
    temporal_basis: str
    reference_value: float
    source: str
    reference_date: str


@dataclass(frozen=True)
class MonetaryPresentation:
    value: float
    unit: str
    lineage: dict[str, Any]


def requested_monetary_unit(text: str | None) -> str | None:
    """Return a generic explicit user override; absence means global UF default."""
    if not isinstance(text, str):
        return None
    normalized = text.casefold()
    if re.search(r"\b(en\s+)?(?:pesos?|clp)\b", normalized):
        return "CLP"
    if re.search(r"\b(?:en\s+)?uf\b", normalized):
        return "UF"
    return None


def conversion_spec(raw: Any) -> MonetaryConversionSpec | None:
    if isinstance(raw, MonetaryConversionSpec):
        return raw
    if not isinstance(raw, dict):
        return None
    required = {"from_unit", "to_unit", "temporal_basis", "reference_value", "source", "reference_date"}
    if required - raw.keys():
        return None
    try:
        spec = MonetaryConversionSpec(
            str(raw["from_unit"]), str(raw["to_unit"]), str(raw["temporal_basis"]),
            float(raw["reference_value"]), str(raw["source"]), str(raw["reference_date"]),
        )
    except (TypeError, ValueError):
        return None
    if spec.from_unit not in _MONETARY_UNITS or spec.to_unit not in _MONETARY_UNITS:
        return None
    if spec.temporal_basis not in {"point_in_time", "monthly_flow"} or spec.reference_value <= 0:
        return None
    return spec


def convert_monetary_value(value: float, spec: MonetaryConversionSpec) -> MonetaryPresentation:
    """Convert through a declared reference, retaining all conversion lineage."""
    if spec.from_unit == "CLP" and spec.to_unit == "UF":
        converted = float(value) / spec.reference_value
    elif spec.from_unit == "UF" and spec.to_unit == "CLP":
        converted = float(value) * spec.reference_value
    else:
        raise ValueError("unsupported monetary conversion pair")
    return MonetaryPresentation(converted, spec.to_unit, {
        "conversion": "governed",
        "from_unit": spec.from_unit,
        "to_unit": spec.to_unit,
        "temporal_basis": spec.temporal_basis,
        "reference_value": spec.reference_value,
        "source": spec.source,
        "reference_date": spec.reference_date,
    })


def present_monetary_fact(fact: dict[str, Any], requested_unit: str | None = None) -> MonetaryPresentation | None:
    """Apply the global default or a user override without changing the fact.

    Native UF is already the default.  Other units are converted only when an
    explicit conversion contract on the fact targets the desired unit.
    """
    unit = _unit(fact.get("unit"))
    value = fact.get("value")
    if unit not in _MONETARY_UNITS or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    target = requested_unit or PREFERRED_MONETARY_UNIT
    if target not in _MONETARY_UNITS or target == unit:
        return MonetaryPresentation(float(value), str(unit), {"conversion": "native"})
    spec = conversion_spec(fact.get("presentation_conversion"))
    if spec is None or spec.from_unit != unit or spec.to_unit != target:
        return MonetaryPresentation(float(value), str(unit), {"conversion": "unavailable"})
    return convert_monetary_value(float(value), spec)
