"""Compact, provider-neutral inventory of the evidence one investigation produced.

Purpose: a structured synthesis can only bind a claim to evidence it can NAME.
The model has already seen each tool result once, mid-investigation, buried in
JSON; by synthesis time it reliably forgets which `evidence_id` backs which
entities, and then enumerates them in prose instead -- which the entity
provenance guard correctly rejects. This module re-states, in a few lines, what
identifiers exist and what each one covers.

It is deliberately NOT a new authority and NOT a new data source:

* every line is derived from the real `ToolEvidence` objects the actions
  emitted -- nothing is invented, restated more strongly, or re-derived from
  the database;
* values are omitted entirely. The inventory carries identity (evidence_id,
  class, metric, scope, periods, entities, coverage), never the payload, so it
  cannot become an alternative source of figures;
* `canonical_guard` / `coverage_guard` keep validating claims against the same
  `ToolEvidence` objects, unchanged. A claim naming an evidence_id that does
  not exist, or the wrong entity, period or metric, fails closed exactly as it
  did before this module existed.
"""
from __future__ import annotations

from tools.analyst_runtime.transport import ToolEvidence

# Small and metric-agnostic on purpose: it restates the binding contract the
# schema already describes, without naming any metric, fund or asset.
INVENTORY_HEADER = (
    "Evidencia gobernada disponible para citar (identidades reales, sin valores). "
    "Cita evidence_id textualmente: una cifra gobernada va en canonical_metric_claims "
    "y un conjunto o enumeración de entidades en governed_dataset_claims. El texto "
    "libre no sustituye a una claim."
)

_MAX_LISTED_IDS = 40


def render_evidence_inventory(evidence: list[ToolEvidence]) -> str:
    """One line per evidence item, or "" when the investigation produced none."""
    if not evidence:
        return ""
    lines = [INVENTORY_HEADER]
    lines.extend(f"- {_render_item(item)}" for item in evidence)
    return "\n".join(lines)


def _render_item(item: ToolEvidence) -> str:
    parts = [
        f"evidence_id={item.evidence_id}",
        f"clase={item.evidence_class}",
        f"herramienta={item.producer.tool_name}",
        f"metrica={item.semantic_contract.get('metric_key') or _facts_metric(item) or 'ninguna'}",
        f"alcance={_render_scope(item.scope)}",
        f"periodos={_render_ids(_unique(item.facts, 'period'))}",
        f"entidades={_render_ids(_unique(item.facts, 'entity_id'))}",
    ]
    coverage = item.coverage
    if coverage:
        parts.append(
            f"cobertura={coverage.get('status')} "
            f"({coverage.get('observed_count')}/{coverage.get('eligible_count')}, "
            f"universo={coverage.get('universe_kind')})"
        )
    return " | ".join(parts)


def _facts_metric(item: ToolEvidence) -> str | None:
    metrics = _unique(item.facts, "metric_key")
    return metrics[0] if len(metrics) == 1 else None


def _unique(facts: tuple[dict, ...], key: str) -> list[str]:
    return sorted({str(fact[key]) for fact in facts if fact.get(key) is not None})


def _render_scope(scope: dict) -> str:
    return ", ".join(f"{name}={value}" for name, value in sorted(scope.items())) or "ninguno"


def _render_ids(values: list[str]) -> str:
    if not values:
        return "ninguna"
    if len(values) > _MAX_LISTED_IDS:
        return f"{', '.join(values[:_MAX_LISTED_IDS])}, … (+{len(values) - _MAX_LISTED_IDS})"
    return ", ".join(values)
