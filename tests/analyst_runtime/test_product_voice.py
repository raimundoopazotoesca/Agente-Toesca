"""Alpha product-voice boundary tests (offline; no provider calls)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.round_b.runner import build_run_manifest
from eval.benchmark.adapters.track_b_frontier import _SYSTEM_PROMPT_TEMPLATE
from tools.analyst_runtime.session import (
    ALPHA_EVIDENCE_INSTRUCTION,
    ALPHA_PRODUCT_VOICE,
    DEFAULT_INTERACTIVE_SYSTEM_PROMPT,
    INTERACTIVE_EVIDENCE_INSTRUCTION,
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
    """A toolless turn now always makes a second, no-tools model round asking
    for a structured SynthesisEnvelope (see session.py: routing toolless
    turns through the same coverage_guard binding as any evidence-bearing
    turn). This double emulates a real provider on that second call too --
    when the request asks for the SynthesisEnvelope JSON schema, it returns a
    minimal valid envelope wrapping the SAME plain-text answer in one text
    fragment, instead of the plain prose it returns on an ordinary round."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = kwargs.get("text", {}).get("format", {}).get("name")
        if schema_name == "SynthesisEnvelope":
            output_text = json.dumps({
                "fragments": [{"type": "text", "text": "Respuesta del analista."}],
                "canonical_metric_claims": [], "governed_dataset_claims": [], "derived_metric_claims": [],
            })
        else:
            output_text = "Respuesta del analista."
        return SimpleNamespace(
            output_text=output_text,
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


class _SequencedResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.outputs.pop(0), output=[], usage=None)


class _SequencedClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = _SequencedResponses(outputs)


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
    assert request["input"] == [{"role": "user", "content": "Consulta actual"}]
    assert ALPHA_PRODUCT_VOICE not in json.dumps(request["input"], ensure_ascii=False)


def test_alpha_toolless_turn_with_unbound_quantity_fails_closed(tmp_path):
    """A toolless turn (no new tool call this turn) is NOT exempt from
    fact-integrity guarantees: it now always makes a second, no-tools model
    round asking for a SynthesisEnvelope (see session.py), and that envelope
    is validated by the SAME coverage_guard as any evidence-bearing turn. A
    model that writes a numeric literal into free text instead of binding it
    via a claim_ref must fail closed here exactly as it would for a
    tool-calling turn -- this is the gap this fix closes."""
    draft = "La vacancia de TRI en junio de 2026 fue 5,945%."
    unbound_envelope = json.dumps({
        "fragments": [{"type": "text", "text": draft}],
        "canonical_metric_claims": [], "governed_dataset_claims": [], "derived_metric_claims": [],
    })
    client = _SequencedClient([draft, unbound_envelope])
    factory = OpenAIResponsesAnalystSessionFactory(
        _knowledge_db(tmp_path / "knowledge.db"), client_factory=lambda: client
    )

    result = factory.create(object(), []).ask("¿Cuál es la vacancia?")

    assert result.text != draft
    assert len(client.responses.calls) == 2


def test_alpha_purely_conversational_toolless_turn_stays_usable(tmp_path):
    """A toolless turn with NO quantitative facts at all must remain usable:
    the second (finalize) round is a plain no-tools model call, never a new
    investigation/tool round, so nothing forces a spurious tool call."""
    draft = "Con gusto, cuéntame qué fondo o período te interesa revisar."
    envelope = json.dumps({
        "fragments": [{"type": "text", "text": draft}],
        "canonical_metric_claims": [], "governed_dataset_claims": [], "derived_metric_claims": [],
    })
    client = _SequencedClient([draft, envelope])
    factory = OpenAIResponsesAnalystSessionFactory(
        _knowledge_db(tmp_path / "knowledge.db"), client_factory=lambda: client
    )

    result = factory.create(object(), []).ask("Hola, buenos días")

    assert result.text == draft
    assert result.presentation_applied is False
    assert result.presentation_integrity_status == "not_applicable"
    assert len(client.responses.calls) == 2


