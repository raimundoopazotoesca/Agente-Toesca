"""Native Anthropic Track B adapter with in-memory tool-replay state only."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic

from eval.benchmark.adapters.base import ToolCall, Turn, Usage
from eval.benchmark.adapters._transport import ModelRequest, ModelResponse, ToolRequest, ToolSpec, TranscriptItem
from eval.benchmark.adapters.analyst_loop import AnalystLoop
from eval.benchmark.adapters.track_b_frontier import (
    MAX_INVESTIGATION_ROUNDS, MAX_ROWS_RETURNED, _RUN_SQL_SPEC, _RUN_SQL_TOOL, _SYNTHESIS_INSTRUCTION,
    _SYSTEM_PROMPT_TEMPLATE,
    _extract_artifacts, _format_tool_result, _schema_summary, _semantic_context, _validate_sql,
    LegacySqlActionExecutor,
)
from eval.benchmark.snapshot import SnapshotSandbox

_ANTHROPIC_RUN_SQL_TOOL = {"name": "run_sql", "description": _RUN_SQL_TOOL["function"]["description"], "input_schema": _RUN_SQL_TOOL["function"]["parameters"]}


def _block_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


def _tool_spec_to_anthropic(spec: ToolSpec) -> dict:
    return {"name": spec.name, "description": spec.description, "input_schema": spec.parameters}


@dataclass
class AnthropicTransport:
    """F4 Stage 2E: the Anthropic Messages wire-protocol translation,
    extracted from _AnthropicSession.ask(). Pure protocol translation -- no
    round budget, no SQL.

    Two Anthropic-specific quirks live here, not in AnalystLoop, because both
    are about what THIS protocol needs, not about reasoning policy:
      - a TranscriptItem's `raw` is the assistant turn's full content-block
        list (thinking/signature blocks included), replayed verbatim as that
        message's `content` -- never reconstructed;
      - roles must alternate. `request.message` (the original question, or
        the synthesis instruction) is appended as a NEW user message only
        when the last rendered message isn't already a list-content user
        message (a tool_result turn); otherwise it's merged into that
        message's content list as an extra text block. This is exactly what
        Stage 1's _AnthropicSession did for the synthesis instruction
        specifically -- generalized here to the one rule that also correctly
        handles the very first question (history is empty, so it always
        appends fresh).
    """

    client: Any
    model: str
    tool_specs: list[ToolSpec]
    max_tokens: int = 4096  # Anthropic requires this at the transport layer; not a thinking budget, no sampling override sent.
    request_observer: Callable[[str, int, object | None], None] | None = None
    _round: int = 0

    def _render_history(self, history: list[TranscriptItem]) -> list[dict]:
        messages: list[dict] = []
        for item in history:
            if item.role == "user":
                messages.append({"role": "user", "content": item.text or ""})
                continue
            # Within one turn, an assistant item always carries `raw` (the real
            # content-block list, thinking/tool_use included). Across turns,
            # Stage 1's cross-session history is a plain-text summary (see
            # _AnthropicSession's compat facade) -- `raw is None` there, and
            # content must be the string Anthropic expects for that shape, not
            # a block list.
            messages.append({"role": "assistant", "content": item.raw if item.raw is not None else (item.text or "")})
            if item.tool_results:
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": tr.call_id, "content": tr.content} for tr in item.tool_results
                ]})
        return messages

    def complete(self, request: ModelRequest) -> ModelResponse:
        messages = self._render_history(request.history)
        if request.message:
            if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
                messages[-1]["content"] = [*messages[-1]["content"], {"type": "text", "text": request.message}]
            else:
                messages.append({"role": "user", "content": request.message})

        kwargs = {} if request.tools else {"tool_choice": {"type": "none"}}
        if self.request_observer:
            self.request_observer("provider_request_started", self._round, None)
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=request.system_prompt,
                messages=messages, tools=[_tool_spec_to_anthropic(t) for t in self.tool_specs], **kwargs,
            )
        except Exception as exc:
            if self.request_observer:
                self.request_observer("provider_request_failed", self._round, exc)
            raise
        finally:
            self._round += 1
        if self.request_observer:
            self.request_observer("provider_response_received", self._round - 1, response)

        content = [_block_dict(block) for block in response.content]
        tool_blocks = [block for block in content if block.get("type") == "tool_use"]
        tool_requests = [
            ToolRequest(call_id=block.get("id", ""), name=block.get("name", ""), arguments=block.get("input") or {})
            for block in tool_blocks
        ]
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        usage_raw = getattr(response, "usage", None)
        usage = Usage(
            provider="anthropic", model=self.model, calls=1,
            input_tokens=getattr(usage_raw, "input_tokens", None), output_tokens=getattr(usage_raw, "output_tokens", None),
            reasoning_tokens=getattr(usage_raw, "thinking_tokens", None), cached_tokens=getattr(usage_raw, "cache_read_input_tokens", None),
        )
        return ModelResponse(text=text, tool_requests=tool_requests, raw_items=content, usage=usage)


@dataclass
class _AnthropicSession:
    """F4 Stage 2F compatibility facade: same name, constructor, `ask()`
    signature and `history` shape Stage 1 had -- verified against
    test_track_b_native_providers.py and test_f4_reserved_synthesis.py, which
    construct this class directly and inspect `.history` as `list[dict]`
    with plain-text assistant entries. All reasoning-loop logic now lives in
    AnalystLoop.

    Cross-turn retention matches Stage 1 exactly: only [question, final_text]
    per turn (plain text, never content blocks -- thinking/tool_use blocks
    from a finished turn are never replayed into a later one), verified in
    test_analyst_loop_multiturn_parity.py.
    """

    sandbox: SnapshotSandbox
    session_id: str
    system_prompt: str
    client: Any
    model: str
    request_observer: Callable[[str, int, object | None], None] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def ask(self, message: str) -> Turn:
        self.sandbox.log.reset()
        loop = AnalystLoop(
            system_prompt=self.system_prompt,
            transport=AnthropicTransport(client=self.client, model=self.model, tool_specs=[_RUN_SQL_SPEC], request_observer=self.request_observer),
            action_executor=LegacySqlActionExecutor(sandbox=self.sandbox),
            tool_specs=[_RUN_SQL_SPEC],
        )
        prior_history = [TranscriptItem(role=m["role"], text=m["content"]) for m in self.history]
        result = loop.ask(message, history=prior_history)

        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": result.turn.text})

        result.turn.queries = list(self.sandbox.log.statements)
        result.turn.gate_violations = list(self.sandbox.log.violations)
        return result.turn


class TrackBAnthropic:
    name = "track_b_anthropic"

    def __init__(self, sandbox: SnapshotSandbox | None = None, provider: dict | None = None, request_observer=None):
        if provider is None:
            raise ValueError("Anthropic provider configuration is required")
        self.sandbox = sandbox or SnapshotSandbox()
        self.provider = provider
        self.client = Anthropic(api_key=provider["api_key"], max_retries=0)
        self.model = provider["model"]
        self.request_observer = request_observer
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(semantic_context=_semantic_context(), schema_summary=_schema_summary(self.sandbox))

    def new_session(self, session_id: str) -> _AnthropicSession:
        return _AnthropicSession(self.sandbox, session_id, self._system_prompt, self.client, self.model, self.request_observer)
