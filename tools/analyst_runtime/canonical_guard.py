"""Deterministic binding of structured canonical claims to tool evidence."""
from dataclasses import dataclass
from typing import Any

from tools.analyst_runtime.transport import ToolEvidence


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
        if not isinstance(fact, dict) or any(claim.get(key) != fact.get(key) for key in ("metric_key", "value", "unit", "entity_id", "period")):
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
            fact = bound[fragment["claim_id"]]
            rendered.append(f"{fact['value']}{fact['unit']}")
        else:
            return _conflict(evidence, "invalid_fragment")
    return CanonicalValidation(True, "".join(rendered), {"canonical_validation_applied": True,
        "canonical_validation_scope": "scalar", "canonical_claim_count": len(bound),
        "canonical_conflict": False, "conflicting_evidence_ids": [], "conflicting_metric_keys": [],
        "deterministic_fallback_used": False})


def _conflict(evidence: list[ToolEvidence], reason: str) -> CanonicalValidation:
    facts = [fact for item in evidence if item.evidence_class == "canonical_metric" for fact in item.facts]
    content = "\n".join(f"{fact['metric_key']}: {fact['value']}{fact['unit']}" for fact in facts)
    return CanonicalValidation(False, content, {"canonical_validation_applied": True,
        "canonical_validation_scope": "scalar", "canonical_claim_count": 0, "canonical_conflict": True,
        "conflicting_evidence_ids": [item.evidence_id for item in evidence if item.evidence_class == "canonical_metric"],
        "conflicting_metric_keys": [str(fact.get("metric_key")) for fact in facts],
        "deterministic_fallback_used": True, "reason": reason})
