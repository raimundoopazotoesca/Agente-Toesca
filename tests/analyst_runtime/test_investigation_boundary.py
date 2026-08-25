from dataclasses import dataclass, field

from tools.analyst_runtime.analyst_loop import AnalystLoop, MAX_INVESTIGATION_ROUNDS
from tools.analyst_runtime.base import Usage
from tools.analyst_runtime.transport import ModelResponse, ToolRequest, ToolResult


@dataclass
class Transport:
    responses: list[ModelResponse]
    requests: list = field(default_factory=list)

    def complete(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


class Executor:
    def execute(self, request):
        return ToolResult(request.call_id, True, "ok")


def test_investigate_stops_at_budget_without_finalization():
    transport = Transport([
        ModelResponse("", [ToolRequest(str(i), "tool", {})], usage=Usage(calls=1))
        for i in range(MAX_INVESTIGATION_ROUNDS)
    ])
    result = AnalystLoop("sys", transport, Executor()).investigate("q")

    assert result.termination_reason == "budget_exhausted"
    assert len(transport.requests) == MAX_INVESTIGATION_ROUNDS
    assert result.final_text == ""
    assert result.usage.calls == MAX_INVESTIGATION_ROUNDS


def test_ask_legacy_finalizes_budget_once_without_tools():
    transport = Transport([
        *[ModelResponse("", [ToolRequest(str(i), "tool", {})], usage=Usage(calls=1))
          for i in range(MAX_INVESTIGATION_ROUNDS)],
        ModelResponse("final", usage=Usage(calls=1)),
    ])
    result = AnalystLoop("sys", transport, Executor()).ask("q")

    assert result.turn.text == "final"
    assert len(transport.requests) == MAX_INVESTIGATION_ROUNDS + 1
    assert transport.requests[-1].tools == []
    assert result.turn.usage.calls == MAX_INVESTIGATION_ROUNDS + 1


def test_rejected_terminal_candidate_continues_same_investigation_without_stale_text():
    class RejectFirst:
        calls = 0

        def accept(self, **_kwargs):
            self.calls += 1
            return self.calls > 1

    validator = RejectFirst()
    transport = Transport([
        ModelResponse("LTV del fondo: 61,02%"),
        ModelResponse("respuesta actual"),
    ])
    result = AnalystLoop("sys", transport, Executor(), terminal_validator=validator).investigate("Top tenants")

    assert result.final_text == "respuesta actual"
    assert len(transport.requests) == 2
    assert "LTV" not in "".join(item.text or "" for item in result.round_trajectory)
    assert "no satisface la solicitud actual" in transport.requests[1].message
