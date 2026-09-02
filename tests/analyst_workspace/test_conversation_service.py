from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tools.analyst_runtime.base import ToolCall, Usage
from tools.analyst_workspace.conversation_service import (
    AnalystSessionResult,
    ConversationService,
    ConversationServiceError,
    TurnTracePersistenceError,
)
from tools.analyst_workspace.store import WorkspaceStore


@dataclass
class FakeSession:
    responses: list[AnalystSessionResult | Exception]
    calls: list[str] = field(default_factory=list)

    def ask(self, text: str) -> AnalystSessionResult:
        self.calls.append(text)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass
class FakeFactory:
    responses: list[AnalystSessionResult | Exception]
    sessions: list[FakeSession] = field(default_factory=list)
    creations: list[tuple] = field(default_factory=list)

    def create(self, conversation, visible_messages, runtime_context=None):
        self.creations.append((conversation, list(visible_messages), runtime_context))
        session = FakeSession(list(self.responses))
        self.sessions.append(session)
        return session


@dataclass
class FakeTitleGenerator:
    responses: list[str | None | Exception]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def generate(self, user_text: str, assistant_text: str) -> str | None:
        self.calls.append((user_text, assistant_text))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _result(text="Respuesta", **kwargs):
    return AnalystSessionResult(text=text, **kwargs)


@pytest.fixture
def workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    return store


def test_create_conversation_delegates_to_store(workspace):
    service = ConversationService(workspace, FakeFactory([]))
    conversation = service.create_conversation(context={"fund": "PT"})
    assert workspace.get_conversation(conversation.id).context == {"fund": "PT"}


def test_send_persists_visible_user_then_assistant_message(workspace):
    service = ConversationService(workspace, FakeFactory([_result("La vacancia es 5%. ")]))
    conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "¿Cuál es la vacancia?")
    messages = workspace.list_messages(conversation.id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].content == "¿Cuál es la vacancia?"
    assert assistant.content == "La vacancia es 5%. "


def test_send_persists_completed_correlated_turn_trace(workspace):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")])); conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "Pregunta")
    messages = workspace.list_messages(conversation.id)
    trace = assistant.metadata["turn_trace"]
    assert trace["completion"]["status"] == "completed"
    assert trace["identity"]["conversation_id"] == conversation.id
    assert trace["identity"]["user_message_id"] == messages[0].id
    assert trace["identity"]["assistant_message_id"] == assistant.id


