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

from tools.analyst_runtime.derived_claims import DerivedClaimError, compute_derived_claim, render_derived_claim
from tools.analyst_runtime.transport import ToolEvidence
from tools.analytics.formatting import render_fact, render_named_fact
from tools.analytics.humanize import entity_display_name, humanize_text

# A decimal-separated or percent-suffixed numeric literal in free prose is
# always a computed/derived quantity (an integer like a year or a raw
# unformatted DB key is not) -- see derived_claims.py. Any such literal MUST
# come from a derived_metric_ref instead: this is the fail-closed guard that
# closes the bypass where a model wrote an unvalidated arithmetic result
# (e.g. a percent change) directly into a text/raw_text fragment.
_UNBOUND_QUANTITY_RE = re.compile(r"\d[\d.,]*[.,]\d+\s*%?|\d[\d.,]*\d\s*%")

_PARTIAL_PREFIX = "Ojo: estos datos alcanzan a {observed} de {eligible} elementos aplicables; el resto no está disponible. "
_UNKNOWN_PREFIX = "No es posible confirmar que estos datos representen el conjunto completo. "
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
    derived_claims = envelope.get("derived_metric_claims", [])
    if not isinstance(fragments, list) or not isinstance(canonical_claims, list) or not isinstance(governed_claims, list) \
            or not isinstance(derived_claims, list):
        return _fail(canonical_evidence, governed_evidence, "invalid_envelope")

    bound_canonical: dict[str, dict[str, Any]] = {}
    backed_entity_ids: set[str] = set()
    # governed_dataset evidence a canonical claim selected a single fact from;
    # its coverage still has to be surfaced (see _coverage_prefix below).
    selected_from_governed: dict[str, ToolEvidence] = {}
    for claim in canonical_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound_canonical:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim")
        evidence_id = claim.get("evidence_id")
        item = canonical_by_id.get(evidence_id)
        if item is not None and item.evidence_class == "canonical_metric":
            fact = item.facts[0] if len(item.facts) == 1 else None
        else:
            # A claim may also name ONE fact inside a governed_dataset -- the
            # period-selection path for a time series, and the per-entity path
            # for a breakdown. Selection is by exact (entity_id, period) and
            # must be unambiguous; the same 5-field equality check applies, so
            # this carries no less authority than a single-fact evidence item.
            item = governed_by_id.get(evidence_id)
            if item is None or item.evidence_class != "governed_dataset":
                return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
            matches = [candidate for candidate in item.facts
                       if candidate.get("entity_id") == claim.get("entity_id")
                       and candidate.get("period") == claim.get("period")]
            if len(matches) > 1:
                return _fail(canonical_evidence, governed_evidence, "ambiguous_fact_binding")
            fact = matches[0] if matches else None
        if not isinstance(fact, dict) or any(claim.get(key) != fact.get(key) for key in ("metric_key", "value", "unit", "entity_id", "period")):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
        bound_canonical[claim["claim_id"]] = fact
        if item.evidence_class == "governed_dataset":
            selected_from_governed[item.evidence_id] = item
            backed_entity_ids.add(str(fact.get("entity_id")))

    bound_governed: dict[str, dict[str, Any]] = {}
    governed_coverage: list[dict[str, Any]] = []
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
        selected_from_governed.pop(item.evidence_id, None)
        backed_entity_ids.update(claim_entity_ids)

    # Derived (arithmetic) claims: each operand MUST reference a claim_id
    # already bound above (canonical, never a raw evidence_id and never a
    # governed claim, so the operand set is exactly the single-fact values a
    # reader could otherwise see rendered). The arithmetic runs on raw
    # ``value`` floats inside compute_derived_claim -- this function never
    # touches a rendered/humanized display string.
    bound_derived: dict[str, Any] = {}
    for claim in derived_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) \
                or claim["claim_id"] in bound_derived or claim["claim_id"] in bound_canonical:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim")
        operation = claim.get("operation")
        lhs_claim_id, rhs_claim_id = claim.get("lhs_claim_id"), claim.get("rhs_claim_id")
        lhs_fact, rhs_fact = bound_canonical.get(lhs_claim_id), bound_canonical.get(rhs_claim_id)
        if lhs_fact is None or rhs_fact is None or not isinstance(operation, str):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")
        try:
            bound_derived[claim["claim_id"]] = compute_derived_claim(
                claim["claim_id"], operation, lhs_fact, rhs_fact, lhs_claim_id, rhs_claim_id)
        except DerivedClaimError:
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch")

    # Coverage of a governed dataset a claim cherry-picked facts from must
    # still reach the reader: otherwise a partial ranking could be presented
    # as if it were the whole universe.
    prefix = ""
    for item in selected_from_governed.values():
        coverage = item.coverage or {"status": "unknown", "eligible_count": None, "observed_count": len(item.facts)}
        governed_coverage.append({**coverage, "scope": item.scope, "universe_kind": coverage.get("universe_kind")})
        prefix += _coverage_prefix(coverage, len(item.facts))

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
            if _UNBOUND_QUANTITY_RE.search(text):
                # A decimal/percent literal in free prose is always a computed
                # quantity (a difference, a percent change, ...); it must come
                # from a derived_metric_ref instead. Plain integers (years,
                # counts) are unaffected. Fail-closed rather than plausible:
                # this is the guard that stops "8,26 UF" from ever reaching a
                # reader unbound.
                return _fail(canonical_evidence, governed_evidence, "unbound_derived_quantity")
            if catalog:
                provenance_checked = True
                if not _entities_backed(text, catalog, backed_entity_ids):
                    provenance_ok = False
            # Presentation-only cleanup: raw entity keys / YYYY-MM notation /
            # unrounded float literals a model fragment may still carry get
            # relabelled deterministically. Never changes which facts were
            # validated above -- provenance is checked against the raw text.
            _append_fragment(rendered, humanize_text(text, db_path))
        elif kind == "canonical_metric_ref" and fragment.get("claim_id") in bound_canonical:
            _append_fragment(rendered, render_fact(bound_canonical[fragment["claim_id"]]))
        elif kind == "governed_dataset_ref" and fragment.get("claim_id") in bound_governed:
            _append_fragment(rendered, _render_governed(bound_governed[fragment["claim_id"]], db_path))
        elif kind == "derived_metric_ref" and fragment.get("claim_id") in bound_derived:
            _append_fragment(rendered, render_derived_claim(bound_derived[fragment["claim_id"]]))
        else:
            return _fail(canonical_evidence, governed_evidence, "invalid_fragment")

    if not provenance_ok:
        return CoverageValidation(False, _PROVENANCE_FALLBACK, _trace(
            canonical_claims=bound_canonical, governed_coverage=governed_coverage,
            result="fail", provenance="fail", reason="entity_provenance_violation"))

    return CoverageValidation(True, prefix + "".join(rendered), _trace(
        canonical_claims=bound_canonical, governed_coverage=governed_coverage,
        result="pass", provenance=("pass" if provenance_checked else "not_applicable")))


