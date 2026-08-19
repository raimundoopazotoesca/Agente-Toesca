"""Interactive analyst sessions built from the provider-neutral F4 runtime.

The OpenAI client is created only when a real session is requested.  This
keeps imports and ordinary workspace operations offline and testable.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from tools.analyst_runtime.actions import ActionRegistry, RunSqlAction
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.base import ToolCall, Usage
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.transport import ModelRequest, ModelResponse, ToolRequest, ToolResult, ToolSpec, TranscriptItem

DEFAULT_INTERACTIVE_SYSTEM_PROMPT = """Eres el Asistente Inmobiliario Toesca.
Responde en español, distingue datos verificados de inferencias y usa la
herramienta SQL sólo para consultas de lectura cuando necesites evidencia."""


@dataclass
class AnalystSessionResult:
    """Safe, provider-neutral result exposed to the workspace layer."""

    text: str
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    sql_queries: list[str] = field(default_factory=list)


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

    def __init__(self, loop: AnalystLoop, history: list[TranscriptItem] | None = None):
        self._loop = loop
        self._history: list[TranscriptItem] = list(history or [])

    def ask(self, text: str) -> AnalystSessionResult:
        result = self._loop.ask(text, history=self._history)
        self._history = result.round_trajectory
        turn = result.turn
        return AnalystSessionResult(
            text=turn.text,
            usage=turn.usage,
            tool_calls=turn.tool_calls,
            sql_queries=[call.args["query"] for call in turn.tool_calls if call.name == "run_sql" and "query" in call.args],
        )


class OpenAIResponsesAnalystSessionFactory:
    """Build the real local F4 session without any benchmark dependency."""

    def __init__(
        self,
        knowledge_db_path: Path,
        system_prompt: str = DEFAULT_INTERACTIVE_SYSTEM_PROMPT,
        model: str = "gpt-5.6-terra",
        client_factory: Callable[[], Any] | None = None,
    ):
        self.knowledge_db_path = Path(knowledge_db_path)
        self.system_prompt = system_prompt
        self.model = model
        self._client_factory = client_factory or _default_openai_client

    def create(self, conversation: Any, visible_messages: list[Any], runtime_context: dict[str, Any] | None = None) -> AnalystSession:
        # Visible history is sufficient for restart continuity. Opaque provider
        # replay data is absent after a restart by design and never persisted.
        del conversation, runtime_context
        sandbox = LiveReadOnlySandbox(self.knowledge_db_path)
        action = RunSqlAction(sandbox=sandbox)
        registry = ActionRegistry([action])
        transport = OpenAIResponsesTransport(self._client_factory(), self.model, registry.tool_specs())
        history = [TranscriptItem(role=message.role, text=message.content) for message in visible_messages]
        return OpenAIResponsesAnalystSession(
            AnalystLoop(self.system_prompt, transport, registry, registry.tool_specs()), history=history
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
