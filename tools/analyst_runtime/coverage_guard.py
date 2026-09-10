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

from tools.analyst_runtime.derived_claims import DerivedClaim, DerivedClaimError, compute_derived_claim, render_derived_claim
from tools.analyst_runtime.transport import ToolEvidence
from tools.analytics.catalog import load_metric_catalog
from tools.analytics.formatting import render_fact, render_named_fact
from tools.analytics.humanize import entity_display_name, entity_kind_label, format_period_short, humanize_text

# A decimal-separated or percent-suffixed numeric literal in free prose is
# always a computed/derived quantity (an integer like a year or a raw
# unformatted DB key is not) -- see derived_claims.py. Any such literal MUST
# come from a derived_metric_ref instead: this is the fail-closed guard that
# closes the bypass where a model wrote an unvalidated arithmetic result
# (e.g. a percent change) directly into a text/raw_text fragment.
_UNBOUND_QUANTITY_RE = re.compile(r"\d[\d.,]*[.,]\d+\s*%?|\d[\d.,]*\d\s*%")

# Both guards below only fire in a "multi-component" context: this turn bound
# 2+ distinct entities sharing the same metric_key+period (see
# ``metric_entities`` in validate_and_render). That keeps them narrow to the
# exact failure shape they close, instead of policing prose in general.
#
# A vague placeholder standing in for a real, already-resolved entity
# identity (e.g. "uno de los activos"/"el otro") when the real display name
# was available -- see humanize.py's entity_display_name, which never
# returns a placeholder like this for a known key.
_VAGUE_REFERENT_RE = re.compile(
    r"\b(uno de los activos|el otro activo\w*|otro activo\b|"
    r"el (primer|segundo|tercer) activo|el (primero|segundo|tercero)\b)",
    re.IGNORECASE,
)
# A qualitative greater/less/equal assertion the model decided itself instead
# of routing through a derived_metric_ref(operation="comparison") -- see
# derived_claims.py. This is the guard that closes the "7,84% ... 22,91% ...
# el primer activo exhibe la mayor tasa" inversion: the digits may be
# correctly bound, but the CONCLUSION about which is bigger was free text.
_COMPARISON_SUPERLATIVE_RE = re.compile(
    r"\b(mayor|menor|m[aá]s alt[oa]|m[aá]s baj[oa]|superior|inferior|lidera|encabeza|concentra m[aá]s)\b",
    re.IGNORECASE,
)

_PARTIAL_PREFIX = "Ojo: estos datos alcanzan a {observed} de {eligible} elementos aplicables; el resto no está disponible. "
_UNKNOWN_PREFIX = "No es posible confirmar que estos datos representen el conjunto completo. "
_PROVENANCE_FALLBACK = (
    "No puedo confirmar que este listado de activos este completo ni respaldado "
    "por datos gobernados; te puedo dar el detalle de un activo especifico si lo indicas."
)
# The generic fail-closed floor: no canonical_metric evidence to render, no
# governed_dataset evidence to fall back on either (the common shape for a
# turn that only ran run_sql -- run_sql never emits ToolEvidence, so a
# rejected envelope over it has nothing to summarize). Without this, `_fail`
# returned "" and the reader saw a blank answer with no explanation -- a
# silent failure that looked like a broken pipeline rather than a governed
# refusal. This is the last-resort text; every branch above it is preferred
# when it has real facts to show.
_NO_EVIDENCE_FALLBACK = (
    "No puedo confirmar esta respuesta con datos gobernados: la consulta no produjo evidencia "
    "validable para responder con certeza. Intenta reformular la pregunta o pedir el dato de forma más específica."
)


@dataclass(frozen=True)
class CoverageValidation:
    valid: bool
    content: str
    trace: dict[str, Any]
    # Deterministically rendered Markdown table blocks (Stage: Structured
    # Analytical Table Outputs). Kept OUT of ``content`` deliberately: content
    # still flows through FinalPresenter's numeric-redaction rephrasing pass,
    # which is safe only for the sentence-level prose it was built for -- a
    # table's literal pipe/row/column structure has no representation in that
    # protocol and would risk being paraphrased away or garbled. Tables are
    # appended by the caller (session.py) AFTER presentation, verbatim.
    tables: tuple[str, ...] = ()


