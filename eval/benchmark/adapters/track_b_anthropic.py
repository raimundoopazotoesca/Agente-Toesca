"""Native Anthropic Track B adapter with in-memory tool-replay state only."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic

from eval.benchmark.adapters.base import ToolCall, Turn, Usage
from eval.benchmark.adapters.track_b_frontier import (
    MAX_ROWS_RETURNED, MAX_TOOL_ITERATIONS, _RUN_SQL_TOOL, _SYSTEM_PROMPT_TEMPLATE,
    _extract_artifacts, _format_tool_result, _schema_summary, _semantic_context, _validate_sql,
)
from eval.benchmark.snapshot import SnapshotSandbox

_ANTHROPIC_RUN_SQL_TOOL = {"name": "run_sql", "description": _RUN_SQL_TOOL["function"]["description"], "input_schema": _RUN_SQL_TOOL["function"]["parameters"]}


def _block_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


@dataclass
class _AnthropicSession:
    sandbox: SnapshotSandbox
    session_id: str
    system_prompt: str
    client: Any
    model: str
    request_observer: Callable[[str, int, object | None], None] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def _run_tool(self, query: str) -> tuple[str, bool]:
        error = _validate_sql(query)
        if error:
            return json.dumps({"error": error}, ensure_ascii=False), False
        sql = query.strip().rstrip(";")
        if not re.search(r"\blimit\b\s+\d+", sql, re.IGNORECASE):
            sql = f"{sql} LIMIT {MAX_ROWS_RETURNED}"
        conn = self.sandbox.connect(guard=True)
        try:
            cur = conn.execute(sql)
            columns = [d[0] for d in cur.description or []]
            rows = [list(row) for row in cur.fetchmany(MAX_ROWS_RETURNED)]
            return _format_tool_result(columns, rows), True
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)}, ensure_ascii=False), False
        finally:
            conn.close()

    def ask(self, message: str) -> Turn:
        self.sandbox.log.reset()
        started = time.monotonic()
        messages: list[dict[str, Any]] = [*self.history, {"role": "user", "content": message}]
        tool_calls_log: list[ToolCall] = []
        final_text, api_calls, response = "", 0, None
        for model_round in range(MAX_TOOL_ITERATIONS):
            call_started = time.monotonic()
            if self.request_observer: self.request_observer("provider_request_started", model_round, None)
            try:
                # Anthropic requires max_tokens at the transport layer. This is
                # not a thinking budget; no thinking or sampling override is sent.
                response = self.client.messages.create(model=self.model, max_tokens=4096, system=self.system_prompt,
                                                       messages=messages, tools=[_ANTHROPIC_RUN_SQL_TOOL])
            except Exception as exc:
                if self.request_observer: self.request_observer("provider_request_failed", model_round, exc)
                raise
            if self.request_observer: self.request_observer("provider_response_received", model_round, response)
            api_calls += 1
            content = [_block_dict(block) for block in response.content]
            tool_blocks = [block for block in content if block.get("type") == "tool_use"]
            if not tool_blocks:
                final_text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
                break
            # Opaque thinking/signature blocks remain intact only in this in-memory replay trajectory.
            messages.append({"role": "assistant", "content": content})
            tool_results = []
            for block in tool_blocks:
                args = block.get("input") or {}
                query = args.get("query", "") if block.get("name") == "run_sql" else ""
                result_text, ok = self._run_tool(query)
                tool_calls_log.append(ToolCall(name="run_sql", args={"query": query}, ok=ok,
                                              duration_ms=(time.monotonic() - call_started) * 1000))
                tool_results.append({"type": "tool_result", "tool_use_id": block.get("id", ""), "content": result_text})
            messages.append({"role": "user", "content": tool_results})
        else:
            final_text = "(no se alcanzo una respuesta final dentro del limite de iteraciones de herramientas)"
        elapsed_ms = (time.monotonic() - started) * 1000
        self.history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": final_text}])
        usage = getattr(response, "usage", None)
        return Turn(text=final_text, artifacts=_extract_artifacts(final_text), tool_calls=tool_calls_log,
                    usage=Usage(provider="anthropic", model=self.model, calls=api_calls, latency_ms=elapsed_ms,
                                input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
                                reasoning_tokens=getattr(usage, "thinking_tokens", None), cached_tokens=getattr(usage, "cache_read_input_tokens", None)),
                    queries=list(self.sandbox.log.statements), gate_violations=list(self.sandbox.log.violations), raw={"final_text": final_text})


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
