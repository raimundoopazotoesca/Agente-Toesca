import json
from pathlib import Path

from tools.analyst_runtime.actions import (
    ActionRegistry, AnalyticsBreakdownAssetAction, AnalyticsLookupAssetAction,
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
        "resolve_entity", "list_assets", "analytics_lookup_dimensional",
    }
    assert isinstance(registry._by_name["run_sql"], RunSqlAction)
    assert isinstance(registry._by_name["schema_search"], SchemaSearchAction)
    assert isinstance(registry._by_name["analytics_lookup_fund"], AnalyticsLookupFundAction)
    assert isinstance(registry._by_name["analytics_lookup_asset"], AnalyticsLookupAssetAction)
    assert isinstance(registry._by_name["analytics_breakdown_asset"], AnalyticsBreakdownAssetAction)


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
