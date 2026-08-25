"""Session-level: when coverage_guard produces a governed table, the
presentation rephrasing pass must be skipped entirely.

Real QA (CASE8, "pon en una tabla la vacancia de Apoquindo y TRI...") showed
FinalPresenter's own protocol -- which explicitly allows it to add Markdown
"cuando ayude a leer" -- freelancing a SECOND, LLM-authored table via
claim_ref segments, duplicating the deterministic one coverage_guard already
rendered. Since a duplicate table is a fact-safe but real "no duplication"
regression, the fix is to never call the presenter when a table is about to
be appended (empty claims tuple -> FinalPresenter returns the deterministic
draft verbatim, never invoking the provider at all -- see
FinalPresenter.present's ``if not claims`` fast path).
"""
from __future__ import annotations

from pathlib import Path

from tools.analyst_runtime.actions import ActionRegistry, AnalyticsLookupFundAction, RunSqlAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.session import OpenAIResponsesAnalystSession
from tools.analyst_runtime.transport import ModelResponse, ToolRequest

DB = Path("memory/agente_toesca_v2.db")


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, _request):
        return next(self.responses)


class RecordingPresenter:
    def __init__(self):
        self.calls: list[tuple] = []

    def present(self, *, user_message, draft_answer, claims=()):
        self.calls.append(claims)
        from tools.analyst_runtime.presentation import PresentationResult
        return PresentationResult(draft_answer, False, 0.0, None, None, "not_applicable")


def _fund_fact(metric, fund, period):
    action = AnalyticsLookupFundAction(DB)
    result = action.execute(ToolRequest("call", action.name, {"metric": metric, "fund": fund, "period": period}))
    assert result.ok and result.evidence is not None
    return result.evidence.facts[0]


def test_presenter_receives_no_claims_when_a_table_is_present():
    apo = _fund_fact("vacancia_pct_fondo", "Apo", "2026-06")
    tri = _fund_fact("vacancia_pct_fondo", "TRI", "2026-06")
    presenter = RecordingPresenter()
    transport = ScriptedTransport([
        ModelResponse("", [
            ToolRequest("ca", "analytics_lookup_fund", {"metric": "vacancia_pct_fondo", "fund": "Apo", "period": "2026-06"}),
            ToolRequest("ctri", "analytics_lookup_fund", {"metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06"}),
        ]),
        ModelResponse("listo"),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "text", "text": "Vacancia de ambos fondos:"}],
            "canonical_metric_claims": [
                {"claim_id": "c_apo", "evidence_id": "ca", **apo},
                {"claim_id": "c_tri", "evidence_id": "ctri", **tri},
            ],
            "governed_dataset_claims": [], "derived_metric_claims": [],
            "table_claims": [{"claim_id": "t1", "cell_claim_ids": ["c_apo", "c_tri"], "order_by": None}],
        }),
    ])
    registry = ActionRegistry([RunSqlAction(LiveReadOnlySandbox(DB)), AnalyticsLookupFundAction(DB)])
    loop = AnalystLoop("sys", transport, registry, registry.tool_specs())
    session = OpenAIResponsesAnalystSession(loop, presenter=presenter, db_path=DB)

    result = session.ask("Pon en una tabla la vacancia de Apoquindo y TRI en junio de 2026.")

    assert presenter.calls == [()]  # presenter was invoked, but with an empty claims tuple
    assert result.text.count("| Fondo") <= 1  # the table header appears at most once -- no duplicate
    assert "11,49%" in result.text and "5,95%" in result.text
