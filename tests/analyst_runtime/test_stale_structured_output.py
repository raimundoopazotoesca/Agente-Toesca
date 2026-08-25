"""Regression coverage for per-turn structured-output isolation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession, _TerminalEvidenceValidator, _materialize_governed_dataset_claims
from tools.analyst_runtime.transport import ModelResponse, ToolEvidence, ToolRequest, ToolResult


FINANCIAL_FACT = {
    "metric_key": "ltv_fondo", "value": 61.02, "unit": "%", "entity_id": "TRI", "period": "2026-06",
    "space_type": None, "space_types": None, "measurement_unit": None,
}
TENANT_FACTS = (
    {"metric_key": "gla", "value": 1200.0, "unit": "m2", "entity_id": "Tenant A", "period": "2026-06",
     "space_type": None, "space_types": None, "measurement_unit": None},
    {"metric_key": "gla", "value": 900.0, "unit": "m2", "entity_id": "Tenant B", "period": "2026-06",
     "space_type": None, "space_types": None, "measurement_unit": None},
)
FINANCIAL = ToolEvidence("financial", "canonical_metric", facts=(FINANCIAL_FACT,))
TENANTS = ToolEvidence(
    "tenants", "governed_dataset", coverage={"status": "complete", "observed_count": 2, "eligible_count": 2,
                                                 "universe_kind": "asset_tenants"}, facts=TENANT_FACTS,
)


def _financial_envelope():
    return {"fragments": [{"type": "canonical_metric_ref", "claim_id": "f"}],
            "canonical_metric_claims": [{"claim_id": "f", "evidence_id": "financial", **FINANCIAL_FACT}],
            "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": []}


def _tenant_envelope():
    return {"fragments": [{"type": "text", "text": "Top arrendatarios: "},
                            {"type": "governed_dataset_ref", "claim_id": "t"}],
            "canonical_metric_claims": [],
            "governed_dataset_claims": [{"claim_id": "t", "evidence_id": "tenants", "metric_key": "gla",
                                          "entity_ids": ["Tenant A", "Tenant B"], "period": "2026-06",
                                          "universe_kind": "asset_tenants"}],
            "derived_metric_claims": [], "table_claims": []}


def _tenant_table_envelope():
    claims = [{"claim_id": f"t{index}", "evidence_id": "tenants", **fact}
              for index, fact in enumerate(TENANT_FACTS)]
    return {"fragments": [{"type": "text", "text": "Top arrendatarios:"}],
            "canonical_metric_claims": claims, "governed_dataset_claims": [], "derived_metric_claims": [],
            "table_claims": [{"claim_id": "table", "cell_claim_ids": ["t0", "t1"], "order_by": "value_desc"}]}


class _Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return next(self.responses)


class _Executor:
    def execute(self, request):
        evidence = FINANCIAL if request.name == "financial" else TENANTS
        return ToolResult(request.call_id, True, "{}", evidence=replace(evidence, evidence_id=request.call_id))


class _NormalizationTransport:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, _request):
        return ModelResponse("", structured_output=self.payload)


@pytest.mark.parametrize("request_kind", [
    "prior_fact", "prior_explanation", "prior_formatting", "prior_comparison",
])
def test_current_request_allows_only_declared_compatible_prior_evidence(request_kind):
    validator = _TerminalEvidenceValidator(
        _NormalizationTransport({
            "request_kind": request_kind, "ambiguous": False,
            "compatible_evidence_ids": ["financial"],
        }),
        "sys", [FINANCIAL],
    )

    assert validator.accept(user_message="seguimiento", candidate=ModelResponse("candidato"), history=[])


@pytest.mark.parametrize("payload", [
    None,
    {"request_kind": "new_factual", "ambiguous": False, "compatible_evidence_ids": []},
    {"request_kind": "prior_fact", "ambiguous": True, "compatible_evidence_ids": ["financial"]},
    {"request_kind": "prior_fact", "ambiguous": False, "compatible_evidence_ids": ["unknown"]},
])
def test_current_request_fails_closed_for_invalid_ambiguous_or_new_factual_reuse(payload):
    validator = _TerminalEvidenceValidator(_NormalizationTransport(payload), "sys", [FINANCIAL])

    assert not validator.accept(user_message="consulta nueva", candidate=ModelResponse("candidato"), history=[])


def test_dataset_claim_identity_is_materialized_from_evidence_not_provider_fields():
    evidence = ToolEvidence("d", "governed_dataset", coverage={"status": "complete", "universe_kind": "grouped", "universe_id": "u"}, facts=(
        {"metric_key": "gla_m2", "value": 2.0, "unit": "m2", "entity_id": "Tenant A", "period": None},
        {"metric_key": "gla_m2", "value": 1.0, "unit": "m2", "entity_id": "Tenant B", "period": None},
    ))
    envelope = {"governed_dataset_claims": [{"claim_id": "g", "evidence_id": "d", "metric_key": "wrong", "entity_ids": ["wrong"], "period": "2020", "universe_kind": "wrong"}]}

    claim = _materialize_governed_dataset_claims(envelope, [evidence])["governed_dataset_claims"][0]

    assert claim == {"claim_id": "g", "evidence_id": "d", "metric_key": "gla_m2", "entity_ids": ["Tenant A", "Tenant B"], "period": None, "universe_kind": "grouped"}


def _turn(kind: str, envelope, turn_id: int):
    if kind == "none":
        return [
            ModelResponse("Sin evidencia nueva."),
            ModelResponse("", structured_output={
                "request_kind": "conversational", "ambiguous": False,
                "compatible_evidence_ids": [],
            }),
            ModelResponse("ok", structured_output=envelope),
        ]
    call_id = f"{kind}-{turn_id}"
    output = deepcopy(envelope)
    if output is not None:
        for claim in output.get("canonical_metric_claims", []) + output.get("governed_dataset_claims", []):
            claim["evidence_id"] = call_id
    return [
        ModelResponse("", [ToolRequest(call_id, kind, {})]),
        ModelResponse("InvestigaciÃ³n terminada."),
        ModelResponse("ok", structured_output=output),
    ]


def _session(*turns):
    transport = _Transport([response for turn_id, (kind, envelope) in enumerate(turns)
                            for response in _turn(kind, envelope, turn_id)])
    return OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, _Executor()), presenter=None), transport


def test_invalid_structured_dataset_envelope_falls_back_to_current_dataset_facts():
    """A broken rewrite may not discard fresh dataset evidence for old prose."""
    tenants = ToolEvidence(
        "turn-2-tenants", "governed_dataset",
        coverage={"status": "complete", "observed_count": 2, "eligible_count": 2,
                  "universe_kind": "asset_tenants"},
        facts=(
            {"metric_key": "gla", "value": 1200.0, "unit": "m2", "entity_id": "Tenant A", "period": "2026-06"},
            {"metric_key": "gla", "value": 900.0, "unit": "m2", "entity_id": "Tenant B", "period": "2026-06"},
        ),
    )

    result = validate_and_render({}, [], [tenants])

    assert not result.valid
    assert "Tenant A" in result.content
    assert "Tenant B" in result.content
    assert "1.200" in result.content


def test_financial_then_dataset_synthesis_receives_only_current_turn_trajectory():
    session, transport = _session(("financial", _financial_envelope()), ("dataset", _tenant_envelope()))

    first = session.ask("Â¿CuÃ¡l fue el LTV de TRI?")
    second = session.ask("Top 5 arrendatarios por GLA de Apo3001.")

    final_request = transport.requests[-1]
    assert "61,02%" in first.text
    assert "Tenant A" in second.text and "Tenant B" in second.text
    assert "61,02%" not in second.text
    assert all("61,02%" not in (item.text or "") for item in final_request.history)
    assert [result.evidence.evidence_id for item in final_request.history for result in item.tool_results if result.evidence] == ["dataset-1"]


def test_stale_financial_terminal_is_rejected_before_dataset_tools_and_never_retained():
    """A new factual request cannot complete from the previous turn's evidence.

    The scripted provider deliberately tries stale LTV prose.  CurrentRequest
    identifies the new request as independent, so the loop must continue to a
    governed dataset call; the rejected candidate is absent from both the
    visible result and the retained/synthesis trajectories.
    """
    tenant_envelope = _tenant_envelope()
    tenant_envelope["governed_dataset_claims"][0]["evidence_id"] = "dataset-1"
    transport = _Transport([
        ModelResponse("", [ToolRequest("financial-0", "financial", {})]),
        ModelResponse("LTV TRI: 61,02%."),
        ModelResponse("ok", structured_output=_financial_envelope()),
        ModelResponse("LTV TRI: 61,02%."),
        ModelResponse("", structured_output={
            "request_kind": "new_factual", "ambiguous": False,
            "compatible_evidence_ids": [],
        }),
        ModelResponse("", [ToolRequest("dataset-1", "dataset", {})]),
        ModelResponse("Top arrendatarios."),
        ModelResponse("ok", structured_output=tenant_envelope),
    ])
    session = OpenAIResponsesAnalystSession(AnalystLoop("sys", transport, _Executor()), presenter=None)

    session.ask("¿Cuál fue el LTV de TRI?")
    result = session.ask("Top 5 arrendatarios por GLA de Apo3001.")

    assert "Tenant A" in result.text and "61,02%" not in result.text
    current_request = next(request for request in transport.requests
                           if request.output_contract and request.output_contract.name == "CurrentRequest")
    assert current_request.output_contract.name == "CurrentRequest"
    assert any("no satisface la solicitud actual" in request.message for request in transport.requests)
    assert all("61,02%" not in (item.text or "") for item in transport.requests[-1].history)


def test_dataset_then_financial_and_every_failure_fallback_remain_current_turn_scoped():
    session, _ = _session(
        ("dataset", _tenant_envelope()), ("financial", _financial_envelope()),
        ("dataset", None), ("financial", None),
    )

    dataset = session.ask("Top 5 arrendatarios por GLA de Apo3001.")
    financial = session.ask("Â¿CuÃ¡l fue el LTV de TRI?")
    failed_dataset = session.ask("Top 5 arrendatarios por GLA de Apo3001.")
    failed_financial = session.ask("Â¿CuÃ¡l fue el LTV de TRI?")

    assert "Tenant A" in dataset.text
    assert "61,02%" in financial.text and "Tenant A" not in financial.text
    assert "Tenant A" in failed_dataset.text and "61,02%" not in failed_dataset.text
    assert "61,02%" in failed_financial.text and "Tenant A" not in failed_financial.text
    assert failed_dataset.presentation_integrity_status == "canonical_conflict"
    assert failed_financial.presentation_integrity_status == "canonical_conflict"


def test_table_turn_after_financial_turn_cannot_reuse_the_financial_scalar():
    session, _ = _session(("financial", _financial_envelope()), ("dataset", _tenant_table_envelope()))

    session.ask("Â¿CuÃ¡l fue el LTV de TRI?")
    table = session.ask("Top 5 arrendatarios por GLA de Apo3001 en una tabla.")

    assert "Tenant A" in table.text and "Tenant B" in table.text
    assert "|" in table.text
    assert "61,02%" not in table.text


def test_repeated_financial_dataset_sequence_and_none_turn_do_not_replay_visible_output():
    session, _ = _session(
        ("financial", _financial_envelope()), ("dataset", _tenant_envelope()),
        ("financial", _financial_envelope()), ("dataset", _tenant_envelope()),
        ("none", {"fragments": [{"type": "text", "text": "Sin datos."}], "canonical_metric_claims": [],
                   "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": []}),
        ("dataset", _tenant_envelope()),
    )

    outputs = [session.ask(question).text for question in (
        "LTV", "Top tenants", "LTV", "Top tenants", "Nada", "Top tenants",
    )]

    assert all("61,02%" in outputs[index] and "Tenant A" not in outputs[index] for index in (0, 2))
    assert all("Tenant A" in outputs[index] and "61,02%" not in outputs[index] for index in (1, 3, 5))
    assert outputs[4] == "Sin datos."