def test_trace_persistence_failure_keeps_pending_user_and_explicit_retry_does_not_duplicate_it(workspace, monkeypatch):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")])); conversation = service.create_conversation()
    monkeypatch.setattr("tools.analyst_workspace.conversation_service.build_turn_trace", lambda **_: (_ for _ in ()).throw(ValueError("broken trace")))
    with pytest.raises(TurnTracePersistenceError) as excinfo:
        service.send_message(conversation.id, "Pregunta")
    assert excinfo.value.turn_id and excinfo.value.user_message_id
    pending = workspace.list_messages(conversation.id)
    assert len(pending) == 1 and pending[0].metadata["turn_trace_status"] == "pending"
    pending_turn_id = pending[0].metadata["turn_id"]
    assert pending_turn_id == excinfo.value.turn_id
    monkeypatch.undo()
    # Retry must present the turn_id the failed attempt returned -- reuse is never
    # inferred from conversation + last-pending-message + identical text alone.
    assistant = service.send_message(conversation.id, "Pregunta", turn_id=pending_turn_id)
    messages = workspace.list_messages(conversation.id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert assistant.metadata["turn_trace"]["identity"]["turn_id"] == pending_turn_id


def test_new_turn_with_identical_text_and_no_turn_id_is_not_collapsed_into_failed_turn(workspace, monkeypatch):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")])); conversation = service.create_conversation()
    monkeypatch.setattr("tools.analyst_workspace.conversation_service.build_turn_trace", lambda **_: (_ for _ in ()).throw(ValueError("broken trace")))
    with pytest.raises(TurnTracePersistenceError) as excinfo:
        service.send_message(conversation.id, "Pregunta")
    failed_turn_id = excinfo.value.turn_id
    monkeypatch.undo()
    # A genuinely new send with the same text but no turn_id must never be
    # silently treated as a retry of the earlier failed turn.
    assistant = service.send_message(conversation.id, "Pregunta")
    messages = workspace.list_messages(conversation.id)
    user_messages = [message for message in messages if message.role == "user"]
    assert len(user_messages) == 2
    assert user_messages[0].metadata["turn_id"] == failed_turn_id
    assert user_messages[1].metadata["turn_id"] != failed_turn_id
    assert assistant.metadata["turn_trace"]["identity"]["turn_id"] == user_messages[1].metadata["turn_id"]


def test_unknown_turn_id_is_rejected_and_creates_no_new_message(workspace):
    service = ConversationService(workspace, FakeFactory([])); conversation = service.create_conversation()
    with pytest.raises(ConversationServiceError):
        service.send_message(conversation.id, "Pregunta", turn_id="turn-does-not-exist")
    assert workspace.list_messages(conversation.id) == []


def test_turn_id_from_another_conversation_is_rejected_and_creates_no_new_message(workspace, monkeypatch):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")]))
    conversation_a = service.create_conversation()
    conversation_b = service.create_conversation()
    monkeypatch.setattr("tools.analyst_workspace.conversation_service.build_turn_trace", lambda **_: (_ for _ in ()).throw(ValueError("broken trace")))
    with pytest.raises(TurnTracePersistenceError) as excinfo:
        service.send_message(conversation_a.id, "Pregunta")
    other_turn_id = excinfo.value.turn_id
    monkeypatch.undo()
    with pytest.raises(ConversationServiceError):
        service.send_message(conversation_b.id, "Pregunta", turn_id=other_turn_id)
    assert workspace.list_messages(conversation_b.id) == []


def test_completed_turn_id_is_rejected(workspace):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")])); conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "Pregunta")
    completed_turn_id = assistant.metadata["turn_trace"]["identity"]["turn_id"]
    with pytest.raises(ConversationServiceError):
        service.send_message(conversation.id, "Pregunta", turn_id=completed_turn_id)
    assert len(workspace.list_messages(conversation.id)) == 2


def test_pending_turn_id_with_different_text_is_rejected(workspace, monkeypatch):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")])); conversation = service.create_conversation()
    monkeypatch.setattr("tools.analyst_workspace.conversation_service.build_turn_trace", lambda **_: (_ for _ in ()).throw(ValueError("broken trace")))
    with pytest.raises(TurnTracePersistenceError) as excinfo:
        service.send_message(conversation.id, "Pregunta original")
    pending_turn_id = excinfo.value.turn_id
    monkeypatch.undo()
    with pytest.raises(ConversationServiceError):
        service.send_message(conversation.id, "Pregunta distinta", turn_id=pending_turn_id)
    pending = workspace.list_messages(conversation.id)
    assert len(pending) == 1 and pending[0].content == "Pregunta original"


def test_unrelated_metadata_failure_is_not_mislabeled_trace_persistence_failed(workspace, monkeypatch):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")])); conversation = service.create_conversation()
    monkeypatch.setattr(
        "tools.analyst_workspace.conversation_service.runtime_result_to_metadata",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("unrelated metadata bug")),
    )
    with pytest.raises(ValueError, match="unrelated metadata bug"):
        service.send_message(conversation.id, "Pregunta")


def test_same_conversation_reuses_one_in_memory_session(workspace):
    factory = FakeFactory([_result("Uno"), _result("Dos")])
    service = ConversationService(workspace, factory)
    conversation = service.create_conversation()
    service.send_message(conversation.id, "Primero")
    service.send_message(conversation.id, "Segundo")
    assert len(factory.sessions) == 1
    assert factory.sessions[0].calls == ["Primero", "Segundo"]


def test_different_conversations_use_isolated_sessions(workspace):
    factory = FakeFactory([_result("A"), _result("B")])
    service = ConversationService(workspace, factory)
    first = service.create_conversation()
    second = service.create_conversation()
    service.send_message(first.id, "uno")
    service.send_message(second.id, "dos")
    assert len(factory.sessions) == 2
    assert [session.calls for session in factory.sessions] == [["uno"], ["dos"]]


def test_new_service_rebuilds_session_from_visible_history_after_restart(workspace):
    original = ConversationService(workspace, FakeFactory([_result("Respuesta previa")]))
    conversation = original.create_conversation()
    original.send_message(conversation.id, "Pregunta previa")

    restarted_factory = FakeFactory([_result("Respuesta nueva")])
    restarted = ConversationService(workspace, restarted_factory)
    restarted.send_message(conversation.id, "Pregunta nueva")
    history = restarted_factory.creations[0][1]
    assert [(message.role, message.content) for message in history] == [
        ("user", "Pregunta previa"), ("assistant", "Respuesta previa")
    ]