def validate_and_render(envelope: dict[str, Any], canonical_evidence: list[ToolEvidence],
                          governed_evidence: list[ToolEvidence], db_path: Path | None = None,
                          requested_monetary_unit: str | None = None, *,
                          supporting_evidence: list[ToolEvidence] | None = None) -> CoverageValidation:
    # Defensive re-filter, not just trust-the-caller: even if a future caller
    # passes a mixed list, only genuinely canonical_metric/governed_dataset/
    # controlled_sql items can ever bind through their respective claim type.
    # This is the boundary that makes cross-class binding structurally
    # impossible, not merely something session.py's own filtering happens to
    # prevent today.
    canonical_evidence = [item for item in canonical_evidence if item.evidence_class == "canonical_metric"]
    governed_evidence = [item for item in governed_evidence if item.evidence_class == "governed_dataset"]
    supporting_evidence = [item for item in (supporting_evidence or ()) if item.evidence_class == "controlled_sql"]

    canonical_by_id = {item.evidence_id: item for item in canonical_evidence}
    if len(canonical_by_id) != len(canonical_evidence):
        return _fail(canonical_evidence, governed_evidence, "duplicate_canonical_evidence_id", db_path)
    governed_by_id = {item.evidence_id: item for item in governed_evidence}
    if len(governed_by_id) != len(governed_evidence):
        return _fail(canonical_evidence, governed_evidence, "duplicate_governed_evidence_id", db_path)
    supporting_by_id = {item.evidence_id: item for item in supporting_evidence}
    if len(supporting_by_id) != len(supporting_evidence):
        return _fail(canonical_evidence, governed_evidence, "duplicate_supporting_evidence_id", db_path)

    fragments = envelope.get("fragments")
    canonical_claims = envelope.get("canonical_metric_claims")
    governed_claims = envelope.get("governed_dataset_claims", [])
    derived_claims = envelope.get("derived_metric_claims", [])
    table_claims = envelope.get("table_claims", [])
    supporting_claims = envelope.get("supporting_evidence_claims", [])
    if not isinstance(fragments, list) or not isinstance(canonical_claims, list) or not isinstance(governed_claims, list) \
            or not isinstance(derived_claims, list) or not isinstance(table_claims, list) \
            or not isinstance(supporting_claims, list):
        return _fail(canonical_evidence, governed_evidence, "invalid_envelope", db_path)

    bound_canonical: dict[str, dict[str, Any]] = {}
    backed_entity_ids: set[str] = set()
    # governed_dataset evidence a canonical claim selected a single fact from;
    # its coverage still has to be surfaced (see _coverage_prefix below).
    selected_from_governed: dict[str, ToolEvidence] = {}
    for claim in canonical_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound_canonical:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim", db_path)
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
                return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
            matches = [candidate for candidate in item.facts
                       if candidate.get("entity_id") == claim.get("entity_id")
                       and candidate.get("period") == claim.get("period")
                       and candidate.get("space_type") == claim.get("space_type")]
            if len(matches) > 1:
                return _fail(canonical_evidence, governed_evidence, "ambiguous_fact_binding", db_path)
            fact = matches[0] if matches else None
        if not isinstance(fact, dict) or any(claim.get(key) != fact.get(key) for key in ("metric_key", "value", "unit", "entity_id", "period", "space_type", "space_types", "measurement_unit")):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
        bound_canonical[claim["claim_id"]] = fact
        if item.evidence_class == "governed_dataset":
            selected_from_governed[item.evidence_id] = item
            backed_entity_ids.add(str(fact.get("entity_id")))

    bound_governed: dict[str, dict[str, Any]] = {}
    governed_coverage: list[dict[str, Any]] = []
    for claim in governed_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound_governed:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim", db_path)
        item = governed_by_id.get(claim.get("evidence_id"))
        if item is None or item.evidence_class != "governed_dataset":
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
        evidence_universe_kind = (item.coverage or {}).get("universe_kind")
        if evidence_universe_kind is not None and claim.get("universe_kind") != evidence_universe_kind:
            return _fail(canonical_evidence, governed_evidence, "universe_mismatch", db_path)
        claim_entity_ids = claim.get("entity_ids")
        if not isinstance(claim_entity_ids, list):
            return _fail(canonical_evidence, governed_evidence, "invalid_claim", db_path)
        if not claim_entity_ids:
            # A confirmed-empty governed dataset result (the query executed
            # successfully and its own coverage reports zero matching rows,
            # e.g. "what units are vacant" for an asset with none) is itself
            # a real, evidence-backed fact worth citing -- there is nothing
            # to fail closed against here. Any OTHER empty entity_ids claim
            # (the evidence's own coverage does not confirm zero rows) is
            # still rejected: the model may not assert "nothing found"
            # against evidence that never established that.
            if (item.coverage or {}).get("status") != "none":
                return _fail(canonical_evidence, governed_evidence, "invalid_claim", db_path)
            coverage = item.coverage or {"status": "none", "eligible_count": None, "observed_count": 0}
            bound_governed[claim["claim_id"]] = {"facts": [], "scope": item.scope, "coverage": coverage}
            governed_coverage.append({**coverage, "scope": item.scope, "universe_kind": coverage.get("universe_kind")})
            selected_from_governed.pop(item.evidence_id, None)
            continue
        # Select facts by (entity, period), never by entity alone: evidence
        # may hold several periods for the same entity (a `period_range`
        # series). Indexing by entity alone would silently collapse those and
        # could bind a claim to the wrong period. Missing period => the
        # entity_ids subset check below fails => fail-closed.
        period_matches = [fact for fact in item.facts if fact.get("period") == claim.get("period")]
        claim_metric_key = claim.get("metric_key")
        if claim_metric_key is not None:
            candidates = [fact for fact in period_matches if fact.get("metric_key") == claim_metric_key]
            fact_by_entity = {fact.get("entity_id"): fact for fact in candidates}
            if len(fact_by_entity) != len(candidates):
                return _fail(canonical_evidence, governed_evidence, "ambiguous_fact_binding", db_path)
        else:
            # The schema documents null metric_key as valid for "a pure
            # entity enumeration" (synthesis_schema.py), and the model also
            # legitimately emits it for a metric-bearing ranking (e.g. "top 5
            # tenants by GLA") where the metric is implicit in the cited
            # rows -- as well as for a multi-measure breakdown (e.g.
            # "vencimientos por año", several measures per group), where a
            # governed_dataset query action fans out ONE fact per (entity,
            # measure) at the SAME period (see AnalyticsDatasetQueryAction).
            # Indexing that fan-out by entity_id alone looks like duplicate/
            # ambiguous rows even though every entity is unambiguous.
            distinct_metrics = {fact.get("metric_key") for fact in period_matches}
            if len(distinct_metrics) == 1:
                # Unambiguous: infer it, mirroring evidence_inventory.py's
                # ``_facts_metric`` single-metric inference.
                claim_metric_key = next(iter(distinct_metrics))
                fact_by_entity = {fact.get("entity_id"): fact for fact in period_matches}
                if len(fact_by_entity) != len(period_matches):
                    return _fail(canonical_evidence, governed_evidence, "ambiguous_fact_binding", db_path)
            else:
                # Genuinely multi-metric: the claim does not name one, so
                # render identity only -- never guess which of several
                # equally valid measures to surface for a pure enumeration.
                fact_by_entity = {
                    entity_id: {"entity_id": entity_id, "metric_key": None, "value": None, "period": claim.get("period")}
                    for entity_id in {fact.get("entity_id") for fact in period_matches}
                }
        if not set(claim_entity_ids) <= set(fact_by_entity):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
        facts = [fact_by_entity[eid] for eid in claim_entity_ids]
        if claim_metric_key is not None and any(fact.get("metric_key") != claim_metric_key for fact in facts):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
        coverage = item.coverage or {"status": "unknown", "eligible_count": None, "observed_count": len(item.facts)}
        bound_governed[claim["claim_id"]] = {"facts": facts, "scope": item.scope, "coverage": coverage}
        governed_coverage.append({**coverage, "scope": item.scope, "universe_kind": coverage.get("universe_kind")})
        selected_from_governed.pop(item.evidence_id, None)
        backed_entity_ids.update(claim_entity_ids)

    # Supporting (noncanonical) claims: A3.2c. Exclusively bind to
    # controlled_sql evidence -- supporting_by_id was built only from items
    # already filtered to that class, so an evidence_id that happens to exist
    # in canonical_by_id/governed_by_id (but not supporting_by_id) still fails
    # closed here rather than resolving against the wrong lookup. A claim_id
    # colliding with a canonical/governed claim_id is rejected too: the three
    # claim-id namespaces must stay disjoint so a later reference can never
    # be ambiguous about which claim type it names.
    bound_supporting: dict[str, ToolEvidence] = {}
    for claim in supporting_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in bound_supporting \
                or claim["claim_id"] in bound_canonical or claim["claim_id"] in bound_governed:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim", db_path)
        item = supporting_by_id.get(claim.get("evidence_id"))
        if item is None:
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
        bound_supporting[claim["claim_id"]] = item

    # Derived (arithmetic) claims: each operand MUST reference a claim_id
    # already bound above (canonical, never a raw evidence_id and never a
    # governed claim, so the operand set is exactly the single-fact values a
    # reader could otherwise see rendered). The arithmetic runs on raw
    # ``value`` floats inside compute_derived_claim -- this function never
    # touches a rendered/humanized display string.
    bound_derived: dict[str, Any] = {}
    for claim in derived_claims:
        # claim_id namespace must stay disjoint from ALL other claim types
        # (canonical, governed, supporting), not just canonical/supporting --
        # see A3.2d: a derived claim_id colliding with a governed one used to
        # pass through unrejected here (each fragment type still resolved
        # against its own dict, so no wrong value was ever rendered, but the
        # documented "three claim-id namespaces must stay disjoint" invariant
        # was not actually enforced for this pair). Closed for consistency
        # with the existing canonical/supporting checks on this same line.
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) \
                or claim["claim_id"] in bound_derived or claim["claim_id"] in bound_canonical \
                or claim["claim_id"] in bound_supporting or claim["claim_id"] in bound_governed:
            return _fail(canonical_evidence, governed_evidence, "invalid_claim", db_path)
        operation = claim.get("operation")
        lhs_claim_id, rhs_claim_id = claim.get("lhs_claim_id"), claim.get("rhs_claim_id")
        # bound_canonical only -- a supporting (controlled_sql) claim_id can
        # never be an operand: it has no ``value`` to compute with, and
        # looking it up here would silently do nothing (KeyError-free
        # ``.get`` returning None), which already falls through to the
        # binding_mismatch fail-closed below rather than a false accept.
        lhs_fact, rhs_fact = bound_canonical.get(lhs_claim_id), bound_canonical.get(rhs_claim_id)
        if lhs_fact is None or rhs_fact is None or not isinstance(operation, str):
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)
        try:
            bound_derived[claim["claim_id"]] = compute_derived_claim(
                claim["claim_id"], operation, lhs_fact, rhs_fact, lhs_claim_id, rhs_claim_id)
        except DerivedClaimError:
            return _fail(canonical_evidence, governed_evidence, "binding_mismatch", db_path)

    # A "multi-component" turn: 2+ distinct entities bound to the same
    # metric_key+period in this envelope (a breakdown/comparison context).
    # Drives both the vague-referent and unbound-comparison guards below.
    metric_entities: dict[tuple[Any, Any], set[str]] = {}
    for fact in bound_canonical.values():
        metric_entities.setdefault((fact.get("metric_key"), fact.get("period")), set()).add(str(fact.get("entity_id")))
    for bound in bound_governed.values():
        for fact in bound["facts"]:
            metric_entities.setdefault((fact.get("metric_key"), fact.get("period")), set()).add(str(fact.get("entity_id")))
    multi_component_context = any(len(ids) >= 2 for ids in metric_entities.values())
    # Any of these operations already grounds "which side is bigger" in a real
    # computed value (comparison directly; difference/percentage_point_difference
    # by sign; ratio by whether it's above/below 1) -- not just the dedicated
    # "comparison" operation.
    has_comparison_claim = any(
        claim.operation in {"comparison", "difference", "percentage_point_difference", "ratio",
                            "discount_premium"}
        for claim in bound_derived.values()
    )

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
    referenced_supporting: set[str] = set()
    for fragment in fragments:
        if not isinstance(fragment, dict):
            return _fail(canonical_evidence, governed_evidence, "invalid_fragment", db_path)
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
                return _fail(canonical_evidence, governed_evidence, "unbound_derived_quantity", db_path)
            if multi_component_context and _VAGUE_REFERENT_RE.search(text):
                return _fail(canonical_evidence, governed_evidence, "vague_entity_reference", db_path)
            if multi_component_context and not has_comparison_claim and _COMPARISON_SUPERLATIVE_RE.search(text):
                return _fail(canonical_evidence, governed_evidence, "unbound_qualitative_comparison", db_path)
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
            _append_fragment(rendered, render_fact(bound_canonical[fragment["claim_id"]], requested_monetary_unit))
        elif kind == "governed_dataset_ref" and fragment.get("claim_id") in bound_governed:
            _append_fragment(rendered, _render_governed(bound_governed[fragment["claim_id"]], db_path, requested_monetary_unit))
        elif kind == "derived_metric_ref" and fragment.get("claim_id") in bound_derived:
            _append_fragment(rendered, render_derived_claim(bound_derived[fragment["claim_id"]]))
        elif kind == "evidence_ref" and fragment.get("claim_id") in bound_supporting:
            # Noncanonical (controlled_sql) reference: marks that this point
            # in the answer relies on supporting, ungoverned evidence. Never
            # renders a value -- there is none to render (facts == ()) -- and
            # never treated as a citeable figure. The claim_id is tracked
            # only for the trace, not for the rendered text.
            referenced_supporting.add(fragment["claim_id"])
        else:
            return _fail(canonical_evidence, governed_evidence, "invalid_fragment", db_path)

    if not provenance_ok:
        return CoverageValidation(False, _PROVENANCE_FALLBACK, _trace(
            canonical_claims=bound_canonical, governed_coverage=governed_coverage,
            result="fail", provenance="fail", reason="entity_provenance_violation"))

    tables, table_fail_reason = _build_tables(table_claims, bound_canonical, bound_derived, db_path, requested_monetary_unit)
    if table_fail_reason is not None:
        return _fail(canonical_evidence, governed_evidence, table_fail_reason, db_path)

    return CoverageValidation(True, prefix + "".join(rendered), _trace(
        canonical_claims=bound_canonical, governed_coverage=governed_coverage,
        result="pass", provenance=("pass" if provenance_checked else "not_applicable"),
        supporting_claim_count=len(bound_supporting),
        supporting_evidence_ids_referenced=sorted({bound_supporting[cid].evidence_id for cid in referenced_supporting})),
        tables=tuple(tables))


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


