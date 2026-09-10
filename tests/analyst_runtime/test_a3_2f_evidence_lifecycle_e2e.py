"""A3.2f: genuine end-to-end evidence lifecycle test.

Closes the one gap the A3.2f diagnostic/design memo found with no existing
analog: every individual boundary of the evidence/citation pipeline is
well tested (test_result_evidence_contract.py, test_a3_2b/c/d, test_
coverage_guard.py on the producer/coverage_guard side; test_a3_2e_durable_
evidence_restart.py on the persist/restart side), but nothing chains them
all through one real `.ask()` call:

    real producer -> ToolEvidence -> coverage_guard -> durable projection
    -> persistence -> simulated restart -> reconstruction -> follow-up
    claim -> coverage_guard again

This test drives that full chain in one place. It uses:
- a REAL governed producer (AnalyticsLookupAssetAction against the real
  knowledge DB), mirroring test_governed_expansion.py -- the evidence
  entering coverage_guard is genuine, not hand-built;
- a REAL WorkspaceStore (SQLite, tmp_path), mirroring
  test_a3_2e_durable_evidence_restart.py;
- a REAL OpenAIResponsesAnalystSession (not a fake), driving `.ask()` for
  real through AnalystLoop/coverage_guard;
- a STUBBED ModelTransport (no live LLM/API call), mirroring
  test_stale_structured_output.py's _Transport/_turn pattern.

Turn 3 is the adversarial half: a follow-up claim that tampers with the
reconstructed evidence's value must still fail closed with the same rigor
coverage_guard applies to fresh evidence -- proving restart does not
weaken validation.
"""
from __future__ import annotations

from pathlib import Path

from tools.analyst_runtime.actions import AnalyticsLookupAssetAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession, _reconstruct_durable_evidence_batch
from tools.analyst_runtime.transport import ModelResponse, ToolRequest
from tools.analyst_workspace.store import WorkspaceStore

DB = Path("memory/agente_toesca_v2.db")
ACTION = AnalyticsLookupAssetAction(DB)
LOOKUP_ARGS = {"metric": "ltv_activo", "assets": ["Apo3001"], "period": "2026-06", "period_end": None}


class _Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return next(self.responses)


class _Executor:
    """Dispatches to the one real producer under test -- no fake evidence
    anywhere in this test."""

    def execute(self, request):
        return ACTION.execute(request)


def _canonical_claim(claim_id: str, evidence_id: str, fact: dict) -> dict:
    return {"claim_id": claim_id, "evidence_id": evidence_id, **fact}


def _envelope(claim: dict) -> dict:
    return {
        "fragments": [{"type": "text", "text": "El LTV de Apo3001 es "},
                      {"type": "canonical_metric_ref", "claim_id": claim["claim_id"]}],
        "canonical_metric_claims": [claim],
        "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": [],
    }