_GLUE_BOUNDARY_RE = re.compile(r"[\s([{–—-]$")
_GLUE_START_RE = re.compile(r"^[\s.,;:!?)\]}%]")


def _append_fragment(rendered: list[str], chunk: str) -> None:
    """Join rendered fact/text fragments with a generic whitespace glue.

    A model-authored synthesis envelope may emit two structurally rendered
    fragments (two ``governed_dataset_ref``/``canonical_metric_ref`` facts,
    or a fact directly followed by prose) with no separating text fragment
    in between. Concatenating them with bare ``"".join`` then produces
    "Entity: valueEntity: value" -- a formatting defect, not a factual one:
    the values themselves are untouched. This inserts a single space at any
    fragment boundary that isn't already whitespace/opening-bracket on one
    side or punctuation/closing-bracket on the other. It is content-agnostic:
    it never looks at which entity, fund, or metric produced the chunk.
    """
    if not chunk:
        return
    if rendered and rendered[-1] and not _GLUE_BOUNDARY_RE.search(rendered[-1]) and not _GLUE_START_RE.match(chunk):
        rendered.append(" ")
    rendered.append(chunk)


def _coverage_prefix(coverage: dict[str, Any], fact_count: int) -> str:
    status = coverage.get("status", "unknown")
    if status == "partial":
        return _PARTIAL_PREFIX.format(observed=coverage.get("observed_count") or fact_count,
                                      eligible=coverage.get("eligible_count") or 0)
    if status == "unknown":
        return _UNKNOWN_PREFIX
    return ""


def _render_governed(bound: dict[str, Any], db_path: Path | None = None) -> str:
    listing = ", ".join(_render_entity_fact(fact, db_path) for fact in bound["facts"])
    return _coverage_prefix(bound["coverage"], len(bound["facts"])) + listing


def _render_entity_fact(fact: dict[str, Any], db_path: Path | None = None) -> str:
    """A governed fact without a metric (an entity enumeration) has no value
    to render -- only its identity, shown with its human display name where
    the entity catalog has one (falls back to the raw key otherwise)."""
    display = entity_display_name(fact.get("entity_id"), db_path)
    if fact.get("metric_key") is None and fact.get("value") is None:
        name = fact.get("name")
        # Only add a parenthetical when it says something the display name
        # doesn't already say (avoids "Apoquindo 3001 (Apoquindo 3001)" when
        # both ultimately resolve to the same dim_activo.nombre).
        if name and name != fact.get("entity_id") and name != display:
            return f"{display} ({name})"
        return str(display)
    return f"{display}: {render_fact(fact)}"


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
    except sqlite3.OperationalError:
        # A database without dim_activo (a minimal/legacy fixture, not a real
        # deployment DB) simply has no asset catalog to check names against;
        # the caller already treats an empty catalog as "skip this guard",
        # so this degrades the entity-provenance check, never the numeric
        # unbound-quantity guard or claim binding above it.
        return {}
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
