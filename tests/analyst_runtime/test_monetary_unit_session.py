"""Session-level: the global UF default is sticky per-session once the user
explicitly overrides it, and durable memory always keeps the native unit --
only the rendered text changes with the requested display unit.

Uses the same ScriptedTransport / real-evidence pattern as
test_table_claims_session.py, but with a synthetic fact carrying an explicit
governed presentation_conversion (UF -> CLP), since no real evidence in the
DB currently ships that contract -- this exercises the conversion path end
to end through OpenAIResponsesAnalystSession.ask(), not just coverage_guard
directly.
"""
from __future__ import annotations

from pathlib import Path

from tests.analyst_runtime._evidence_factory import mk_evidence
from tools.analyst_runtime.actions import ActionRegistry
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession
from tools.analyst_runtime.transport import ModelResponse, ToolRequest, ToolResult, ToolSpec

DB = Path("memory/agente_toesca_v2.db")

_FACT = {
    "metric_key": "tax", "value": 100.0, "unit": "UF", "entity_id": "Torre A", "period": "2025",
    "presentation_conversion": {"from_unit": "UF", "to_unit": "CLP", "temporal_basis": "point_in_time",
                                 "reference_value": 35000.0, "source": "raw_uf_diaria", "reference_date": "2025-01-31"},
}


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, _request):
        return next(self.responses)


class _FakeTaxQueryAction:
    """Minimal Action double standing in for analytics_account_query: always
    returns the same canonical fact, bound to whatever call_id the scripted
    tool_requests use for that turn."""
    name = "fake_tax_query"

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(self.name, "fake tax lookup", {"type": "object", "properties": {}})

    def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(request.call_id, True, "{}", trace={"tool_name": self.name},
                          evidence=mk_evidence(request.call_id, "canonical_metric", facts=(_FACT,)))


def _turn_responses(call_id: str, claim_id: str) -> list[ModelResponse]:
    return [
        ModelResponse("", tool_requests=[ToolRequest(call_id, "fake_tax_query", {})]),
        ModelResponse("listo"),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "text", "text": "Contribuciones Torre A 2025: "},
                          {"type": "canonical_metric_ref", "claim_id": claim_id}],
            "canonical_metric_claims": [{"claim_id": claim_id, "evidence_id": call_id, **_FACT}],
            "governed_dataset_claims": [], "derived_metric_claims": [], "table_claims": [],
        }),
    ]


def _session() -> OpenAIResponsesAnalystSession:
    transport = ScriptedTransport([
        *_turn_responses("c1", "cc1"),
        *_turn_responses("c2", "cc2"),
        *_turn_responses("c3", "cc3"),
    ])
    registry = ActionRegistry([_FakeTaxQueryAction()])
    loop = AnalystLoop("sys", transport, registry, registry.tool_specs())
    return OpenAIResponsesAnalystSession(loop, presenter=None, db_path=DB)


def test_unit_override_sticks_across_turns_and_durable_memory_stays_native():
    session = _session()

    turn1 = session.ask("¿Cuánto son las contribuciones de Torre A en 2025?")
    assert "100 UF" in turn1.text

    turn2 = session.ask("Muéstramelo en pesos.")
    assert "3.500.000 CLP" in turn2.text

    turn3 = session.ask("¿Y eso a qué corresponde exactamente?")
    assert "3.500.000 CLP" in turn3.text, "the CLP override must persist to a follow-up that does not repeat it"

    for turn in (turn1, turn2, turn3):
        claim = turn.durable_memory["envelope"]["canonical_metric_claims"][0]
        assert claim["unit"] == "UF" and claim["value"] == 100.0, "durable memory must retain the native unit/value, never the display conversion"