_CONFIRMED_EMPTY_TEXT = "No se encontraron registros que cumplan los criterios consultados."


def _render_governed(bound: dict[str, Any], db_path: Path | None = None,
                     requested_monetary_unit: str | None = None) -> str:
    if not bound["facts"]:
        return _CONFIRMED_EMPTY_TEXT
    listing = ", ".join(_render_entity_fact(fact, db_path, requested_monetary_unit) for fact in bound["facts"])
    return _coverage_prefix(bound["coverage"], len(bound["facts"])) + listing


def _render_entity_fact(fact: dict[str, Any], db_path: Path | None = None,
                        requested_monetary_unit: str | None = None) -> str:
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
    return f"{display}: {render_fact(fact, requested_monetary_unit)}"


# Operations that render as a comparable numeric/derived value and can sit in
# a table cell. "comparison" renders as a relation sentence ("es mayor que"),
# not a value, so it can never be placed in a cell -- citing one as a table
# cell_claim_id fails the whole table closed rather than being silently
# dropped or coerced into a value it doesn't have.
_TABLE_DERIVED_OPERATIONS = {"difference", "percent_change", "percentage_point_difference", "ratio",
                             "discount_premium"}

_DERIVED_OPERATION_DISPLAY = {
    "difference": "Diferencia", "percent_change": "Variación %",
    "percentage_point_difference": "Cambio (pp)", "ratio": "Razón",
    "discount_premium": "Descuento / premio",
}


