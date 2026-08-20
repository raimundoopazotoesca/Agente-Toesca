from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analyst_runtime.actions import AnalyticsQueryAction
from tools.analyst_runtime.actions import ActionRegistry, RunSqlAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ModelResponse, ToolRequest


DB = Path("memory/agente_toesca_v2.db")


def test_analytics_tool_spec_is_closed_and_exposes_action_range_field():
    spec = AnalyticsQueryAction(DB).tool_spec()

    assert spec.parameters["additionalProperties"] is False
    assert spec.parameters["required"] == ["metric", "period"]
    assert set(spec.parameters["properties"]) == {
        "metric", "funds", "assets", "period", "period_end", "group_by", "order_by", "limit",
    }


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (
            {"metric": "vacancia_pct_fondo", "scope": {"fund": "TRI"}, "period": "2026-06"},
            "unknown analytics_query fields: scope",
        ),
        (
            {"metric": "m2_vacantes", "funds": ["TRI"], "period": "2026-06", "group_by": ["asset"]},
            "group_by must be a string",
        ),
    ],
)
def test_analytics_action_rejects_noncanonical_shapes_before_executor(arguments, expected_error):
    result = AnalyticsQueryAction(DB).execute(ToolRequest("call", "analytics_query", arguments))

    assert result.ok is False
    payload = json.loads(result.content)
    assert payload["error_type"] == "invalid_request"
    assert payload["error"] == expected_error


def test_analytics_action_accepts_range_declared_by_tool_spec():
    result = AnalyticsQueryAction(DB).execute(ToolRequest(
        "call", "analytics_query",
        {"metric": "vacancia_pct_fondo", "funds": ["TRI"], "period": "2026-05", "period_end": "2026-06"},
    ))

    assert result.ok is True
    assert [row["period"] for row in json.loads(result.content)["rows"]] == ["2026-05", "2026-06"]


def test_scripted_analytics_call_exposes_sanitized_request_and_result_trace():
    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("call", "analytics_query", {
                    "metric": "vacancia_pct_fondo", "funds": ["TRI"], "period": "2026-06",
                })]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([RunSqlAction(LiveReadOnlySandbox(DB)), AnalyticsQueryAction(DB)])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("consulta")

    trace = result.turn.tool_calls[0].trace
    assert trace["arguments"] == {"metric": "vacancia_pct_fondo", "funds": ["TRI"], "period": "2026-06"}
    assert trace["result"] == {
        "metric_key": "vacancia_pct_fondo", "source_kind": "canonical", "catalog_version": 1,
        "row_count": 1, "provenance_ingest_run_ids": [142],
    }


def test_scripted_analytics_ranking_uses_the_governed_breakdown_contract():
    class ScriptedTransport:
        def __init__(self):
            self.responses = iter([
                ModelResponse("", [ToolRequest("call", "analytics_query", {
                    "metric": "m2_vacantes", "funds": ["TRI"], "period": "2026-06",
                    "group_by": "asset", "order_by": "value_desc",
                })]),
                ModelResponse("respuesta"),
            ])

        def complete(self, _request):
            return next(self.responses)

    registry = ActionRegistry([RunSqlAction(LiveReadOnlySandbox(DB)), AnalyticsQueryAction(DB)])
    result = AnalystLoop("sys", ScriptedTransport(), registry, registry.tool_specs()).ask("ranking")

    payload = json.loads(result.round_trajectory[1].tool_results[0].content)
    assert [row["entity_id"] for row in payload["rows"][:3]] == ["Mall Curicó", "Apo3001", "Viña Centro"]
    assert [row["value"] for row in payload["rows"][:3]] == pytest.approx([2476.0, 1632.6, 199.83])
    assert result.turn.tool_calls[0].trace["result"] == {
        "metric_key": "m2_vacantes", "source_kind": "breakdown", "catalog_version": 1,
        "row_count": 10, "provenance_ingest_run_ids": [],
    }
