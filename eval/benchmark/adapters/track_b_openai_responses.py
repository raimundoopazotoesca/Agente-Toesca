"""Direct OpenAI Responses API adapter for the B1_STANDARD GPT-5.6 models."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI

from eval.benchmark.adapters.base import ToolCall, Turn, Usage
from eval.benchmark.adapters.track_b_frontier import (
    MAX_ROWS_RETURNED, MAX_TOOL_ITERATIONS, _RUN_SQL_TOOL, _SYSTEM_PROMPT_TEMPLATE,
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


@dataclass
class _OpenAIResponsesSession:
    sandbox: SnapshotSandbox
    session_id: str
    system_prompt: str
    client: Any
    model: str
    request_observer: Callable[[str, int, object | None], None] | None = None
    # Output items, including opaque reasoning, are protocol state only and
    # never escape this in-memory session.
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
        except Exception as exc:  # noqa: BLE001 -- returned to the model as tool output
            return json.dumps({"error": str(exc)}, ensure_ascii=False), False
        finally:
            conn.close()

    def ask(self, message: str) -> Turn:
        self.sandbox.log.reset()
        started = time.monotonic()
        request_input: list[dict[str, Any]] = [*self.history, {"role": "user", "content": message}]
        tool_calls_log: list[ToolCall] = []
        final_text, api_calls, response, final_items = "", 0, None, []

        for model_round in range(MAX_TOOL_ITERATIONS):
            call_started = time.monotonic()
            if self.request_observer:
                self.request_observer("provider_request_started", model_round, None)
            try:
                response = self.client.responses.create(
                    model=self.model, instructions=self.system_prompt, input=request_input,
                    tools=[_RESPONSES_RUN_SQL_TOOL], tool_choice="auto", store=False,
                )
            except Exception as exc:
                if self.request_observer:
                    self.request_observer("provider_request_failed", model_round, exc)
                raise
            if self.request_observer:
                self.request_observer("provider_response_received", model_round, response)
            api_calls += 1
            items = [_item_dict(item) for item in response.output]
            function_calls = [item for item in items if item.get("type") == "function_call"]
            if not function_calls:
                final_items = items
                final_text = _visible_text(response, items)
                break

            # Responses tool replay requires the original output items (which
            # may include opaque reasoning) plus the matching call_id outputs.
            request_input.extend(items)
            for item in function_calls:
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                query = args.get("query", "") if item.get("name") == "run_sql" else ""
                result_text, ok = self._run_tool(query)
                tool_calls_log.append(ToolCall(name="run_sql", args={"query": query}, ok=ok,
                                              duration_ms=(time.monotonic() - call_started) * 1000))
                request_input.append({"type": "function_call_output", "call_id": item.get("call_id", ""), "output": result_text})
        else:
            final_text = "(no se alcanzo una respuesta final dentro del limite de iteraciones de herramientas)"

        # Keep the complete provider-required trajectory only in memory for TCE.
        self.history = [*request_input, *final_items]
        elapsed_ms = (time.monotonic() - started) * 1000
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        return Turn(
            text=final_text, artifacts=_extract_artifacts(final_text), tool_calls=tool_calls_log,
            usage=Usage(provider="openai", model=self.model, calls=api_calls, latency_ms=elapsed_ms,
                        input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
                        reasoning_tokens=getattr(output_details, "reasoning_tokens", None), cached_tokens=getattr(input_details, "cached_tokens", None)),
            queries=list(self.sandbox.log.statements), gate_violations=list(self.sandbox.log.violations), raw={"final_text": final_text},
        )


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
