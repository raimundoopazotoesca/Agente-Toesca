"""Single deterministic formatter for rendering governed metric values.

Runs strictly AFTER evidence binding (canonical_guard / coverage_guard) and
BEFORE final presentation. Evidence facts and structured claims always carry
the raw semantic value (e.g. LTV 0.7115159 with unit ``ratio_0_1``); guards
compare claim against fact using that raw value and are unaffected by
anything here. Only the human-readable string applies the catalog's
``display_unit``.

There is no per-metric branching in this module: behaviour is driven entirely
by the metric's ``unit`` / ``display_unit`` catalog fields.
"""
from __future__ import annotations

from typing import Any

from tools.analytics.catalog import load_metric_catalog

# Human suffix per internal unit code. The internal code itself must never
# reach a user.
_UNIT_SUFFIX = {"pct_0_100": "%", "%": "%", "m2": " m²", "clp": " CLP", "ratio_0_1": "", "UF": " UF"}

# Display precision per unit code. Deliberately absent for pct_0_100, which
# is already expressed in its display scale and must render unrounded.
_UNIT_PRECISION = {"UF": 0, "clp": 0, "m2": 1, "pct_0_100": 2, "%": 2}

# Scale transforms keyed by (unit, display_unit). Value -> (factor, suffix).
_DISPLAY_TRANSFORMS = {("ratio_0_1", "percent"): (100.0, "%")}


def render_metric_value(metric_key: Any, value: Any, unit: Any) -> str:
    """Render one metric value for a human reader.

    Unknown metric keys fall back to the legacy raw concatenation so test
    fixtures and any legacy caller keep their exact previous output.
    """
    metric = _metric(metric_key)
    effective_unit = metric.unit if metric is not None else unit
    display_unit = metric.display_unit if metric is not None else None
    transform = _DISPLAY_TRANSFORMS.get((effective_unit, display_unit))
    if transform is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        factor, suffix = transform
        return _number(value * factor, 2) + suffix
    suffix = _UNIT_SUFFIX.get(effective_unit, f" {effective_unit}" if effective_unit else "")
    precision = _UNIT_PRECISION.get(effective_unit)
    if precision is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number(value, precision) + suffix
    # No catalogued precision for this unit: still never surface a raw
    # unrounded Python float to a reader. Default to 2dp Chilean formatting
    # (sensible for an unmodelled unit) rather than str(value).
    if isinstance(value, float) and not isinstance(value, bool):
        return _number(value, 2) + suffix
    return f"{value}{suffix}"


def _number(value: float, precision: int) -> str:
    """Locale-neutral deterministic Chilean display, independent of KPI names."""
    rendered = f"{value:,.{precision}f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")


def render_fact(fact: dict[str, Any]) -> str:
    return render_metric_value(fact.get("metric_key"), fact.get("value"), fact.get("unit"))


def render_named_fact(fact: dict[str, Any]) -> str:
    """``<display name>: <value>`` for fail-closed fallbacks; never leaks the
    internal metric_key or unit code for a catalogued metric."""
    metric = _metric(fact.get("metric_key"))
    label = metric.display_name if metric is not None else fact.get("metric_key")
    return f"{label}: {render_fact(fact)}"


def _metric(metric_key: Any):
    try:
        return load_metric_catalog().metrics.get(metric_key)
    except Exception:  # noqa: BLE001 -- rendering must never raise
        return None