def _metric_label(metric_key: Any) -> str:
    try:
        metric = load_metric_catalog().metrics.get(metric_key)
    except Exception:  # noqa: BLE001 -- display must never raise
        metric = None
    return metric.display_name if metric is not None else str(metric_key)


def _ordered_unique(values: Any) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


_DIM_TO_FACT_KEY = {"entity": "entity_id", "period": "period", "metric": "metric_key"}


def _dim_value(fact: dict[str, Any], dim: str) -> Any:
    return fact.get(_DIM_TO_FACT_KEY[dim])


def _dim_label(dim: str, key: Any, db_path: Path | None) -> str:
    if dim == "entity":
        return entity_display_name(key, db_path)
    if dim == "period":
        return format_period_short(str(key))
    return _metric_label(key)


def _row_header_label(row_dim: str, row_keys: list[Any], db_path: Path | None) -> str:
    if row_dim == "period":
        return "Período"
    if row_dim == "metric":
        return "Métrica"
    kinds = {entity_kind_label(key, db_path) for key in row_keys}
    return kinds.pop() if len(kinds) == 1 else "Entidad"


def _build_tables(table_claims: list[Any], bound_canonical: dict[str, dict[str, Any]],
                   bound_derived: dict[str, DerivedClaim], db_path: Path | None,
                   requested_monetary_unit: str | None = None) -> tuple[list[str] | None, str | None]:
    tables: list[str] = []
    seen_ids: set[str] = set()
    for claim in table_claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in seen_ids:
            return None, "invalid_table_claim"
        seen_ids.add(claim["claim_id"])
        rendered = _render_table(claim, bound_canonical, bound_derived, db_path, requested_monetary_unit)
        if rendered is None:
            return None, "invalid_table_claim"
        if rendered not in tables:
            # Two table_claims entries can legitimately cite the same facts
            # under different claim_ids (or the same ones twice); since
            # rendering is a pure function of the underlying facts, identical
            # output means identical content -- never show a reader the same
            # table rendered twice (spec: "No duplication").
            tables.append(rendered)
    return tables, None


