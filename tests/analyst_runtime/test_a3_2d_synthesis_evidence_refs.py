"""A3.2d: closes the test gaps identified by the read-only A3.2d diagnosis.

No new evidence/citation architecture: every test here exercises the EXISTING
A3.2a-A3.2c pathway (coverage_guard.validate_and_render / evidence_inventory /
session._allowed_claims / presentation.validate_structured_output). Where a
test demonstrates a real defect, the defect and its minimal fix are documented
inline next to the test that proves it -- see G_DERIVED_GOVERNED_NAMESPACE
below for the one case that surfaced.
"""
from __future__ import annotations

from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.evidence_inventory import render_evidence_inventory
from tools.analyst_runtime.presentation import AllowedClaim, validate_structured_output
from tools.analyst_runtime.session import _allowed_claims

from tests.analyst_runtime._evidence_factory import mk_evidence

CANONICAL_FACT = {"metric_key": "vacancia_pct_fondo", "value": 5.94, "unit": "%",
                   "entity_id": "TRI", "period": "2026-06", "space_type": None,
                   "space_types": None, "measurement_unit": None}
CANONICAL_FACT_2 = {"metric_key": "vacancia_pct_fondo", "value": 3.10, "unit": "%",
                     "entity_id": "PT", "period": "2026-06", "space_type": None,
                     "space_types": None, "measurement_unit": None}
CANONICAL_EVIDENCE = mk_evidence("e_canon", "canonical_metric", facts=(CANONICAL_FACT,))
CANONICAL_EVIDENCE_2 = mk_evidence("e_canon_2", "canonical_metric", facts=(CANONICAL_FACT_2,))

GOVERNED_FACT = {"entity_id": "Apo4501", "period": "2026-06", "metric_key": None, "value": None}
GOVERNED_EVIDENCE = mk_evidence("e_gov", "governed_dataset", facts=(GOVERNED_FACT,),
                                 coverage={"status": "complete", "eligible_count": 1,
                                           "observed_count": 1, "universe_kind": "fund_assets"})

SQL_EVIDENCE = mk_evidence("e_sql", "controlled_sql", tool_name="run_sql")
SQL_EVIDENCE_2 = mk_evidence("e_sql_2", "controlled_sql", tool_name="run_sql")


def _envelope(**overrides):
    base = {"fragments": [], "canonical_metric_claims": [], "governed_dataset_claims": [],
            "derived_metric_claims": [], "table_claims": [], "supporting_evidence_claims": []}
    base.update(overrides)
    return base


# ===========================================================================
# G1 -- multi-turn evidence_id collision.
#
# ToolEvidence.evidence_id == ToolRequest.call_id (session.py's producers all
# pass evidence_id=request.call_id). Nothing in the codebase asserts that a
# provider's call_id is globally unique across turns of one conversation --
# session.py's `_evidence_for_current_answer` simply concatenates evidence
# lists (durable_evidence + retained history, or this turn's fresh results)
# with no id-based dedupe. The question G1 asks: if two ToolEvidence objects
# from DIFFERENT turns end up in the same list handed to validate_and_render
# with the SAME evidence_id, does synthesis silently bind to one of them
# (ambiguous), or fail closed?
#
# Finding: coverage_guard.validate_and_render builds `canonical_by_id` /
# `governed_by_id` / `supporting_by_id` as `{item.evidence_id: item for item
# in evidence}` and explicitly compares `len(by_id) != len(evidence)` --  a
# duplicate evidence_id anywhere in the list (regardless of which turn it
# came from) collapses the dict to fewer entries than the list, and the whole
# envelope fails closed with a dedicated reason ("duplicate_*_evidence_id")
# BEFORE any claim binding happens. There is no silent "last write wins"
# resolution. This is safe by construction, independent of the current turn
# boundary -- confirmed here at the actual enforcement boundary
# (validate_and_render), not merely asserted.
#
# Conclusion: no production change required. Documented and tested below.
# ===========================================================================

def test_g1_duplicate_evidence_id_across_simulated_turns_fails_closed_canonical():
    # Two DIFFERENT ToolEvidence objects (as if from two different tool calls
    # in two different turns) that happen to reuse the same call_id/evidence_id
    # -- exactly the shape a provider that resets its call_id counter per turn
    # would produce.
    turn1_evidence = mk_evidence("call_1", "canonical_metric",
                                  facts=({"metric_key": "vacancia_pct_fondo", "value": 1.0, "unit": "%",
                                          "entity_id": "TRI", "period": "2026-01"},))
    turn2_evidence = mk_evidence("call_1", "canonical_metric",
                                  facts=({"metric_key": "vacancia_pct_fondo", "value": 9.0, "unit": "%",
                                          "entity_id": "TRI", "period": "2026-06"},))
    envelope = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "call_1",
                                   "metric_key": "vacancia_pct_fondo", "value": 9.0, "unit": "%",
                                   "entity_id": "TRI", "period": "2026-06", "space_type": None,
                                   "space_types": None, "measurement_unit": None}],
    )
    result = validate_and_render(envelope, [turn1_evidence, turn2_evidence], [])
    assert result.valid is False
    assert result.trace.get("reason") == "duplicate_canonical_evidence_id"