def test_evidence_lifecycle_e2e_survives_restart_and_rebinds_with_the_same_rigor(tmp_path):
    # ---- Turn 1: fresh session, real producer, real coverage_guard bind ----
    call_id = "call-1"
    tool_result = ACTION.execute(ToolRequest(call_id, ACTION.name, LOOKUP_ARGS))
    assert tool_result.ok
    fact = tool_result.evidence.facts[0]

    transport1 = _Transport([
        ModelResponse("", [ToolRequest(call_id, ACTION.name, LOOKUP_ARGS)]),
        ModelResponse("Investigación terminada."),
        ModelResponse("ok", structured_output=_envelope(_canonical_claim("c1", call_id, fact))),
    ])
    session1 = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport1, _Executor()), presenter=None, db_path=DB)

    turn1 = session1.ask("¿Cuál fue el LTV de Apo3001 en 2026-06?")

    # Validation succeeded (coverage_guard only sets durable_memory when
    # validation.valid -- see session.py) and only durable evidence classes
    # were projected.
    assert turn1.durable_memory is not None
    assert turn1.durable_memory["evidence"]
    assert all(item["evidence_class"] in ("canonical_metric", "governed_dataset")
               for item in turn1.durable_memory["evidence"])
    assert "71,15%" in turn1.text

    # ---- Persist via a REAL WorkspaceStore ----
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    user_id = store.create_user("raimundo", "Raimundo", "password-a")
    conversation = store.create_conversation(owner_user_id=user_id)
    user_message = store.append_message(conversation.id, "user", "¿Cuál fue el LTV de Apo3001 en 2026-06?", metadata={})
    assistant_message = store.append_message(conversation.id, "assistant", turn1.text, metadata={})
    store.persist_analytical_turn(conversation.id, user_message.id, assistant_message.id, turn1.durable_memory)

    # ---- Simulated restart: reload + reconstruct (no FakeFactory) ----
    durable = store.load_durable_context_for_user(conversation.id, user_id)
    assert durable["evidence"]
    reconstructed = _reconstruct_durable_evidence_batch(durable["evidence"])
    assert len(reconstructed) == 1
    reconstructed_evidence_id = reconstructed[0].evidence_id
    reconstructed_fact = reconstructed[0].facts[0]

    # Semantic equivalence for coverage_guard's purposes: the reconstructed
    # fact is byte-identical to the original -- only `result` (deliberately
    # excluded, see transport.project_evidence_for_durable_storage) differs.
    assert reconstructed_fact == fact

    # ---- Turn 2 (post-restart): a NEW session object, no tool call this
    # turn, citing the reconstructed evidence for a genuinely new claim_id
    # through coverage_guard AGAIN ----
    transport2 = _Transport([
        ModelResponse("Recuerdo el LTV de Apo3001."),
        ModelResponse("", structured_output={
            "request_kind": "prior_fact", "ambiguous": False,
            "compatible_evidence_ids": [reconstructed_evidence_id],
        }),
        ModelResponse("ok", structured_output=_envelope(
            _canonical_claim("c2", reconstructed_evidence_id, reconstructed_fact))),
    ])
    session2 = OpenAIResponsesAnalystSession(
        AnalystLoop("sys", transport2, _Executor()), presenter=None, db_path=DB,
        durable_evidence=reconstructed,
    )
    turn2 = session2.ask("¿Puedes recordarme ese mismo LTV?")

    # Same rendered value as turn 1 -- reconstructed evidence binds and
    # renders identically to pre-restart evidence for the same fact.
    assert "71,15%" in turn2.text
    assert turn2.durable_memory is not None
    assert turn2.reused_evidence_count == 1

    # ---- Turn 3 (adversarial): a follow-up claim that tampers with the
    # reconstructed evidence's value must still fail closed, proving
    # restart does not weaken coverage_guard's rigor ----
    tampered_fact = {**reconstructed_fact, "value": reconstructed_fact["value"] + 1.0}
    transport3 = _Transport([
        ModelResponse("Recuerdo el LTV de Apo3001."),
        ModelResponse("", structured_output={
            "request_kind": "prior_fact", "ambiguous": False,
            "compatible_evidence_ids": [reconstructed_evidence_id],
        }),
        ModelResponse("ok", structured_output=_envelope(
            _canonical_claim("c3", reconstructed_evidence_id, tampered_fact))),
    ])
    session3 = OpenAIResponsesAnalystSession(
        AnalystLoop("sys", transport3, _Executor()), presenter=None, db_path=DB,
        durable_evidence=reconstructed,
    )
    turn3 = session3.ask("¿Puedes recordarme ese mismo LTV?")

    # Fail-closed: the tampered claim never binds, so no durable_memory is
    # produced for it, and coverage_guard's deterministic fallback renders
    # only the REAL, correctly-bound evidence (never the tampered value) --
    # see coverage_guard._fail, which renders canonical_evidence's own facts
    # on a binding failure rather than anything from the untrusted envelope.
    assert turn3.durable_memory is None
    assert "171,15%" not in turn3.text  # the tampered (value + 1.0) rendering
    assert "71,15%" in turn3.text  # the real evidence, rendered deterministically