def _render_table(claim: dict[str, Any], bound_canonical: dict[str, dict[str, Any]],
                   bound_derived: dict[str, DerivedClaim], db_path: Path | None,
                   requested_monetary_unit: str | None = None) -> str | None:
    cell_ids = claim.get("cell_claim_ids")
    if not isinstance(cell_ids, list) or not cell_ids:
        return None
    canonical_cells: list[tuple[str, dict[str, Any]]] = []
    derived_cells: list[tuple[str, DerivedClaim]] = []
    seen: set[str] = set()
    for cell_id in cell_ids:
        if not isinstance(cell_id, str) or cell_id in seen:
            return None
        seen.add(cell_id)
        if cell_id in bound_canonical:
            canonical_cells.append((cell_id, bound_canonical[cell_id]))
        elif cell_id in bound_derived:
            derived = bound_derived[cell_id]
            if derived.operation not in _TABLE_DERIVED_OPERATIONS:
                return None
            derived_cells.append((cell_id, derived))
        else:
            # Referenced a claim_id this table can't trace to an already-bound
            # canonical or derived claim -- fail closed rather than silently
            # dropping a cell (an unbound number must never reach a reader).
            return None
    if not canonical_cells:
        return None

    entities = {fact.get("entity_id") for _, fact in canonical_cells}
    periods = {fact.get("period") for _, fact in canonical_cells}
    metrics = {fact.get("metric_key") for _, fact in canonical_cells}
    varying = {"entity": len(entities) > 1, "period": len(periods) > 1, "metric": len(metrics) > 1}
    n_varying = sum(varying.values())
    if n_varying == 0 or n_varying == 3:
        # 0: a scalar -- a one-cell table is never useful, force prose instead.
        # 3: a genuine 3D pivot -- out of v1 scope, keep tables 2-dimensional.
        return None
    if n_varying == 1:
        row_dim = next(dim for dim, does_vary in varying.items() if does_vary)
        col_dim: str | None = None
    elif not varying["entity"]:
        row_dim, col_dim = "metric", "period"
    elif not varying["period"]:
        row_dim, col_dim = "entity", "metric"
    else:
        row_dim, col_dim = "entity", "period"

    row_keys = _ordered_unique(_dim_value(fact, row_dim) for _, fact in canonical_cells)
    col_keys = _ordered_unique(_dim_value(fact, col_dim) for _, fact in canonical_cells) if col_dim else [None]

    order_by = claim.get("order_by")
    if order_by in ("value_desc", "value_asc") and row_dim == "entity" and col_dim is None:
        value_by_row = {_dim_value(fact, row_dim): fact.get("value") for _, fact in canonical_cells}
        row_keys = sorted(row_keys, key=lambda key: value_by_row.get(key, 0.0), reverse=(order_by == "value_desc"))

    grid: dict[Any, dict[Any, dict[str, Any]]] = {row_key: {} for row_key in row_keys}
    for _, fact in canonical_cells:
        row_key = _dim_value(fact, row_dim)
        col_key = _dim_value(fact, col_dim) if col_dim else None
        if row_key not in grid or col_key in grid[row_key]:
            return None  # unreachable row, or two claims landing on the same cell -- ambiguous, fail closed
        grid[row_key][col_key] = fact

    derived_by_row: dict[Any, DerivedClaim] = {}
    for _, derived in derived_cells:
        lhs_fact = bound_canonical.get(derived.lineage.get("lhs_claim_id"))
        if lhs_fact is None:
            return None
        row_key = _dim_value(lhs_fact, row_dim)
        if row_key not in grid or row_key in derived_by_row:
            return None  # can't place this operand's row, or a second derived cell competing for the same row
        derived_by_row[row_key] = derived
    derived_operations = {derived.operation for derived in derived_by_row.values()}
    change_header = (_DERIVED_OPERATION_DISPLAY[next(iter(derived_operations))]
                      if len(derived_operations) == 1 else "Cambio")

    if col_dim is None:
        value_header = _metric_label(next(iter(metrics))) if row_dim != "metric" else "Valor"
        col_headers = [value_header]
    else:
        col_headers = [_dim_label(col_dim, key, db_path) for key in col_keys]
    if derived_by_row:
        col_headers = col_headers + [change_header]

    lines = ["| " + _row_header_label(row_dim, row_keys, db_path) + " | " + " | ".join(col_headers) + " |",
             "|" + "---|" * (1 + len(col_headers))]
    for row_key in row_keys:
        cells = [render_fact(grid[row_key][col_key], requested_monetary_unit) if col_key in grid[row_key] else "Sin dato"
                 for col_key in col_keys]
        if derived_by_row:
            derived = derived_by_row.get(row_key)
            cells.append(render_derived_claim(derived) if derived is not None else "Sin dato")
        lines.append("| " + _dim_label(row_dim, row_key, db_path) + " | " + " | ".join(cells) + " |")
    return "\n".join(lines)


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
           provenance: str, reason: str | None = None, supporting_claim_count: int = 0,
           supporting_evidence_ids_referenced: list[str] | None = None) -> dict[str, Any]:
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
        "supporting_claim_count": supporting_claim_count,
        "supporting_evidence_ids_referenced": supporting_evidence_ids_referenced or [],
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


