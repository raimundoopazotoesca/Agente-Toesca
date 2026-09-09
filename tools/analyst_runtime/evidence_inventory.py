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

A3.2c: `controlled_sql` evidence is now also listed, in a second, clearly
separate section, so synthesis can name it in a `supporting_evidence_claims`
entry (via an `evidence_ref` fragment). It never joins the citeable section
above: `controlled_sql` has no `facts` and no claim type it can bind a
governed figure to (see `coverage_guard.validate_and_render`, which rejects
any attempt to cite it as canonical/governed). Its inventory line carries the
same values-omitted identity discipline -- evidence_id, class, tool, and only
schema-shaped metadata (column names, row counts), never a query row.
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

# Only these classes back a claim type (canonical_metric_claims /
# governed_dataset_claims) that canonical_guard/coverage_guard validate
# against.
_CITEABLE_CLAIM_CLASSES = frozenset({"canonical_metric", "governed_dataset", "verified_query"})

# controlled_sql (A3.2b) is real evidence but never a governed claim target --
# it is exclusively referenceable via supporting_evidence_claims/evidence_ref
# (A3.2c). Listed in its own section, never merged with the citeable one, so
# the model can never mistake it for something canonical_guard/coverage_guard
# would accept in canonical_metric_claims or governed_dataset_claims.
_SUPPORTING_EVIDENCE_CLASSES = frozenset({"controlled_sql"})

SUPPORTING_INVENTORY_HEADER = (
    "Evidencia de apoyo no canónica disponible para referenciar (identidades reales, sin valores). "
    "Nunca respalda una cifra gobernada: no puede citarse en canonical_metric_claims, "
    "governed_dataset_claims ni derived_metric_claims. Para referenciarla, agrega una entrada en "
    "supporting_evidence_claims con su evidence_id textual y marca su lugar en fragments con "
    "{\"type\":\"evidence_ref\",\"claim_id\":...}."
)


def render_evidence_inventory(evidence: list[ToolEvidence]) -> str:
    """Compact inventory of the evidence one investigation produced, in up to
    two sections:

    * citeable (canonical_metric / governed_dataset / verified_query) -- can
      back a canonical_metric_claims/governed_dataset_claims entry;
    * supporting (controlled_sql) -- can only back a
      supporting_evidence_claims entry, never a governed one.

    Returns "" only when the investigation produced neither."""
    citeable = [item for item in evidence if item.evidence_class in _CITEABLE_CLAIM_CLASSES]
    supporting = [item for item in evidence if item.evidence_class in _SUPPORTING_EVIDENCE_CLASSES]
    sections = []
    if citeable:
        sections.append("\n".join([INVENTORY_HEADER] + [f"- {_render_item(item)}" for item in citeable]))
    if supporting:
        sections.append("\n".join([SUPPORTING_INVENTORY_HEADER] + [f"- {_render_supporting_item(item)}" for item in supporting]))
    return "\n\n".join(sections)


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


def _render_supporting_item(item: ToolEvidence) -> str:
    """Identity + schema-shaped metadata only -- controlled_sql carries no
    ``facts``, so nothing here is ever a query row or a value."""
    parts = [
        f"evidence_id={item.evidence_id}",
        f"clase={item.evidence_class}",
        f"herramienta={item.producer.tool_name}",
        f"columnas={_render_ids(list(item.result.columns))}",
        f"filas_devueltas={item.result.returned_rows}",
    ]
    if item.result.truncated:
        parts.append("truncado=true")
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
