import json
from pathlib import Path

from tools.analyst_runtime.actions import (
    ActionRegistry, AnalyticsDatasetQueryAction, AnalyticsBreakdownAssetAction, AnalyticsLookupAssetAction,
    AnalyticsLookupFundAction, RunSqlAction, SchemaSearchAction,
)
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.session import OpenAIResponsesAnalystSessionFactory
from tools.analyst_runtime.transport import ModelResponse, ToolRequest


DB = Path("memory/agente_toesca_v2.db")


class ScriptedTransport:
    def __init__(self, responses): self.responses = iter(responses)
    def complete(self, request): return next(self.responses)


def test_alpha_factory_registers_exactly_governed_and_exploratory_actions():
    factory = OpenAIResponsesAnalystSessionFactory(DB, client_factory=lambda: object(), presenter_factory=None)
    session = factory.create(None, [])
    registry = session._loop.action_executor
    assert set(registry._by_name) == {
        "run_sql", "schema_search", "analytics_lookup_fund", "analytics_lookup_asset", "analytics_breakdown_asset", "analytics_account_query",
        "resolve_entity", "list_assets", "analytics_lookup_dimensional", "analytics_query_dataset",
    }
    assert isinstance(registry._by_name["run_sql"], RunSqlAction)
    assert isinstance(registry._by_name["schema_search"], SchemaSearchAction)
    assert isinstance(registry._by_name["analytics_lookup_fund"], AnalyticsLookupFundAction)
    assert isinstance(registry._by_name["analytics_lookup_asset"], AnalyticsLookupAssetAction)
    assert isinstance(registry._by_name["analytics_breakdown_asset"], AnalyticsBreakdownAssetAction)
    assert isinstance(registry._by_name["analytics_query_dataset"], AnalyticsDatasetQueryAction)


def test_scripted_loop_dispatches_lookup_capability_with_semantic_envelope():
    action = AnalyticsLookupFundAction(DB)
    registry = ActionRegistry([RunSqlAction(LiveReadOnlySandbox(DB)), action])
    transport = ScriptedTransport([ModelResponse("", [ToolRequest("1", action.name, {"metric":"vacancia_pct_fondo","fund":"TRI","period":"2026-06"})]), ModelResponse("respuesta")])
    result = AnalystLoop("sys", transport, registry, registry.tool_specs()).ask("x")
    assert result.turn.tool_calls[0].name == "analytics_lookup_fund"
    assert result.turn.tool_calls[0].ok


def test_scripted_loop_keeps_run_sql_available_and_benchmark_contract_has_no_analytics():
    registry = ActionRegistry([RunSqlAction(LiveReadOnlySandbox(DB)), AnalyticsLookupFundAction(DB)])
    transport = ScriptedTransport([ModelResponse("", [ToolRequest("1", "run_sql", {"query":"SELECT 1"})]), ModelResponse("respuesta")])
    result = AnalystLoop("sys", transport, registry, registry.tool_specs()).ask("x")
    assert result.turn.tool_calls[0].name == "run_sql"
    from eval.benchmark.adapters.track_b_frontier import _RUN_SQL_SPEC
    assert _RUN_SQL_SPEC.name == "run_sql"


def test_dataset_action_keeps_the_full_query_contract_in_governed_evidence():
    action = AnalyticsDatasetQueryAction(DB)
    request = ToolRequest("dataset", action.name, {
        "dataset": "rent_roll", "filters": [{"field": "activo_key", "op": "eq", "value": "Apo3001", "value_end": None}, {"field": "periodo", "op": "eq", "value": "2026-06", "value_end": None}],
        "group_by": ["arrendatario"], "measures": [{"measure": "gla_m2", "aggregation": "sum"}],
        "order_by": "gla_m2", "descending": True, "limit": 5, "share_of_total": True,
        "row_axis": None, "column_axis": None,
    })
    result = action.execute(request)
    assert result.ok and result.evidence is not None
    assert result.evidence.semantic_contract["filters"] == request.arguments["filters"]
    assert result.evidence.semantic_contract["limit"] == 5


def test_factory_does_not_replay_visible_transcript_after_restart():
    """Restart reconstruction relies on durable context, never stale prose."""
    factory = OpenAIResponsesAnalystSessionFactory(DB, client_factory=lambda: object(), presenter_factory=None)
    messages = [
        type("Message", (), {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}"})()
        for index in range(20)
    ]

    session = factory.create(None, messages)

    assert session._history == []


def test_factory_states_current_request_precedence_in_its_runtime_prompt():
    factory = OpenAIResponsesAnalystSessionFactory(DB, client_factory=lambda: object(), presenter_factory=None)

    session = factory.create(None, [])

    assert "Prioriza la solicitud actual del usuario" in session._loop.system_prompt
