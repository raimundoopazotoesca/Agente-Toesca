"""Interactive analyst sessions built from the provider-neutral F4 runtime.

The OpenAI client is created only when a real session is requested.  This
keeps imports and ordinary workspace operations offline and testable.
"""
from __future__ import annotations

import json
import os
from hashlib import sha256
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from tools.analyst_runtime.actions import (
    ActionRegistry, AnalyticsBreakdownAssetAction, AnalyticsLookupAssetAction,
    AnalyticsLookupFundAction, RunSqlAction, SchemaSearchAction,
    ResolveEntityAction,
)
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.base import ToolCall, Usage
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.presentation import FinalPresenter, OpenAIResponsesFinalPresenter, PresentationResult
from tools.analyst_runtime.transport import ModelRequest, ModelResponse, ToolRequest, ToolResult, ToolSpec, TranscriptItem

INTERACTIVE_EVIDENCE_INSTRUCTION = """Responde en español, distingue datos verificados de inferencias y usa la
herramienta SQL sólo para consultas de lectura cuando necesites evidencia."""

ALPHA_EVIDENCE_INSTRUCTION = """Responde en español. Distingue internamente entre evidencia, inferencias,
hipótesis y supuestos para decidir qué puedes afirmar. Usa la herramienta SQL
sólo para consultas de lectura cuando necesites evidencia. No conviertas esas
categorías en etiquetas visibles para el usuario; si una limitación o
incertidumbre es material para interpretar la respuesta, explícala de forma
natural dentro de la respuesta.

Antes de concluir, verifica que la evidencia alcance para el deliverable exacto,
no sólo para una observación prudente. Si la conclusión requiere relación entre
entidades, comparación, contribución relativa o cambio en el tiempo, reúne una
base comparable suficiente cuando una consulta de lectura razonable pueda cambiar
materialmente la respuesta. Si no puede obtenerse, explica naturalmente el
alcance de lo observado."""

DEFAULT_INTERACTIVE_SYSTEM_PROMPT = (
    "Eres el Asistente Inmobiliario Toesca.\n"
    f"{INTERACTIVE_EVIDENCE_INSTRUCTION}"
)

ALPHA_PRODUCT_VOICE = """\
Comunica como un analista inmobiliario competente que trabaja junto al equipo
de Toesca: natural, directo, profesional y preciso. Responde primero lo que
importa; profundiza sólo cuando agrega valor. Señala hallazgos y criterio
analítico cuando estén respaldados por la evidencia, y expresa la incertidumbre
de forma natural cuando no alcance para concluir.

La trazabilidad, verificación y procedencia son responsabilidades internas:
no las expongas rutinariamente. En respuestas simples, no agregues definiciones
del KPI, metodología, fuente, consultas, códigos de período ni advertencias
operativas salvo que el usuario las pida o sean materiales para interpretar el
resultado. Una respuesta completa no tiene que ser larga: si una frase resuelve
la pregunta, una frase es suficiente.

Las categorías epistemológicas sirven para razonar, no para organizar visualmente
la respuesta. No uses por defecto encabezados, etiquetas ni prefijos como dato
verificado, inferencia, hipótesis, supuesto o evidencia. Expresa hechos,
interpretaciones y limitaciones con lenguaje natural integrado en la respuesta.

Modela esa presentación así: ante una pregunta simple, responde "La vacancia fue
**5,9%**." y termina. Ante una pregunta analítica, responde "Lo más relevante es
la concentración de la vacancia en pocos activos. Esto sugiere que una mejora en
ellos podría mover materialmente el indicador." Si la incertidumbre es material,
di "El dato apunta a una mejora, aunque la cobertura del período es parcial."

Adapta la extensión y la presentación a la pregunta. Usa Markdown sólo cuando
ayude a leer: negritas para cifras o hallazgos clave, tablas para comparaciones
que lo justifiquen, y headings o listas sólo cuando una respuesta más extensa
los necesite. No conviertas respuestas simples en informes, no repitas
metodología o advertencias si no son materiales y no uses HTML, CSS ni estilos
inline. No suenes como un sistema de consultas ni como un chatbot genérico."""