def test_restart_hydrates_structured_durable_context(workspace):
    memory = {"evidence": [{"evidence_id": "e", "evidence_class": "canonical_metric", "source": {}, "scope": {},
        "semantic_contract": {}, "provenance": {"source": "fixture"}, "coverage": {"status": "complete"},
        "facts": [{"metric_key": "noi", "value": 10.0, "unit": "UF", "entity_id": "PT", "period": "2025"}]}],
        "envelope": {"canonical_metric_claims": [{"claim_id": "noi-2025", "evidence_id": "e", "metric_key": "noi", "value": 10.0, "unit": "UF", "entity_id": "PT", "period": "2025"}], "derived_metric_claims": []}}
    original = ConversationService(workspace, FakeFactory([_result("Respuesta previa", durable_memory=memory)]))
    conversation = original.create_conversation()
    original.send_message(conversation.id, "Pregunta previa")
    restarted_factory = FakeFactory([_result("Respuesta nueva")])
    ConversationService(workspace, restarted_factory).send_message(conversation.id, "Pregunta nueva")
    durable = restarted_factory.creations[0][2]["durable_analytical_context"]
    assert durable["claims"][0]["claim_id"] == "noi-2025"
    assert durable["evidence"][0]["facts"][0]["value"] == 10.0


def test_runtime_metadata_is_whitelisted_and_raw_reasoning_is_not_persisted(workspace):
    result = _result(
        "Respuesta",
        usage=Usage(provider="openai", model="gpt-test", calls=2, input_tokens=10, output_tokens=5),
        tool_calls=[ToolCall(
            name="analytics_lookup_fund",
            args={"metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06"},
            ok=False,
            duration_ms=3.0,
            trace={
                "arguments": {"metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06"},
                "scope": {"fund": "TRI"},
                "error": {"error_type": "semantic_query_error", "message": "fund scope is required"},
            },
        )],
        sql_queries=["SELECT 1"],
    )
    result.raw_reasoning = [{"type": "reasoning", "secret": "never persist"}]
    service = ConversationService(workspace, FakeFactory([result]))
    conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "Consulta")
    assert assistant.metadata.pop("turn_metrics")["llm_rounds"] == 2
    trace = assistant.metadata.pop("turn_trace")
    assert assistant.metadata.pop("turn_trace_status") == "completed"
    assert trace["execution"]["sql_statements"] == ["SELECT 1"]
    assert "secret" not in str(trace)
    assert assistant.metadata == {
        "latency_ms": pytest.approx(assistant.metadata["latency_ms"]),
        "model_calls": 2,
        "action_count": 1,
        "sql_count": 1,
        "sql_queries": ["SELECT 1"],
        "tool_calls": [{
            "name": "analytics_lookup_fund", "ok": False, "duration_ms": 3.0,
            "trace": {
                "arguments": {"metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06"},
                "scope": {"fund": "TRI"},
                "error": {"error_type": "semantic_query_error", "message": "fund scope is required"},
            },
        }],
        "token_usage": {"input_tokens": 10, "output_tokens": 5},
        "provider": "openai",
        "model": "gpt-test",
    }
    assert "raw_reasoning" not in assistant.metadata
    assert "secret" not in str(assistant.metadata)


def test_runtime_failure_keeps_user_message_without_synthetic_assistant(workspace):
    service = ConversationService(workspace, FakeFactory([RuntimeError("provider unavailable")]))
    conversation = service.create_conversation()
    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.send_message(conversation.id, "Pregunta")
    assert [(message.role, message.content) for message in workspace.list_messages(conversation.id)] == [
        ("user", "Pregunta")
    ]


def test_missing_conversation_and_blank_message_are_rejected(workspace):
    service = ConversationService(workspace, FakeFactory([]))
    with pytest.raises(Exception, match="conversation not found"):
        service.send_message("missing", "Hola")
    conversation = service.create_conversation()
    with pytest.raises(ConversationServiceError, match="empty"):
        service.send_message(conversation.id, "  ")


def test_first_user_message_sets_deterministic_auto_title(workspace):
    service = ConversationService(workspace, FakeFactory([_result()]))
    conversation = service.create_conversation()
    service.send_message(conversation.id, "¿Cómo ha evolucionado la vacancia de Parque Titanium?")
    assert workspace.get_conversation(conversation.id).title == "Vacancia Parque Titanium"


def test_manual_title_is_preserved(workspace):
    titles = FakeTitleGenerator(["No debe usarse"])
    service = ConversationService(workspace, FakeFactory([_result()]), titles)
    conversation = service.create_conversation()
    workspace.rename_conversation(conversation.id, "Mi análisis")
    service.send_message(conversation.id, "Una pregunta inicial")
    assert workspace.get_conversation(conversation.id).title == "Mi análisis"


    assert titles.calls == []


