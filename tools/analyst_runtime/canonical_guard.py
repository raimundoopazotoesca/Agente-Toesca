"""Deterministic binding of structured canonical claims to tool evidence.

DEPRECATED (A3.2f): this module (Stage 5.3) is not production-wired. The
single active claim validator is tools.analyst_runtime.coverage_guard
.validate_and_render, which re-implements this module's single-fact binding
rules byte-identically as one case of its broader envelope (canonical_metric
/ governed_dataset / derived_metric / table / supporting_evidence claims --
see coverage_guard.py's own module docstring). No production code imports
this module; it is retained solely as coverage_guard.py's single-fact parity
reference, exercised by test_coverage_guard.py's parity tests (e.g.
test_canonical_only_envelope_renders_identically_to_stage_5_3). Do not add
new callers here -- extend coverage_guard.py instead.
"""
from dataclasses import dataclass
from typing import Any

from tools.analyst_runtime.transport import ToolEvidence
from tools.analytics.formatting import render_fact


@dataclass(frozen=True)
class CanonicalValidation:
    valid: bool
    content: str
    trace: dict[str, Any]


def validate_and_render(envelope: dict[str, Any], evidence: list[ToolEvidence]) -> CanonicalValidation:
    canonical = [item for item in evidence if item.evidence_class == "canonical_metric"]
    by_id = {item.evidence_id: item for item in canonical}
    if len(by_id) != len(canonical):
        return _conflict(evidence, "duplicate_evidence_id")
    claims = envelope.get("canonical_metric_claims")
    fragments = envelope.get("fragments")
    if not isinstance(claims, list) or not isinstance(fragments, list):
        return _conflict(evidence, "invalid_envelope")
    bound: dict[str, dict[str, Any]] = {}
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound:
            return _conflict(evidence, "invalid_claim")
        item = by_id.get(claim.get("evidence_id"))
        fact = item.facts[0] if item and len(item.facts) == 1 else None
        if not isinstance(fact, dict) or any(claim.get(key) != fact.get(key) for key in ("metric_key", "value", "unit", "entity_id", "period", "space_type", "space_types", "measurement_unit")):
            return _conflict(evidence, "binding_mismatch")
        bound[claim["claim_id"]] = fact
    rendered: list[str] = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            return _conflict(evidence, "invalid_fragment")
        kind = fragment.get("type")
        if kind in {"text", "raw_text"} and isinstance(fragment.get("text"), str):
            rendered.append(fragment["text"])
        elif kind == "canonical_metric_ref" and fragment.get("claim_id") in bound:
            # Binding already succeeded on the raw semantic value; only the
            # rendered string applies the catalog's display_unit.
            rendered.append(render_fact(bound[fragment["claim_id"]]))
        else:
            return _conflict(evidence, "invalid_fragment")
    return CanonicalValidation(True, "".join(rendered), {"canonical_validation_applied": True,
        "canonical_validation_scope": "scalar", "canonical_claim_count": len(bound),
        "canonical_conflict": False, "conflicting_evidence_ids": [], "conflicting_metric_keys": [],
        "deterministic_fallback_used": False})


_NO_EVIDENCE_FALLBACK = (
    "No puedo confirmar esta respuesta con datos gobernados: la consulta no produjo evidencia "
    "validable para responder con certeza. Intenta reformular la pregunta o pedir el dato de forma más específica."
)


def _conflict(evidence: list[ToolEvidence], reason: str) -> CanonicalValidation:
    facts = [fact for item in evidence if item.evidence_class == "canonical_metric" for fact in item.facts]
    content = "\n".join(f"{fact['metric_key']}: {render_fact(fact)}" for fact in facts) or _NO_EVIDENCE_FALLBACK
    return CanonicalValidation(False, content, {"canonical_validation_applied": True,
        "canonical_validation_scope": "scalar", "canonical_claim_count": 0, "canonical_conflict": True,
        "conflicting_evidence_ids": [item.evidence_id for item in evidence if item.evidence_class == "canonical_metric"],
        "conflicting_metric_keys": [str(fact.get("metric_key")) for fact in facts],
        "deterministic_fallback_used": True, "reason": reason})
