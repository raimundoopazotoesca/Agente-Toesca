"""Stage 5.4: deterministic binding of governed multi-row claims to
`governed_dataset` evidence, plus the entity-provenance guard that closes the
text/raw_text bypass (a model enumerating canonical entities in free text
without going through a governed_dataset_ref).

Separate module from canonical_guard.py by design: canonical_guard.py (Stage
5.3) keeps validating single-fact `canonical_metric` claims exactly as before
and is not imported or modified here. This module additionally re-implements
that same single-fact binding (byte-identical rules) so ONE envelope --
containing any mix of text / canonical_metric_ref / raw_text /
governed_dataset_ref fragments -- can be validated and rendered in one pass.
Callers who only ever produce canonical_metric_ref envelopes get identical
output to canonical_guard.validate_and_render; this is exercised in
test_coverage_guard.py's parity tests.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.analyst_runtime.transport import ToolEvidence
from tools.analytics.formatting import render_fact, render_named_fact

_PARTIAL_PREFIX = "Cobertura parcial: observados {observed} de {eligible} miembros aplicables. "
_UNKNOWN_PREFIX = "No puede garantizarse completitud de este conjunto con la evidencia disponible. "
_PROVENANCE_FALLBACK = (
    "No puedo confirmar que este listado de activos este completo ni respaldado "
    "por datos gobernados; te puedo dar el detalle de un activo especifico si lo indicas."
)


@dataclass(frozen=True)
class CoverageValidation:
    valid: bool
    content: str
    trace: dict[str, Any]


def validate_and_render(envelope: dict[str, Any], canonical_evidence: list[ToolEvidence],
                          governed_evidence: list[ToolEvidence], db_path: Path | None = None) -> CoverageValidation:
    canonical_by_id = {item.evidence_id: item for item in canonical_evidence}
    if len(canonical_by_id) != len(canonical_evidence):
        return _fail(canonical_evidence, governed_evidence, "duplicate_canonical_evidence_id")
    governed_by_id = {item.evidence_id: item for item in governed_evidence}
    if len(governed_by_id) != len(governed_evidence):
        return _fail(canonical_evidence, governed_evidence, "duplicate_governed_evidence_id")

    fragments = envelope.get("fragments")
    canonical_claims = envelope.get("canonical_metric_claims")
    governed_claims = envelope.get("governed_dataset_claims", [])
    if not isinstance(fragments, list) or not isinstance(canonical_claims, list) or not isinstance(governed_claims, list):
        return _fail(canonical_evidence, governed_evidence, "invalid_envelope")

    bound_canonical: dict[str, dict[str, Any]] = {}
    for claim in canonical_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound_canonical:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim")
        item = canonical_by_id.get(claim.get("evidence_id"))
        fact = item.facts[0] if item and item.evidence_class == "canonical_metric" and len(item.facts) == 1 else None
        if not isinstance(fact, dict) or any(claim.get(key) != fact.get(key) for key in ("metric_key", "value", "unit", "entity_id", "period")):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
        bound_canonical[claim["claim_id"]] = fact

    bound_governed: dict[str, dict[str, Any]] = {}
    governed_coverage: list[dict[str, Any]] = []
    backed_entity_ids: set[str] = set()
    for claim in governed_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound_governed:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim")
        item = governed_by_id.get(claim.get("evidence_id"))
        if item is None or item.evidence_class != "governed_dataset":
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
        claim_entity_ids = claim.get("entity_ids")
        if not isinstance(claim_entity_ids, list) or not claim_entity_ids:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim")
        # Select facts by (entity, period), never by entity alone: evidence
        # may hold several periods for the same entity (a `period_range`
        # series). Indexing by entity alone would silently collapse those and
        # could bind a claim to the wrong period. Missing period => the
        # entity_ids subset check below fails => fail-closed.
        candidates = [fact for fact in item.facts if fact.get("period") == claim.get("period")]
        fact_by_entity = {fact.get("entity_id"): fact for fact in candidates}
        if len(fact_by_entity) != len(candidates):
            return _fail(canonical_evidence, governed_evidence, "ambiguous_fact_binding")
        if not set(claim_entity_ids) <= set(fact_by_entity):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
        facts = [fact_by_entity[eid] for eid in claim_entity_ids]
        if any(fact.get("metric_key") != claim.get("metric_key") for fact in facts):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
        coverage = item.coverage or {"status": "unknown", "eligible_count": None, "observed_count": len(item.facts)}
        bound_governed[claim["claim_id"]] = {"facts": facts, "scope": item.scope, "coverage": coverage}
        governed_coverage.append({**coverage, "scope": item.scope, "universe_kind": coverage.get("universe_kind")})
        backed_entity_ids.update(claim_entity_ids)

    rendered: list[str] = []
    provenance_ok = True
    catalog = _load_asset_catalog(db_path) if db_path is not None else {}
    provenance_checked = False
    for fragment in fragments:
        if not isinstance(fragment, dict):
            return _fail(canonical_evidence, governed_evidence, "invalid_fragment")
        kind = fragment.get("type")
        if kind in {"text", "raw_text"} and isinstance(fragment.get("text"), str):
            text = fragment["text"]
            if catalog:
                provenance_checked = True
                if not _entities_backed(text, catalog, backed_entity_ids):
                    provenance_ok = False
            rendered.append(text)
        elif kind == "canonical_metric_ref" and fragment.get("claim_id") in bound_canonical:
            rendered.append(render_fact(bound_canonical[fragment["claim_id"]]))
        elif kind == "governed_dataset_ref" and fragment.get("claim_id") in bound_governed:
            rendered.append(_render_governed(bound_governed[fragment["claim_id"]]))
        else:
            return _fail(canonical_evidence, governed_evidence, "invalid_fragment")

    if not provenance_ok:
        return CoverageValidation(False, _PROVENANCE_FALLBACK, _trace(
            canonical_claims=bound_canonical, governed_coverage=governed_coverage,
            result="fail", provenance="fail", reason="entity_provenance_violation"))

    return CoverageValidation(True, "".join(rendered), _trace(
        canonical_claims=bound_canonical, governed_coverage=governed_coverage,
        result="pass", provenance=("pass" if provenance_checked else "not_applicable")))


def _render_governed(bound: dict[str, Any]) -> str:
    status = bound["coverage"].get("status", "unknown")
    listing = ", ".join(f"{fact['entity_id']}: {render_fact(fact)}" for fact in bound["facts"])
    if status == "partial":
        eligible = bound["coverage"].get("eligible_count") or 0
        observed = bound["coverage"].get("observed_count") or len(bound["facts"])
        return _PARTIAL_PREFIX.format(observed=observed, eligible=eligible) + listing
    if status == "unknown":
        return _UNKNOWN_PREFIX + listing
    return listing


def _entities_backed(text: str, catalog: dict[str, str], backed_entity_ids: set[str]) -> bool:
    """Exact, literal-boundary matching of canonical asset keys against free
    text -- no fuzzy matching, no NLP, no keyword/intent detection. If a
    fragment names 2+ distinct canonical assets from the same fund, all of
    them must already be backed by a validated governed_dataset claim. A
    single asset mention never triggers this (protects individual-asset
    analysis)."""
    matched_by_fund: dict[str, set[str]] = {}
    for key, fund_key in catalog.items():
        pattern = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)", re.UNICODE)
        if pattern.search(text):
            matched_by_fund.setdefault(fund_key, set()).add(key)
    for keys in matched_by_fund.values():
        if len(keys) >= 2 and not keys <= backed_entity_ids:
            return False
    return True


def _load_asset_catalog(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT activo_key, fondo_key FROM dim_activo").fetchall()
    finally:
        conn.close()
    return {activo_key: fondo_key for activo_key, fondo_key in rows}


def _trace(canonical_claims: dict[str, Any], governed_coverage: list[dict[str, Any]], result: str,
           provenance: str, reason: str | None = None) -> dict[str, Any]:
    worst = _worst_status(gc.get("status") for gc in governed_coverage)
    gap_count = sum(max((gc.get("eligible_count") or 0) - (gc.get("observed_count") or 0), 0) for gc in governed_coverage)
    first = governed_coverage[0] if governed_coverage else None
    trace = {
        "canonical_validation_applied": True,
        "canonical_claim_count": len(canonical_claims),
        "coverage_validation_applied": True,
        "coverage_scope": first.get("scope") if first else None,
        "coverage_universe_kind": first.get("universe_kind") if first else None,
        "coverage_expected_count": first.get("eligible_count") if first else None,
        "coverage_observed_count": first.get("observed_count") if first else None,
        "coverage_status": worst,
        "coverage_gap_count": gap_count,
        "coverage_validation_result": result,
        "entity_provenance_validation": provenance,
        "deterministic_fallback_used": result == "fail",
    }
    if reason:
        trace["reason"] = reason
    return trace


def _worst_status(statuses) -> str | None:
    priority = {"unknown": 2, "partial": 1, "complete": 0}
    ranked = [s for s in statuses if s in priority]
    if not ranked:
        return None
    return max(ranked, key=lambda s: priority[s])


def _render_fact_human(fact: dict[str, Any]) -> str:
    """Render one canonical fact for a fail-closed fallback using the metric
    catalog's human display_name and display scale -- never the internal
    metric_key or unit code. Falls back to the raw key/unit only for a
    metric_key the catalog doesn't recognize (legacy/test fixtures)."""
    return render_named_fact(fact)


def _fail(canonical_evidence: list[ToolEvidence], governed_evidence: list[ToolEvidence], reason: str) -> CoverageValidation:
    facts = [fact for item in canonical_evidence for fact in item.facts]
    content = "\n".join(_render_fact_human(fact) for fact in facts)
    if not content and governed_evidence:
        content = _PROVENANCE_FALLBACK
    return CoverageValidation(False, content, {
        "canonical_validation_applied": True, "canonical_claim_count": 0,
        "coverage_validation_applied": True, "coverage_scope": None, "coverage_universe_kind": None,
        "coverage_expected_count": None, "coverage_observed_count": None, "coverage_status": None,
        "coverage_gap_count": 0, "coverage_validation_result": "fail", "entity_provenance_validation": "fail",
        "deterministic_fallback_used": True, "reason": reason,
    })
