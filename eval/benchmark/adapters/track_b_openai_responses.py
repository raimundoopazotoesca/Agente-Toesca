"""Direct OpenAI Responses API adapter for the B1_STANDARD GPT-5.6 models."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI

from eval.benchmark.adapters.base import ToolCall, Turn, Usage
from eval.benchmark.adapters._transport import ModelRequest, ModelResponse, ToolRequest, ToolSpec, TranscriptItem
from eval.benchmark.adapters.actions import ActionRegistry, RunSqlAction
from eval.benchmark.adapters.analyst_loop import AnalystLoop
from eval.benchmark.adapters.track_b_frontier import (
    MAX_INVESTIGATION_ROUNDS, MAX_ROWS_RETURNED, _RUN_SQL_SPEC, _RUN_SQL_TOOL, _SYNTHESIS_INSTRUCTION,
    _SYSTEM_PROMPT_TEMPLATE, _safe_json_loads,
    _extract_artifacts, _format_tool_result, _schema_summary, _semantic_context, _validate_sql,
)
from eval.benchmark.snapshot import SnapshotSandbox

_RESPONSES_RUN_SQL_TOOL = {
    "type": "function",
    "name": "run_sql",
    "description": _RUN_SQL_TOOL["function"]["description"],
    "parameters": _RUN_SQL_TOOL["function"]["parameters"],
}


def _item_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    return dict(item)


def _visible_text(response: Any, items: list[dict[str, Any]]) -> str:
    if getattr(response, "output_text", None):
        return response.output_text
    parts: list[str] = []
    for item in items:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts)


def _tool_spec_to_responses(spec: ToolSpec) -> dict:
    return {"type": "function", "name": spec.name, "description": spec.description, "parameters": spec.parameters}


@dataclass
class ResponsesTransport:
    """F4 Stage 2D: the OpenAI Responses wire-protocol translation, extracted
    from _OpenAIResponsesSession.ask(). Pure protocol translation -- no round
    budget, no SQL.

    The critical replay requirement (Stage 1's hardest-won constraint): a
    TranscriptItem's `raw` is the *entire* `response.output` item list for
    that round (reasoning items included) and must be replayed verbatim,
    followed by its `function_call_output` entries built from tool_results --
    never reconstructed or filtered. That's exactly what `_render_history`
    does: `request_input.extend(item.raw)` then append outputs, per item, in
    order. Losing or reordering any of it is what breaks Responses' opaque
    reasoning-item validation on the next call.

    `tool_specs` (constructor) is the full, unchanging tool set, declared on
    every call for replay validity -- mirrors ChatCompletionsTransport.
    `request.tools` (per call) drives only tool_choice.
    """

    client: Any
    model: str
    tool_specs: list[ToolSpec]
    request_observer: Callable[[str, int, object | None], None] | None = None
    _round: int = 0

    def _render_history(self, history: list[TranscriptItem]) -> list[dict]:
        request_input: list[dict] = []
        for item in history:
            if item.role == "user":
                request_input.append({"role": "user", "content": item.text or ""})
                continue
            request_input.extend(item.raw or [])
            for tr in item.tool_results:
                request_input.append({"type": "function_call_output", "call_id": tr.call_id, "output": tr.content})
        return request_input

    def complete(self, request: ModelRequest) -> ModelResponse:
        request_input = self._render_history(request.history)
        if request.message:
            request_input.append({"role": "user", "content": request.message})

        tool_choice = "auto" if request.tools else "none"
        if self.request_observer:
            self.request_observer("provider_request_started", self._round, None)
        try:
            response = self.client.responses.create(
                model=self.model, instructions=request.system_prompt, input=request_input,
                tools=[_tool_spec_to_responses(t) for t in self.tool_specs], tool_choice=tool_choice, store=False,
            )
        except Exception as exc:
            if self.request_observer:
                self.request_observer("provider_request_failed", self._round, exc)
            raise
        finally:
            self._round += 1
        if self.request_observer:
            self.request_observer("provider_response_received", self._round - 1, response)

        items = [_item_dict(item) for item in response.output]
        function_calls = [item for item in items if item.get("type") == "function_call"]
        tool_requests = [
            ToolRequest(call_id=fc.get("call_id", ""), name=fc.get("name", ""), arguments=_safe_json_loads(fc.get("arguments")))
            for fc in function_calls
        ]
        text = _visible_text(response, items)
        usage_raw = getattr(response, "usage", None)
        input_details = getattr(usage_raw, "input_tokens_details", None)
        output_details = getattr(usage_raw, "output_tokens_details", None)
        usage = Usage(
            provider="openai", model=self.model, calls=1,
            input_tokens=getattr(usage_raw, "input_tokens", None), output_tokens=getattr(usage_raw, "output_tokens", None),
            reasoning_tokens=getattr(output_details, "reasoning_tokens", None), cached_tokens=getattr(input_details, "cached_tokens", None),
        )
        return ModelResponse(text=text, tool_requests=tool_requests, raw_items=items, usage=usage)


@dataclass
class _OpenAIResponsesSession:
    """F4 Stage 2F compatibility facade: same name, constructor, `ask()`
    signature and `history` shape Stage 1 had -- verified against
    test_track_b_openai_responses.py and test_f4_reserved_synthesis.py, which
    construct this class directly and inspect `.history` as the flat raw
    trajectory (`private in repr(session.history)`). All reasoning-loop logic
    now lives in AnalystLoop.

    Cross-turn retention matches Stage 1 exactly: the FULL raw trajectory
    (every reasoning item, every function_call/function_call_output pair)
    from every turn so far, verified in test_analyst_loop_multiturn_parity.py.
    Achieved by wrapping the prior flat `self.history` in a single opaque
    TranscriptItem (`raw=self.history`) -- AnalystLoop never inspects `raw`,
    so this is exactly the "provider-owned protocol state, replay verbatim"
    case the contract's opacity was designed for, not a special case.
    """

    sandbox: SnapshotSandbox
    session_id: str
    system_prompt: str
    client: Any
    model: str
    request_observer: Callable[[str, int, object | None], None] | None = None
    # Output items, including opaque reasoning, are protocol state only and
    # never escape this in-memory session.
    history: list[dict[str, Any]] = field(default_factory=list)

    def ask(self, message: str) -> Turn:
        self.sandbox.log.reset()
        transport = ResponsesTransport(client=self.client, model=self.model, tool_specs=[_RUN_SQL_SPEC], request_observer=self.request_observer)
        loop = AnalystLoop(
            system_prompt=self.system_prompt, transport=transport,
            action_executor=ActionRegistry([RunSqlAction(sandbox=self.sandbox)]), tool_specs=[_RUN_SQL_SPEC],
        )
        prior_history = [TranscriptItem(role="assistant", raw=self.history)] if self.history else []
        result = loop.ask(message, history=prior_history)

        self.history = transport._render_history(result.round_trajectory)
        result.turn.queries = list(self.sandbox.log.statements)
        result.turn.gate_violations = list(self.sandbox.log.violations)
        return result.turn


class TrackBOpenAIResponses:
    name = "track_b_openai_responses"

    def __init__(self, sandbox: SnapshotSandbox | None = None, provider: dict | None = None, request_observer=None):
        if provider is None:
            raise ValueError("OpenAI provider configuration is required")
        self.sandbox = sandbox or SnapshotSandbox()
        self.provider = provider
        self.client = OpenAI(api_key=provider["api_key"], max_retries=0)
        self.model = provider["model"]
        self.request_observer = request_observer
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(semantic_context=_semantic_context(), schema_summary=_schema_summary(self.sandbox))

    def new_session(self, session_id: str) -> _OpenAIResponsesSession:
        return _OpenAIResponsesSession(self.sandbox, session_id, self._system_prompt, self.client, self.model, self.request_observer)