def _fail(canonical_evidence: list[ToolEvidence], governed_evidence: list[ToolEvidence], reason: str,
          db_path: Path | None = None) -> CoverageValidation:
    facts = [fact for item in canonical_evidence for fact in item.facts]
    content = "\n".join(_render_fact_human(fact) for fact in facts)
    if not content and governed_evidence:
        content = _PROVENANCE_FALLBACK
        # The envelope is untrusted, not the governed rows produced in this
        # turn.  A structured-output failure must still render those rows
        # deterministically; returning a generic sentence here used to leave
        # the fallback without a current-turn answer.
        # A claim-binding failure is different: it may be an attempted
        # citation to an unrelated result, so preserve the normal fail-closed
        # response.  Parse/shape failure has made no such claim and can safely
        # fall back to this turn's complete governed result.
        if reason in {"invalid_envelope", "vague_entity_reference", "unbound_qualitative_comparison"}:
            rendered_sets = []
            for item in governed_evidence:
                if item.facts:
                    coverage = item.coverage or {"status": "unknown"}
                    rows = ", ".join(_render_entity_fact(fact, db_path) for fact in item.facts)
                    rendered_sets.append(_coverage_prefix(coverage, len(item.facts)) + rows)
            if rendered_sets:
                content = "\n".join(rendered_sets)
    if not content:
        content = _NO_EVIDENCE_FALLBACK
    return CoverageValidation(False, content, {
        "canonical_validation_applied": True, "canonical_claim_count": 0,
        "coverage_validation_applied": True, "coverage_scope": None, "coverage_universe_kind": None,
        "coverage_expected_count": None, "coverage_observed_count": None, "coverage_status": None,
        "coverage_gap_count": 0, "coverage_validation_result": "fail", "entity_provenance_validation": "fail",
        "deterministic_fallback_used": True, "reason": reason,
    })
