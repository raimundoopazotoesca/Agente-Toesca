"""Stage 5.4 session-level goldens: the raw-only exhaustive-enumeration
bypass (run_sql -> free text listing entities as if complete) must fail
closed before B.3, while ordinary single-asset raw analysis still works."""
from __future__ import annotations

from pathlib import Path

from tools.analyst_runtime.actions import ActionRegistry, RunSqlAction
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
        self.calls = 0

    def present(self, **_kwargs):
        self.calls += 1
        raise AssertionError("a coverage/provenance failure must not reach the presenter")


def _session(transport, presenter=None):
    registry = ActionRegistry([RunSqlAction(LiveReadOnlySandbox(DB))])
    loop = AnalystLoop("sys", transport, registry, registry.tool_specs())
    return OpenAIResponsesAnalystSession(loop, presenter=presenter, db_path=DB)


def test_raw_sql_only_enumeration_of_multiple_assets_fails_closed_before_presenter():
    presenter = RecordingPresenter()
    transport = ScriptedTransport([
        ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT activo_key FROM dim_activo WHERE fondo_key='PT'"})]),
        ModelResponse("Los activos de PT son Torre A, Boulevard y Parking PT."),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "raw_text", "text": "Los activos de PT son Torre A, Boulevard y Parking PT."}],
            "canonical_metric_claims": [], "governed_dataset_claims": [],
        }),
    ])
    session = _session(transport, presenter)

    result = session.ask("Dame todos los activos de PT")

    assert "no puedo confirmar" in result.text.lower()
    assert presenter.calls == 0
    assert result.presentation_integrity_status == "canonical_conflict"


def test_raw_sql_single_asset_analysis_is_not_blocked():
    transport = ScriptedTransport([
        ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT 1"})]),
        ModelResponse("Apo3001 tuvo vacancia alta este mes."),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "raw_text", "text": "Apo3001 tuvo vacancia alta este mes."}],
            "canonical_metric_claims": [], "governed_dataset_claims": [],
        }),
    ])
    session = _session(transport, presenter=None)

    result = session.ask("¿Cómo estuvo Apoquindo 3001?")

    # Human Analytical Presentation v1: raw_text fragments are humanized
    # (raw asset key -> display name) before reaching the reader.
    assert result.text == "Apoquindo 3001 tuvo vacancia alta este mes."
