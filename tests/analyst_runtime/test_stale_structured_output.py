"""Regression coverage for per-turn structured-output isolation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession
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


def _turn(kind: str, envelope, turn_id: int):
    if kind == "none":
        return [ModelResponse("Sin evidencia nueva."), ModelResponse("ok", structured_output=envelope)]
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
