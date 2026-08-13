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
final answer. Capped at MAX_TOOL_ITERATIONS rounds so a confused model
can't loop forever inside a benchmark run.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from eval.benchmark.adapters.base import Artifact, ToolCall, Turn, Usage
from eval.benchmark.snapshot import SnapshotSandbox

SEMANTIC_DIR = Path(__file__).resolve().parents[3] / "semantic"

MAX_TOOL_ITERATIONS = 5
MAX_ROWS_RETURNED = 50
_CHART_BLOCK = re.compile(r"```chart\s*\n(.*?)```", re.DOTALL)

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


def _validate_sql(sql: str) -> str | None:
    """None if safe to attempt; an error string otherwise. This is a cheap
    pre-filter for a better error message back to the model -- the sandbox's
    authorizer (gate F4) is the actual enforcement layer regardless."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        return "Query vacia."
    if ";" in s:
        return "Solo se permite una sentencia SQL."
    head = s.split(None, 1)[0].lower()
    if head not in {"select", "with"}:
        return "Solo se permiten sentencias SELECT o WITH."
    if _FORBIDDEN_RE.search(s):
        return "La consulta contiene una operacion no permitida (solo lectura)."
    return None


def _format_tool_result(columns: list[str], rows: list[list]) -> str:
    truncated = rows[:MAX_ROWS_RETURNED]
    payload = {
        "columns": columns,
        "rows": truncated,
        "row_count": len(rows),
        "truncated": len(rows) > len(truncated),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _extract_artifacts(text: str) -> list[Artifact]:
    return [Artifact(kind="chart", payload=m.group(1).strip()) for m in _CHART_BLOCK.finditer(text or "")]


@dataclass
class _TrackBSession:
    sandbox: SnapshotSandbox
    session_id: str
    system_prompt: str
    client: OpenAI
    model: str
    history: list[dict] = field(default_factory=list)

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
            cols = [d[0] for d in cur.description or []]
            rows = [list(r) for r in cur.fetchmany(MAX_ROWS_RETURNED)]
            return _format_tool_result(cols, rows), True
        except Exception as exc:  # noqa: BLE001 -- surfaced to the model as a tool error, not raised
            return json.dumps({"error": str(exc)}, ensure_ascii=False), False
        finally:
            conn.close()

    def ask(self, message: str) -> Turn:
        self.sandbox.log.reset()
        started = time.monotonic()

        messages = [{"role": "system", "content": self.system_prompt}, *self.history, {"role": "user", "content": message}]
        tool_calls_log: list[ToolCall] = []
        final_text = ""
        api_calls = 0

        for _ in range(MAX_TOOL_ITERATIONS):
            call_started = time.monotonic()
            # One provider for the whole session (see TrackBFrontier docstring
            # on why: mixing providers mid-loop broke Gemini's OpenAI-compat
            # tool-call replay in practice, not just in theory).
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=[_RUN_SQL_TOOL], tool_choice="auto", temperature=0.0,
            )
            api_calls += 1
            msg = resp.choices[0].message

            if not msg.tool_calls:
                final_text = msg.content or ""
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                query = args.get("query", "")
                result_text, ok = self._run_tool(query)
                duration_ms = (time.monotonic() - call_started) * 1000
                tool_calls_log.append(ToolCall(name="run_sql", args={"query": query}, ok=ok, duration_ms=duration_ms))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
        else:
            final_text = final_text or (
                "(no se alcanzo una respuesta final dentro del limite de iteraciones de herramientas)"
            )

        elapsed_ms = (time.monotonic() - started) * 1000
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": final_text})

        return Turn(
            text=final_text,
            artifacts=_extract_artifacts(final_text),
            tool_calls=tool_calls_log,
            usage=Usage(provider=self.model, model=self.model, calls=api_calls, latency_ms=elapsed_ms),
            queries=list(self.sandbox.log.statements),
            gate_violations=list(self.sandbox.log.violations),
            raw={"final_text": final_text},
        )


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

    def __init__(self, sandbox: SnapshotSandbox | None = None, provider: dict | None = None):
        self.sandbox = sandbox or SnapshotSandbox()
        if provider is None:
            from tools import db_chat  # deferred: avoid importing db_chat (and its
            # DEFAULT_DB_PATH-pointed module state) unless Track B is actually used

            provider = db_chat._provider_chain()[0]
        self.provider = provider
        self.client = OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])
        self.model = provider["model"]
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
        )