def test_alpha_reformulates_the_interactive_evidence_instruction_only():
    """Alpha keeps evidence discipline but makes it internal and user-facing natural."""
    prompt = _alpha_system_prompt(DEFAULT_INTERACTIVE_SYSTEM_PROMPT)
    normalized_prompt = " ".join(prompt.split())

    assert DEFAULT_INTERACTIVE_SYSTEM_PROMPT.count(INTERACTIVE_EVIDENCE_INSTRUCTION) == 1
    assert INTERACTIVE_EVIDENCE_INSTRUCTION not in prompt
    assert ALPHA_EVIDENCE_INSTRUCTION in prompt
    assert ALPHA_PRODUCT_VOICE in prompt
    assert "distingue internamente entre evidencia, inferencias, hip\u00f3tesis y supuestos" in normalized_prompt.lower()
    assert "no conviertas esas categor\u00edas en etiquetas visibles" in normalized_prompt.lower()


def test_alpha_adds_deliverable_sufficiency_before_product_voice_only():
    prompt = _alpha_system_prompt(DEFAULT_INTERACTIVE_SYSTEM_PROMPT)
    sufficiency = "verifica que la evidencia alcance para el deliverable exacto"

    assert sufficiency in prompt.lower()
    assert prompt.index(ALPHA_EVIDENCE_INSTRUCTION) < prompt.index(ALPHA_PRODUCT_VOICE)
    assert _SYSTEM_PROMPT_TEMPLATE.find(sufficiency) == -1


def test_alpha_voice_teaches_natural_evidence_presentation_with_examples():
    """Examples teach Alpha's presentation format without changing F4 evidence policy."""
    normalized_voice = " ".join(ALPHA_PRODUCT_VOICE.split())

    assert "Las categor\u00edas epistemol\u00f3gicas sirven para razonar" in normalized_voice
    assert '"La vacancia fue **5,9%**."' in normalized_voice
    assert '"Lo m\u00e1s relevante es la concentraci\u00f3n de la vacancia en pocos activos.' in normalized_voice
    assert "Esto sugiere que una mejora en ellos podr\u00eda mover materialmente el indicador." in normalized_voice
    assert '"El dato apunta a una mejora, aunque la cobertura del per\u00edodo es parcial."' in normalized_voice
    assert '"La vacancia fue **5,9%**."' not in _SYSTEM_PROMPT_TEMPLATE


def test_alpha_prompt_builder_fails_fast_when_interactive_evidence_instruction_changes():
    with pytest.raises(ValueError, match="exactly once"):
        _alpha_system_prompt("Eres el Asistente Inmobiliario Toesca.")


def test_benchmark_core_keeps_its_frozen_evidence_instruction():
    assert "Distingue hechos (lo que arrojan las consultas) de tu interpretacion" in _SYSTEM_PROMPT_TEMPLATE
    assert ALPHA_EVIDENCE_INSTRUCTION not in _SYSTEM_PROMPT_TEMPLATE
    assert ALPHA_PRODUCT_VOICE not in _SYSTEM_PROMPT_TEMPLATE


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
    assistant_metadata = persisted[-1].metadata
    assert assistant_metadata["presentation_applied"] is False
    assert assistant_metadata["presentation_integrity_status"] == "not_applicable"
    assert len(assistant_metadata["original_answer_hash"]) == 64
    assert "draft" not in json.dumps(assistant_metadata, ensure_ascii=False).lower()
    assert "raw_response" not in assistant_metadata

    manifest = build_run_manifest("offline", "0" * 40, "2026-08-19T00:00:00Z")
    # Catalog-derived capability affordances changed; the static prompt and
    # tool schema hashes below remain the compatibility boundary.
    assert manifest["system_prompt_sha256"] == "b4c6dab114ca78fbff88226cb02c380501fc5dfc9f13778e43bdf8d8b5e0c0b1"
    assert manifest["tool_schema_sha256"] == "d5623b5fc7f1cbc35d6f75b69403df87bbb326c9995d8e240f6a5e51d1b196ca"
    assert manifest["reserved_synthesis_prompt_sha256"] == "803fabd15e39afda32ca1d2044c5bcb77d9cb1ed7f28a4216c3998a2d06c0496"