def test_g1_duplicate_evidence_id_across_simulated_turns_fails_closed_governed():
    turn1 = mk_evidence("call_2", "governed_dataset", facts=(GOVERNED_FACT,),
                         coverage={"status": "complete", "eligible_count": 1, "observed_count": 1,
                                   "universe_kind": "fund_assets"})
    turn2 = mk_evidence("call_2", "governed_dataset",
                         facts=({"entity_id": "Apo4700", "period": "2026-06", "metric_key": None, "value": None},),
                         coverage={"status": "complete", "eligible_count": 1, "observed_count": 1,
                                   "universe_kind": "fund_assets"})
    envelope = _envelope(
        fragments=[{"type": "governed_dataset_ref", "claim_id": "g1"}],
        governed_dataset_claims=[{"claim_id": "g1", "evidence_id": "call_2", "metric_key": None,
                                   "entity_ids": ["Apo4700"], "period": "2026-06", "universe_kind": "fund_assets"}],
    )
    result = validate_and_render(envelope, [], [turn1, turn2])
    assert result.valid is False
    assert result.trace.get("reason") == "duplicate_governed_evidence_id"


def test_g1_duplicate_evidence_id_across_simulated_turns_fails_closed_supporting():
    turn1 = mk_evidence("call_3", "controlled_sql", tool_name="run_sql")
    turn2 = mk_evidence("call_3", "controlled_sql", tool_name="run_sql")
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "call_3"}],
    )
    result = validate_and_render(envelope, [], [], supporting_evidence=[turn1, turn2])
    assert result.valid is False
    assert result.trace.get("reason") == "duplicate_supporting_evidence_id"


# ===========================================================================
# G2 -- real evidence, wrong claim-type slot.
#
# The A3.2c suite (test_a3_2c_supporting_evidence_transport.py) already
# exhaustively covers: real canonical/governed evidence_id cited inside
# supporting_evidence_claims (rejected), and real controlled_sql evidence_id
# cited inside canonical_metric_claims/governed_dataset_claims (rejected).
# What was NOT covered: two evidence items of DIFFERENT classes sharing the
# textually identical evidence_id string (a hygiene edge, not a call_id
# collision -- e.g. two different producers happening to both be handed the
# same call_id by construction in a test, or an id namespace overlap bug
# upstream). This confirms each claim type still resolves only against its
# own class's dict and never cross-contaminates just because the string
# matches.
# ===========================================================================

def test_g2_same_evidence_id_string_across_classes_never_cross_binds():
    shared_id = "shared_id"
    canonical = mk_evidence(shared_id, "canonical_metric", facts=(CANONICAL_FACT,))
    supporting = mk_evidence(shared_id, "controlled_sql", tool_name="run_sql")
    # canonical_metric_claims must bind against the canonical_metric item...
    envelope_canonical = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": shared_id, **CANONICAL_FACT}],
    )
    result_canonical = validate_and_render(envelope_canonical, [canonical], [], supporting_evidence=[supporting])
    assert result_canonical.valid is True
    # ...and supporting_evidence_claims must bind against the controlled_sql
    # item, in the SAME call, with the SAME evidence_id string.
    envelope_supporting = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": shared_id}],
    )
    result_supporting = validate_and_render(envelope_supporting, [canonical], [], supporting_evidence=[supporting])
    assert result_supporting.valid is True


# ===========================================================================
# G3 -- table_claims must never accept a supporting_evidence_claims claim_id
# as a cell. Indirect coverage existed (cell_claim_ids only ever looked up
# against bound_canonical/bound_derived); this is the explicit test the
# diagnosis asked for.
# ===========================================================================

