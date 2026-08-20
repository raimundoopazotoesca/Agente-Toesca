from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tools.analyst_runtime.base import ToolCall, Usage
from tools.analyst_workspace.conversation_service import (
    AnalystSessionResult,
    ConversationService,
    ConversationServiceError,
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
    assert workspace.get_conversation(conversation.id).title == "¿Cómo ha evolucionado la vacancia de Parque…"


def test_manual_title_is_preserved(workspace):
    service = ConversationService(workspace, FakeFactory([_result()]))
    conversation = service.create_conversation()
    workspace.rename_conversation(conversation.id, "Mi análisis")
    service.send_message(conversation.id, "Una pregunta inicial")
    assert workspace.get_conversation(conversation.id).title == "Mi análisis"


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
    assert factory.creations[0][2] == {"source_surface": "factsheet", "fund": "PT"}