def test_greeting_keeps_default_title_until_a_substantive_turn_completes(workspace):
    titles = FakeTitleGenerator(["Vacancia TRI junio 2026"])
    service = ConversationService(workspace, FakeFactory([_result("Hola"), _result("La vacancia fue 5%.")]), titles)
    conversation = service.create_conversation()
    assert conversation.title == "Nueva conversación"
    service.send_message(conversation.id, "Hola")
    assert workspace.get_conversation(conversation.id).title == "Nueva conversación"
    service.send_message(conversation.id, "¿Cuál fue la vacancia de TRI en junio 2026?")
    assert workspace.get_conversation(conversation.id).title == "Vacancia TRI junio 2026"
    assert titles.calls == [("¿Cuál fue la vacancia de TRI en junio 2026?", "La vacancia fue 5%.")]


def test_failed_title_generation_does_not_fail_the_analyst_turn(workspace):
    service = ConversationService(workspace, FakeFactory([_result("Respuesta")]), FakeTitleGenerator([RuntimeError("timeout")]))
    conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "Vacancia TRI junio 2026")
    assert assistant.content == "Respuesta"
    assert workspace.get_conversation(conversation.id).title == "Nueva conversación"


def test_runtime_metadata_includes_turn_latency_breakdown(workspace):
    result = _result("Respuesta", usage=Usage(provider="openai", model="gpt-test", calls=2, latency_ms=18.0),
                     tool_calls=[ToolCall(name="run_sql", duration_ms=4.0)])
    result.hydrated_claim_count = 3
    result.reused_evidence_count = 2
    result.fresh_evidence_count = 1
    service = ConversationService(workspace, FakeFactory([result]))
    conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "Consulta material")
    metrics = assistant.metadata["turn_metrics"]
    assert metrics["llm_rounds"] == 2
    assert metrics["llm_latency_ms"] == 18.0
    assert metrics["tool_calls"] == 1
    assert metrics["tool_latency_ms"] == 4.0
    assert metrics["sql_tool_latency_ms"] == 4.0
    assert metrics["hydrated_claim_count"] == 3
    assert metrics["reused_evidence_count"] == 2
    assert metrics["fresh_evidence_count"] == 1


def test_archive_invalidates_cached_session(workspace):
    factory = FakeFactory([_result("Uno"), _result("Dos")])
    service = ConversationService(workspace, factory)
    conversation = service.create_conversation()
    service.send_message(conversation.id, "Primero")
    service.archive_conversation(conversation.id)
    service.unarchive_conversation(conversation.id)
    service.send_message(conversation.id, "Segundo")
    assert len(factory.sessions) == 2


def test_feedback_continues_to_delegate_to_workspace_store(workspace):
    service = ConversationService(workspace, FakeFactory([_result()]))
    conversation = service.create_conversation()
    assistant = service.send_message(conversation.id, "Pregunta")
    assert service.set_feedback(assistant.id, "up").rating == "up"
    assert service.get_feedback(assistant.id).rating == "up"


def test_conversation_context_is_passed_to_the_session_factory(workspace):
    factory = FakeFactory([_result()])
    service = ConversationService(workspace, factory)
    conversation = service.create_conversation(context={"source_surface": "factsheet", "fund": "PT"})
    service.send_message(conversation.id, "Pregunta")
    assert factory.creations[0][2] == {"source_surface": "factsheet", "fund": "PT",
                                       "durable_analytical_context": {"claims": [], "derived_claims": [], "evidence": []},
                                       "authenticated_user": {"display_name": "Initial admin", "short_name": "Initial", "username": "admin", "role": "admin"}}


def test_authenticated_owner_identity_is_scoped_into_the_new_runtime(workspace):
    raimundo = workspace.create_user("raimundo", "Raimundo", "password-a")
    gregorio = workspace.create_user("gregorio", "Gregorio de la Jara", "password-b", role="admin")
    factory = FakeFactory([_result("Hola")])
    service = ConversationService(workspace, factory)
    conversation = service.create_conversation(user_id=raimundo)

    service.send_message_for_user(conversation.id, raimundo, "Hola")

    context = factory.creations[0][2]
    assert context["authenticated_user"] == {
        "display_name": "Raimundo", "short_name": "Raimundo", "username": "raimundo", "role": "user",
    }
    assert "Gregorio" not in str(context)
    assert gregorio not in str(context)
