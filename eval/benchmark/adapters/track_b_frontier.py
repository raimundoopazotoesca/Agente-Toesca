"""Track B: Frontier Simple.

The counter-architecture to Track A. Deliberately minimal: a competent
model gets the user's message, recent history, the project's own semantic
catalog as plain-text context, and one read-only SQL tool. It iterates
tool calls itself and decides when to stop. Nothing else.

Explicitly NOT reimplemented here (this is the point of the experiment,
not an oversight):
  - intent extraction / closed intent taxonomy
  - StateDelta / candidate extraction / adjudication / reconciliation
  - mandatory metric routing
  - tools.analyst.conversation_state or any other Phase 3 state machinery

What IS kept, because the design doc requires every track to honor it,
not because it's architecture-specific:
  - semantic/business definitions, given to the model as context text
    (read directly from semantic/*.yaml -- the same files Track A's
    semantic_loader reads, but Track B does not import that loader; it
    reads the YAML itself, independently, to stay decoupled from Track A's
    machinery)
  - the pinned snapshot's read-only DB sandbox (SnapshotSandbox), gate F4
    enforcement, and query capture -- Track B calls sandbox.connect()
    directly per tool call, so `queries`/`gate_violations` on the returned
    Turn come from the same sandbox trace as Track A's, not from
    self-reporting
  - session isolation -- trivial here: each Session owns its own message
    history in-process, there is no shared state module to leak across
    sessions in the first place
  - the neutral BenchmarkAdapter/Session/Turn contract from adapters/base.py

Loop: question -> model (+ tools) -> [tool call -> result -> model]* ->
final answer. Capped at MAX_INVESTIGATION_ROUNDS so a confused model can't
loop forever inside a benchmark run; if that cap is reached without a final
answer, the reserved synthesis round (tools disabled) produces one instead of
returning a placeholder. See the round-budget constants below.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from openai import OpenAI

from eval.benchmark.adapters.base import Artifact, ToolCall, Turn, Usage
from eval.benchmark.adapters.actions import ActionRegistry, RunSqlAction, format_query_result, validate_sql
from eval.benchmark.adapters._transport import (
    ModelRequest,
    ModelResponse,
    ToolRequest,
    ToolResult,
    ToolSpec,
    TranscriptItem,
)
from eval.benchmark.snapshot import SnapshotSandbox

SEMANTIC_DIR = Path(__file__).resolve().parents[3] / "semantic"

# Round budget and synthesis instruction now live in analyst_loop.py (F4 Stage
# 2) -- reasoning-loop structure, not Chat-Completions wire protocol. Content
# unchanged byte-for-byte (verified); re-exported under their original names
# so every existing import of them from this module keeps working unchanged.
from eval.benchmark.adapters.analyst_loop import (  # noqa: E402
    MAX_INVESTIGATION_ROUNDS,
    MAX_TOTAL_MODEL_ROUNDS,
    RESERVED_SYNTHESIS_ROUNDS,
    _SYNTHESIS_INSTRUCTION,
    AnalystLoop,
)

MAX_ROWS_RETURNED = 50
_CHART_BLOCK = re.compile(r"```chart\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class InferenceProfile:
    provider: str
    model: str
    version: str
    reasoning_effort: str | None = None

    def request_kwargs(self) -> dict[str, str]:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}


B1_STANDARD_PROFILES = (
    InferenceProfile("groq", "openai/gpt-oss-120b", "B1_STANDARD", "medium"),
    InferenceProfile("fireworks", "accounts/fireworks/models/gpt-oss-120b", "B1_STANDARD", "medium"),
    InferenceProfile("fireworks", "accounts/fireworks/models/glm-5p2", "B1_STANDARD"),
    InferenceProfile("nvidia", "z-ai/glm-5.2", "B1_STANDARD"),
    InferenceProfile("dashscope", "qwen3.8-max", "B1_STANDARD"),
    InferenceProfile("mistral", "mistral-large-2512", "B1_STANDARD"),
    InferenceProfile("sambanova", "MiniMax-M2.7", "B1_STANDARD"),
    InferenceProfile("openai", "gpt-5.6-terra", "B1_STANDARD"),
    InferenceProfile("openai", "gpt-5.6-sol", "B1_STANDARD"),
    InferenceProfile("anthropic", "claude-sonnet-5", "B1_STANDARD"),
    InferenceProfile("anthropic", "claude-opus-5", "B1_STANDARD"),
)


def resolve_b1_standard_profile(provider: str, model: str) -> InferenceProfile:
    for profile in B1_STANDARD_PROFILES:
        if profile.provider == provider and profile.model == model:
            return profile
    raise ValueError(f"no B1_STANDARD profile for {provider}/{model}")

# Tables Track B's model is not meant to query directly: bookkeeping, not
# business data. Keeping the schema summary focused on business tables is
# about context budget, not a security boundary -- the sandbox authorizer
# (gate F4) is what actually enforces read-only/in-scope access regardless
# of what's listed here.
_SCHEMA_EXCLUDE = {"sqlite_sequence", "schema_version", "ingest_run"}

_FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace)\b",
    re.IGNORECASE,
)

_RUN_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": (
            "Run one read-only SELECT statement against the Toesca real-estate "
            "database (pinned snapshot) and get back columns + rows. Use it as "
            "many times as needed before answering -- one query per call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A single SELECT (or WITH ... SELECT) statement. No semicolons, no writes.",
                }
            },
            "required": ["query"],
        },
    },
}

# Provider-neutral ToolSpec built once from _RUN_SQL_TOOL, shared by the three
# compatibility facades (this module's _TrackBSession and the ones in
# track_b_openai_responses.py / track_b_anthropic.py) -- each transport
# re-serializes it to its own wire shape.
_RUN_SQL_SPEC = ToolSpec(name=_RUN_SQL_TOOL["function"]["name"], description=_RUN_SQL_TOOL["function"]["description"], parameters=_RUN_SQL_TOOL["function"]["parameters"])

_SYSTEM_PROMPT_TEMPLATE = """\
Eres un analista inmobiliario senior con acceso de solo lectura a la base de datos \
de Toesca Asset Management (fondos TRI, PT, Apo y sus activos).