def _alpha_system_prompt(core_prompt: str) -> str:
    """Reformulate Alpha's evidence rule without changing frozen F4 prompts."""
    if core_prompt.count(INTERACTIVE_EVIDENCE_INSTRUCTION) != 1:
        raise ValueError("Alpha prompt expected exactly once the interactive evidence instruction")
    alpha_core_prompt = core_prompt.replace(
        INTERACTIVE_EVIDENCE_INSTRUCTION,
        ALPHA_EVIDENCE_INSTRUCTION,
    )
    return f"{alpha_core_prompt}\n\n{ALPHA_PRODUCT_VOICE}"


@dataclass
class AnalystSessionResult:
    """Safe, provider-neutral result exposed to the workspace layer."""

    text: str
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    sql_queries: list[str] = field(default_factory=list)
    presentation_applied: bool | None = None
    presentation_provider: str | None = None
    presentation_model: str | None = None
    presentation_latency_ms: float | None = None
    presentation_integrity_status: str | None = None
    original_answer_hash: str | None = None
    presented_answer_hash: str | None = None
    termination_reason: str | None = None


class AnalystSession(Protocol):
    def ask(self, text: str) -> AnalystSessionResult: ...


class AnalystSessionFactory(Protocol):
    def create(self, conversation: Any, visible_messages: list[Any], runtime_context: dict[str, Any] | None = None) -> AnalystSession: ...


@dataclass
class OpenAIResponsesTransport:
    """OpenAI Responses translation that preserves opaque history in memory."""

    client: Any
    model: str
    tool_specs: list[ToolSpec]

    def complete(self, request: ModelRequest) -> ModelResponse:
        request_input = self._render_history(request.history)
        if request.message:
            request_input.append({"role": "user", "content": request.message})
        response = self.client.responses.create(
            model=self.model,
            instructions=request.system_prompt,
            input=request_input,
            tools=[_tool_spec_to_responses(spec) for spec in self.tool_specs],
            tool_choice="auto" if request.tools else "none",
            store=False,
        )
        items = [_item_dict(item) for item in response.output]
        usage_raw = getattr(response, "usage", None)
        input_details = getattr(usage_raw, "input_tokens_details", None)
        output_details = getattr(usage_raw, "output_tokens_details", None)
        return ModelResponse(
            text=_visible_text(response, items),
            tool_requests=[
                ToolRequest(call_id=item.get("call_id", ""), name=item.get("name", ""),
                            arguments=_safe_json_loads(item.get("arguments")))
                for item in items if item.get("type") == "function_call"
            ],
            raw_items=items,
            usage=Usage(
                provider="openai", model=self.model, calls=1,
                input_tokens=getattr(usage_raw, "input_tokens", None),
                output_tokens=getattr(usage_raw, "output_tokens", None),
                reasoning_tokens=getattr(output_details, "reasoning_tokens", None),
                cached_tokens=getattr(input_details, "cached_tokens", None),
            ),
        )

    @staticmethod
    def _render_history(history: list[TranscriptItem]) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for item in history:
            if item.role == "user":
                rendered.append({"role": "user", "content": item.text or ""})
            else:
                if item.raw:
                    rendered.extend(item.raw)
                else:
                    # Restart reconstruction has only visible transcript text;
                    # native sessions have opaque provider output in ``raw``.
                    rendered.append({"role": "assistant", "content": item.text or ""})
                rendered.extend(
                    {"type": "function_call_output", "call_id": result.call_id, "output": result.content}
                    for result in item.tool_results
                )
        return rendered