def test_g3_table_claim_citing_a_supporting_claim_id_as_a_cell_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"},
                   {"type": "evidence_ref", "claim_id": "s1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_sql"}],
        table_claims=[{"claim_id": "t1", "cell_claim_ids": ["c1", "s1"], "order_by": None}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "invalid_table_claim"


# ===========================================================================
# G4 -- orphan / malformed evidence_ref fragments.
# ===========================================================================

def test_g4_evidence_ref_fragment_with_no_matching_supporting_claim_fails_closed():
    # claim_id never declared in supporting_evidence_claims at all.
    envelope = _envelope(fragments=[{"type": "evidence_ref", "claim_id": "ghost"}])
    result = validate_and_render(envelope, [], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "invalid_fragment"


def test_g4_evidence_ref_claim_declared_but_evidence_id_nonexistent_fails_closed():
    # Already covered structurally by A3.2c's suite; re-asserted here as part
    # of the explicit G4 set with the fragment present (full path exercised).
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "does_not_exist"}],
    )
    result = validate_and_render(envelope, [], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "binding_mismatch"


def test_g4_evidence_ref_claim_points_to_wrong_class_evidence_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "evidence_ref", "claim_id": "s1"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_canon"}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "binding_mismatch"


# ===========================================================================
# G5 -- evidence_ref / supporting evidence can never reach FinalPresenter as
# a factual AllowedClaim.
#
# session._allowed_claims only ever reads envelope["canonical_metric_claims"]
# and envelope["derived_metric_claims"] (confirmed by reading session.py) --
# it does not read supporting_evidence_claims at all, and AllowedClaim is a
# dataclass that REQUIRES value/metric_key/unit (a controlled_sql claim has
# none of those to offer). This makes "supporting evidence becomes an
# AllowedClaim" structurally impossible, not merely untested. These tests
# prove that end to end: an envelope carrying both a canonical claim and a
# supporting claim yields an AllowedClaim tuple containing ONLY the canonical
# claim, and that presentation-layer validation independently fails closed
# if anything ever tried to cite the supporting claim_id as a claim_ref.
# ===========================================================================

def test_g5_allowed_claims_excludes_supporting_evidence_claims():
    envelope = {
        "canonical_metric_claims": [{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT}],
        "derived_metric_claims": [],
        "supporting_evidence_claims": [{"claim_id": "s1", "evidence_id": "e_sql"}],
    }
    claims = _allowed_claims(envelope, [CANONICAL_EVIDENCE, SQL_EVIDENCE])
    claim_ids = {claim.claim_id for claim in claims}
    assert claim_ids == {"c1"}
    assert "s1" not in claim_ids


def test_g5_presentation_layer_rejects_a_claim_ref_to_the_excluded_supporting_claim_id():
    # Simulate the (impossible-by-construction, per the above test) case
    # where a presentation-layer output nonetheless tries to cite "s1" --
    # validate_structured_output must reject it as an unknown claim_ref
    # rather than rendering a value for it.
    allowed = (AllowedClaim(claim_id="c1", evidence_id="e_canon", metric_key="vacancia_pct_fondo",
                             entity_id="TRI", value=5.94, unit="%", period="2026-06"),)
    output = {"segments": [{"type": "claim_ref", "claim_id": "c1"},
                            {"type": "claim_ref", "claim_id": "s1"}]}
    try:
        validate_structured_output(output, allowed)
        raised = False
    except ValueError:
        raised = True
    assert raised is True


def test_g5_presentation_layer_never_sees_a_supporting_digit_when_only_supporting_is_cited():
    # A turn whose ONLY claim is a supporting/evidence_ref one has no
    # AllowedClaim at all (canonical_metric_claims is empty) -- FinalPresenter
    # (per its own `if not claims: return ... not_applicable` short circuit)
    # never invokes the presentation model, so there is no path for a
    # supporting-only turn to have its (nonexistent) "value" rephrased.
    envelope = {"canonical_metric_claims": [], "derived_metric_claims": [],
                "supporting_evidence_claims": [{"claim_id": "s1", "evidence_id": "e_sql"}]}
    claims = _allowed_claims(envelope, [SQL_EVIDENCE])
    assert claims == ()


# ===========================================================================
# G6 -- duplicate supporting references (two claim_ids, same evidence_id).
#
# Nothing in coverage_guard's supporting-claim loop deduplicates by
# evidence_id (only claim_id uniqueness/collision is checked). This mirrors
# the existing, unrestricted behavior of canonical_metric_claims and
# governed_dataset_claims, where a fragment can already cite the same
# claim_id from multiple points in the narrative, and nothing stops two
# DIFFERENT claim_ids from independently binding to the same evidence_id
# either (there is no such prohibition anywhere in canonical/governed
# binding). Per the "do not introduce an arbitrary restriction" instruction,
# this is treated as VALID and tested as such: two distinct narrative points
# may each cite the same supporting evidence_id under their own claim_id.
# ===========================================================================

def test_g6_two_supporting_claim_ids_referencing_the_same_evidence_id_is_valid():
    envelope = _envelope(
        fragments=[{"type": "text", "text": "Se revisaron dos aspectos de la misma consulta de apoyo: "},
                   {"type": "evidence_ref", "claim_id": "s1"},
                   {"type": "text", "text": " y "},
                   {"type": "evidence_ref", "claim_id": "s2"}],
        supporting_evidence_claims=[{"claim_id": "s1", "evidence_id": "e_sql"},
                                     {"claim_id": "s2", "evidence_id": "e_sql"}],
    )
    result = validate_and_render(envelope, [], [], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is True
    assert set(result.trace.get("supporting_evidence_ids_referenced", [])) == {"e_sql"}
    assert result.trace.get("supporting_claim_count") == 2


# ===========================================================================
# Additional namespace-disjointness checks the A3.2c suite did not exercise:
# supporting vs governed claim_id collision (only supporting vs canonical was
# tested there).
# ===========================================================================

def test_supporting_claim_id_colliding_with_governed_claim_id_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "governed_dataset_ref", "claim_id": "g1"},
                   {"type": "evidence_ref", "claim_id": "g1"}],
        governed_dataset_claims=[{"claim_id": "g1", "evidence_id": "e_gov", "metric_key": None,
                                   "entity_ids": ["Apo4501"], "period": "2026-06", "universe_kind": "fund_assets"}],
        supporting_evidence_claims=[{"claim_id": "g1", "evidence_id": "e_sql"}],
    )
    result = validate_and_render(envelope, [], [GOVERNED_EVIDENCE], supporting_evidence=[SQL_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "invalid_claim"


# ===========================================================================
# A3.2d fix: derived_metric_claims' claim_id collision check now also covers
# bound_governed.
#
# Probing this (see the read-only diagnosis / final report for the full
# writeup) found that the derived-claims loop's guard clause tested
# `claim_id in bound_derived or claim_id in bound_canonical or claim_id in
# bound_supporting` -- bound_governed was absent, even though the module
# docstring next to the supporting-claims loop states "the three claim-id
# namespaces must stay disjoint". Concretely: a governed_dataset_claims entry
# and a derived_metric_claims entry could share one claim_id and both pass
# validation, each independently rendering a DIFFERENT, individually-correct
# value (governed_dataset_ref -> bound_governed, derived_metric_ref ->
# bound_derived resolve from separate dicts, so no wrong/mixed value was ever
# produced) -- a namespace-hygiene gap relative to the documented invariant,
# not a data-integrity bug. Given the trivial, same-pattern nature of the
# fix (completing a check the code already applies to the other two claim
# types) and its zero risk of rejecting anything that wasn't already a
# documented violation, it was closed directly rather than left as a probe.
# ===========================================================================

def test_derived_claim_id_colliding_with_governed_claim_id_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "governed_dataset_ref", "claim_id": "g1"},
                   {"type": "derived_metric_ref", "claim_id": "g1"}],
        governed_dataset_claims=[{"claim_id": "g1", "evidence_id": "e_gov", "metric_key": None,
                                   "entity_ids": ["Apo4501"], "period": "2026-06", "universe_kind": "fund_assets"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT},
                                  {"claim_id": "c2", "evidence_id": "e_canon_2", **CANONICAL_FACT_2}],
        derived_metric_claims=[{"claim_id": "g1", "operation": "difference",
                                 "lhs_claim_id": "c1", "rhs_claim_id": "c2"}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE, CANONICAL_EVIDENCE_2], [GOVERNED_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "invalid_claim"


# ===========================================================================
# A3.2f fix: governed_dataset_claims' claim_id collision check now also
# covers bound_canonical.
#
# Same asymmetric-namespace shape as the derived-vs-governed gap fixed above
# in A3.2d: the governed-claims loop's guard clause only tested
# `claim_id in bound_governed`, never `claim_id in bound_canonical`, even
# though the supporting- and derived-claims loops (both processed AFTER
# canonical/governed) already check against bound_canonical. Concretely: a
# canonical_metric_claims entry and a governed_dataset_claims entry could
# share one claim_id and both pass validation, each independently rendering
# from its own dict (canonical_metric_ref -> bound_canonical,
# governed_dataset_ref -> bound_governed), so no wrong/mixed value was ever
# produced -- a namespace-hygiene gap relative to the documented "the ...
# claim-id namespaces must stay disjoint" invariant, not a data-integrity
# bug. Closed the same way the derived-vs-governed case was: completing the
# check the code already applies to the other two claim types.
# ===========================================================================

def test_canonical_claim_id_colliding_with_governed_claim_id_fails_closed():
    envelope = _envelope(
        fragments=[{"type": "canonical_metric_ref", "claim_id": "c1"},
                   {"type": "governed_dataset_ref", "claim_id": "c1"}],
        canonical_metric_claims=[{"claim_id": "c1", "evidence_id": "e_canon", **CANONICAL_FACT}],
        governed_dataset_claims=[{"claim_id": "c1", "evidence_id": "e_gov", "metric_key": None,
                                   "entity_ids": ["Apo4501"], "period": "2026-06", "universe_kind": "fund_assets"}],
    )
    result = validate_and_render(envelope, [CANONICAL_EVIDENCE], [GOVERNED_EVIDENCE])
    assert result.valid is False
    assert result.trace.get("reason") == "invalid_claim"