Reglas:
- Usa la herramienta run_sql para consultar la base de datos las veces que necesites \
antes de responder. No inventes numeros: todo dato cuantitativo en tu respuesta final \
debe provenir de una consulta que realmente ejecutaste.
- Si una pregunta requiere varias consultas (comparar activos, investigar una \
tendencia, diagnosticar una caida), hazlas en pasos sucesivos en vez de intentar \
resolver todo en una sola query.
- Si los datos no alcanzan para responder con certeza, dilo explicitamente en vez \
de rellenar con una suposicion.
- Distingue hechos (lo que arrojan las consultas) de tu interpretacion (por que crees \
que pasa algo). No afirmes causalidad que no puedas respaldar con una consulta.
- Responde en español, en Markdown, de forma clara y directa.

CATALOGO SEMANTICO (fondos, activos, alias, metricas definidas):
{semantic_context}

ESQUEMA DE BASE DE DATOS DISPONIBLE (tabla: columnas):
{schema_summary}
"""


@lru_cache(maxsize=1)
def _semantic_context() -> str:
    """Plain-text rendering of semantic/*.yaml -- the project's own business
    catalog, read independently of tools.analyst.semantic_loader so Track B
    has zero import-time coupling to Track A's machinery."""
    parts = []
    for name in ("domains.yaml", "entities.yaml", "relationships.yaml", "synonyms.yaml"):
        path = SEMANTIC_DIR / name
        if path.exists():
            parts.append(f"--- {name} ---\n{path.read_text(encoding='utf-8')}")
    metrics_dir = SEMANTIC_DIR / "metrics"
    if metrics_dir.exists():
        for metric_file in sorted(metrics_dir.glob("*.yaml")):
            parts.append(f"--- metrics/{metric_file.name} ---\n{metric_file.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _schema_summary(sandbox: SnapshotSandbox) -> str:
    """Compact 'table: col1, col2, ...' listing, built with a trusted
    (unguarded) connection -- this is adapter setup, reading catalog
    metadata, not answering a benchmark question."""
    conn = sandbox.connect(guard=False)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
            ).fetchall()
            if r[0] not in _SCHEMA_EXCLUDE
        ]
        lines = []
        for table in tables:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
            lines.append(f"{table}: {', '.join(cols)}")
        return "\n".join(lines)
    finally:
        conn.close()


# F4 Stage 3: SQL validation/formatting now live canonically in actions.py
# (RunSqlAction's own concern, not this transport's), re-exported here under
# their original names -- test_track_b.py imports and tests `_validate_sql`
# directly, so the name stays importable from this module. Content unchanged
# (same function, not a reimplementation): verified by test_actions.py's
# parity suite before LegacySqlActionExecutor, which used to define these
# locally, was deleted.
_validate_sql = validate_sql
_format_tool_result = format_query_result


def _extract_artifacts(text: str) -> list[Artifact]:
    return [Artifact(kind="chart", payload=m.group(1).strip()) for m in _CHART_BLOCK.finditer(text or "")]


def _tool_spec_to_openai(spec: ToolSpec) -> dict:
    return {"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}}


@dataclass
class ChatCompletionsTransport:
    """F4 Stage 2: the OpenAI Chat Completions wire-protocol translation,
    extracted from _TrackBSession.ask() (Stage 1) so AnalystLoop can drive it
    without knowing anything about tool_calls/tool_call_id or message shapes.

    Pure protocol translation -- no round budget, no investigation/synthesis
    policy, no SQL. `tool_specs` (constructor) is the FULL, unchanging set of
    tools this session may ever use, declared on every call for replay
    validity (a provider must see the same schema that produced any tool_calls
    already in history) -- exactly what the module constant `_RUN_SQL_TOOL`
    already did implicitly in Stage 1. `request.tools` (per call) is used only
    to pick `tool_choice`: non-empty -> "auto" (investigation), empty ->
    "none" (the reserved synthesis round must not be able to call anything,
    regardless of what the model asks for -- see AnalystLoop for the second,
    structural half of that guarantee: it never reads tool_requests back on a
    tools=[] response).
    """

    client: OpenAI
    model: str
    tool_specs: list[ToolSpec]
    inference_profile: InferenceProfile | None = None
    request_observer: Callable[[str, int, object | None], None] | None = None
    _round: int = 0

    def _render_history(self, history: list[TranscriptItem]) -> list[dict]:
        messages: list[dict] = []
        for item in history:
            if item.role == "user":
                messages.append({"role": "user", "content": item.text or ""})
                continue
            assistant_message = {"role": "assistant", "content": item.text or ""}
            if item.tool_requests:
                assistant_message["tool_calls"] = [
                    {"id": tr.call_id, "type": "function", "function": {"name": tr.name, "arguments": json.dumps(tr.arguments, ensure_ascii=False)}}
                    for tr in item.tool_requests
                ]
            if isinstance(item.raw, dict) and item.raw.get("reasoning_content"):
                assistant_message["reasoning_content"] = item.raw["reasoning_content"]
            messages.append(assistant_message)
            for tr in item.tool_results:
                messages.append({"role": "tool", "tool_call_id": tr.call_id, "content": tr.content})
        return messages

    def complete(self, request: ModelRequest) -> ModelResponse:
        messages = [{"role": "system", "content": request.system_prompt}, *self._render_history(request.history)]
        if request.message:
            messages.append({"role": "user", "content": request.message})

        tool_choice = "auto" if request.tools else "none"
        kwargs = self.inference_profile.request_kwargs() if self.inference_profile else {"temperature": 0.0}
        if self.request_observer:
            self.request_observer("provider_request_started", self._round, None)
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=[_tool_spec_to_openai(t) for t in self.tool_specs], tool_choice=tool_choice, **kwargs,
            )
        except Exception as exc:
            if self.request_observer:
                self.request_observer("provider_request_failed", self._round, exc)
            raise
        finally:
            self._round += 1
        if self.request_observer:
            self.request_observer("provider_response_received", self._round - 1, resp)

        msg = resp.choices[0].message
        tool_requests = [
            ToolRequest(call_id=tc.id, name=tc.function.name, arguments=_safe_json_loads(tc.function.arguments))
            for tc in (msg.tool_calls or [])
        ]
        raw_reasoning = getattr(msg, "reasoning_content", None)
        raw_items = {"reasoning_content": raw_reasoning} if raw_reasoning else None
        raw_usage = getattr(resp, "usage", None)
        details = getattr(raw_usage, "completion_tokens_details", None)
        usage = Usage(
            provider=self.model, model=self.model, calls=1,
            input_tokens=getattr(raw_usage, "prompt_tokens", None), output_tokens=getattr(raw_usage, "completion_tokens", None),
            reasoning_tokens=getattr(details, "reasoning_tokens", None), cached_tokens=getattr(getattr(raw_usage, "prompt_tokens_details", None), "cached_tokens", None),
        )
        return ModelResponse(text=msg.content or "", tool_requests=tool_requests, raw_items=raw_items, usage=usage)


def _safe_json_loads(text: str | None) -> dict:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


@dataclass
class _TrackBSession:
    """F4 Stage 2F compatibility facade: same name, constructor, `ask()`
    signature and `history` shape Stage 1 had -- verified against
    tests/test_track_b.py and test_f4_reserved_synthesis.py, which construct
    this class directly and inspect `.history` as `list[dict]`. All reasoning
    -loop logic now lives in AnalystLoop; this class only adapts its dict-
    shaped `history` to/from TranscriptItem and supplies the sandbox-derived
    fields (`queries`, `gate_violations`) AnalystLoop cannot know about.

    Cross-turn retention matches Stage 1 exactly: only [question, final_text]
    per turn, verified in test_analyst_loop_multiturn_parity.py.
    """

    sandbox: SnapshotSandbox
    session_id: str
    system_prompt: str
    client: OpenAI
    model: str
    inference_profile: InferenceProfile | None = None
    request_observer: Callable[[str, int, object | None], None] | None = None
    history: list[dict] = field(default_factory=list)

    def ask(self, message: str) -> Turn:
        self.sandbox.log.reset()
        loop = AnalystLoop(
            system_prompt=self.system_prompt,
            transport=ChatCompletionsTransport(
                client=self.client, model=self.model, tool_specs=[_RUN_SQL_SPEC],
                inference_profile=self.inference_profile, request_observer=self.request_observer,
            ),
            action_executor=ActionRegistry([RunSqlAction(sandbox=self.sandbox)]),
            tool_specs=[_RUN_SQL_SPEC],
        )
        prior_history = [TranscriptItem(role=m["role"], text=m["content"]) for m in self.history]
        result = loop.ask(message, history=prior_history)

        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": result.turn.text})

        result.turn.queries = list(self.sandbox.log.statements)
        result.turn.gate_violations = list(self.sandbox.log.violations)
        return result.turn


class TrackBFrontier:
    """Adapter factory.

    Reuses tools.db_chat._provider_chain() for provider *selection* only
    (API key / base_url / model name lookup) -- that's config plumbing, not
    intent/candidate machinery. It deliberately does NOT reuse db_chat's
    per-call multi-provider fallback: a tool-calling conversation replays
    its own prior turns (including reconstructed assistant tool_calls) on
    every iteration, and providers are not interchangeable mid-conversation
    -- verified in practice, not just in theory: falling over to Gemini's
    OpenAI-compat endpoint mid-loop broke with "missing thought_signature
    in functionCall parts" because Gemini expects its own provider-specific
    metadata echoed back on replayed tool calls, which an OpenAI-shaped
    message built for Groq/DeepSeek doesn't carry. So Track B picks ONE
    provider at adapter construction and uses a single bound client for
    every call in every session -- "one available capable model" per the
    experiment's own framing, not an accident of implementation.
    """

    name = "track_b_frontier"

    def __init__(self, sandbox: SnapshotSandbox | None = None, provider: dict | None = None, inference_profile: InferenceProfile | None = None, request_observer=None):
        self.sandbox = sandbox or SnapshotSandbox()
        if provider is None:
            from tools import db_chat  # deferred: avoid importing db_chat (and its
            # DEFAULT_DB_PATH-pointed module state) unless Track B is actually used

            provider = db_chat._provider_chain()[0]
        self.provider = provider
        client_kwargs = {"api_key": provider["api_key"]}
        if provider.get("base_url"):
            client_kwargs["base_url"] = provider["base_url"]
        self.client = OpenAI(**client_kwargs)
        self.model = provider["model"]
        self.inference_profile = inference_profile
        self.request_observer = request_observer
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            semantic_context=_semantic_context(),
            schema_summary=_schema_summary(self.sandbox),
        )

    def new_session(self, session_id: str) -> _TrackBSession:
        return _TrackBSession(
            sandbox=self.sandbox,
            session_id=session_id,
            system_prompt=self._system_prompt,
            client=self.client,
            model=self.model,
            inference_profile=self.inference_profile,
            request_observer=self.request_observer,
        )