class OpenAIResponsesAnalystSession:
    """Keeps the provider's opaque replay trajectory only in process memory."""

    def __init__(self, loop: AnalystLoop, history: list[TranscriptItem] | None = None, presenter: FinalPresenter | None = None):
        self._loop = loop
        self._history: list[TranscriptItem] = list(history or [])
        self._presenter = presenter

    def ask(self, text: str) -> AnalystSessionResult:
        result = self._loop.ask(text, history=self._history)
        self._history = result.round_trajectory
        turn = result.turn
        termination_reason = turn.raw.get("termination_reason")
        presentation = (_clarification_presentation(turn.text) if termination_reason == "clarification_required"
                        else self._present(turn.text, text))
        return AnalystSessionResult(
            text=presentation.content,
            usage=turn.usage,
            tool_calls=turn.tool_calls,
            sql_queries=[call.args["query"] for call in turn.tool_calls if call.name == "run_sql" and "query" in call.args],
            presentation_applied=presentation.applied,
            presentation_provider=presentation.provider,
            presentation_model=presentation.model,
            presentation_latency_ms=presentation.latency_ms,
            presentation_integrity_status=presentation.integrity_status,
            original_answer_hash=_answer_hash(turn.text),
            presented_answer_hash=_answer_hash(presentation.content),
            termination_reason=termination_reason,
        )

    def _present(self, draft: str, user_message: str) -> PresentationResult:
        if self._presenter is None:
            return PresentationResult(draft, False, None, None, None, "not_configured")
        return self._presenter.present(user_message=user_message, draft_answer=draft)


def _clarification_presentation(content: str) -> PresentationResult:
    return PresentationResult(content, False, None, None, None, "clarification_required")


class OpenAIResponsesAnalystSessionFactory:
    """Build the real local F4 session without any benchmark dependency."""

    def __init__(
        self,
        knowledge_db_path: Path,
        system_prompt: str = DEFAULT_INTERACTIVE_SYSTEM_PROMPT,
        model: str = "gpt-5.6-terra",
        client_factory: Callable[[], Any] | None = None,
        presenter_factory: Callable[[Any, str], FinalPresenter] | None = OpenAIResponsesFinalPresenter,
    ):
        self.knowledge_db_path = Path(knowledge_db_path)
        self.system_prompt = _alpha_system_prompt(system_prompt)
        self.model = model
        self._client_factory = client_factory or _default_openai_client
        self._presenter_factory = presenter_factory

    def create(self, conversation: Any, visible_messages: list[Any], runtime_context: dict[str, Any] | None = None) -> AnalystSession:
        # Visible history is sufficient for restart continuity. Opaque provider
        # replay data is absent after a restart by design and never persisted.
        del conversation, runtime_context
        sandbox = LiveReadOnlySandbox(self.knowledge_db_path)
        action = RunSqlAction(sandbox=sandbox)
        registry = ActionRegistry([
            action,
            ResolveEntityAction(self.knowledge_db_path),
            SchemaSearchAction(self.knowledge_db_path),
            AnalyticsLookupFundAction(self.knowledge_db_path),
            AnalyticsLookupAssetAction(self.knowledge_db_path),
            AnalyticsBreakdownAssetAction(self.knowledge_db_path),
        ])
        client = self._client_factory()
        transport = OpenAIResponsesTransport(client, self.model, registry.tool_specs())
        history = [TranscriptItem(role=message.role, text=message.content) for message in visible_messages]
        presenter = self._presenter_factory(client, self.model) if self._presenter_factory else None
        return OpenAIResponsesAnalystSession(
            AnalystLoop(self.system_prompt, transport, registry, registry.tool_specs()), history=history, presenter=presenter
        )


def _default_openai_client() -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required to create a live analyst session")
    from openai import OpenAI

    return OpenAI(max_retries=0)


def _item_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    return dict(item)


def _visible_text(response: Any, items: list[dict[str, Any]]) -> str:
    if getattr(response, "output_text", None):
        return response.output_text
    return "".join(
        content.get("text", "")
        for item in items if item.get("type") == "message"
        for content in item.get("content") or [] if content.get("type") == "output_text"
    )


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_spec_to_responses(spec: ToolSpec) -> dict[str, Any]:
    return {"type": "function", "name": spec.name, "description": spec.description, "parameters": spec.parameters}


def _answer_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
