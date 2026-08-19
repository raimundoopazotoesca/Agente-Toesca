"""Alpha product-voice boundary tests (offline; no provider calls)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from eval.round_b.runner import build_run_manifest
from tools.analyst_runtime.session import (
    ALPHA_PRODUCT_VOICE,
    OpenAIResponsesAnalystSessionFactory,
    _alpha_system_prompt,
)
from tools.analyst_workspace.conversation_service import ConversationService
from tools.analyst_workspace.store import WorkspaceStore


@dataclass
class _VisibleMessage:
    role: str
    content: str


class _FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text="Respuesta del analista.",
            output=[],
            usage=SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                input_tokens_details=None,
                output_tokens_details=None,
            ),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


def _knowledge_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    return path


def test_alpha_voice_is_instructions_not_conversation_input(tmp_path):
    """Catches a voice layer injected as a visible user/history message."""
    client = _FakeClient()
    factory = OpenAIResponsesAnalystSessionFactory(
        _knowledge_db(tmp_path / "knowledge.db"), client_factory=lambda: client
    )

    session = factory.create(
        conversation=object(),
        visible_messages=[_VisibleMessage("user", "Pregunta previa")],
    )
    result = session.ask("Consulta actual")

    assert result.text == "Respuesta del analista."
    request = client.responses.calls[0]
    assert ALPHA_PRODUCT_VOICE in request["instructions"]
    assert request["input"] == [
        {"role": "user", "content": "Pregunta previa"},
        {"role": "user", "content": "Consulta actual"},
    ]
    assert ALPHA_PRODUCT_VOICE not in json.dumps(request["input"], ensure_ascii=False)


def test_alpha_final_presentation_policy_overrides_evidence_disclosure():
    """Evidence controls claims; Alpha controls how final claims are presented."""
    prompt = _alpha_system_prompt("CORE EVIDENCE POLICY")
    normalized_voice = " ".join(ALPHA_PRODUCT_VOICE.split())

    assert prompt == f"CORE EVIDENCE POLICY\n\n{ALPHA_PRODUCT_VOICE}"
    assert "La disciplina de evidencia determina qu\u00e9 puedes afirmar" in normalized_voice
    assert "pol\u00edtica de presentaci\u00f3n de la respuesta final" in normalized_voice
    assert "conserva esa distinci\u00f3n en tu razonamiento" in normalized_voice.lower()


def test_alpha_voice_stays_out_of_workspace_and_benchmark_contract(tmp_path):
    """Catches persisting product instructions or changing F4 benchmark inputs."""
    client = _FakeClient()
    factory = OpenAIResponsesAnalystSessionFactory(
        _knowledge_db(tmp_path / "knowledge.db"), client_factory=lambda: client
    )
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    service = ConversationService(store, factory)
    conversation = service.create_conversation()

    service.send_message(conversation.id, "Vacancia TRI")

    persisted = store.list_messages(conversation.id)
    assert [(message.role, message.content) for message in persisted] == [
        ("user", "Vacancia TRI"),
        ("assistant", "Respuesta del analista."),
    ]
    assert ALPHA_PRODUCT_VOICE not in json.dumps(
        [message.metadata for message in persisted], ensure_ascii=False
    )

    manifest = build_run_manifest("offline", "0" * 40, "2026-08-19T00:00:00Z")
    assert manifest["system_prompt_sha256"] == "b155ded6464def5a8cf7ba8d4e9c56af8dc3b402cf0227b5f9f097ab96e17f44"
    assert manifest["tool_schema_sha256"] == "d5623b5fc7f1cbc35d6f75b69403df87bbb326c9995d8e240f6a5e51d1b196ca"
    assert manifest["reserved_synthesis_prompt_sha256"] == "803fabd15e39afda32ca1d2044c5bcb77d9cb1ed7f28a4216c3998a2d06c0496"
