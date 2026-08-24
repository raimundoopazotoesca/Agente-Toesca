"""F4 Stage 2: the provider-neutral reasoning loop.

Moved from eval/benchmark/adapters/analyst_loop.py (Stage A1) byte-for-byte.

Everything here is reasoning POLICY: how many rounds exist, when investigation
gives way to mandatory synthesis, how one turn's transcript is assembled, when
to stop, how to invoke actions. None of it is provider wire protocol (that's
ModelTransport, transport.py) and none of it is SQL or any other action's
semantics (that's ActionExecutor, injected).

Architectural invariant this module exists to enforce: AnalystLoop imports
NOTHING from `openai`, `anthropic`, `eval.benchmark.snapshot` (SnapshotSandbox),
or any SQL-validation helper. It has never compared an action name to the
string "run_sql". It receives a ToolRequest and hands it to `action_executor`;
it has no idea what comes back besides a ToolResult.

Cross-turn history retention is deliberately NOT this module's decision.
`ask()` takes the prior-turn history explicitly and returns the full round
trajectory alongside the Turn; what subset of that trajectory a session keeps
for the *next* turn is provider-shaped. That policy lives in whatever
constructs and reuses an AnalystLoop across turns (a session wrapper), not in
AnalystLoop itself.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from tools.analyst_runtime.transport import (
    ModelRequest,
    ModelResponse,
    ModelTransport,
    ToolRequest,
    ToolResult,
    ToolSpec,
    TranscriptItem,
)
from tools.analyst_runtime.base import Artifact, Turn, ToolCall, Usage

# Round budget (F4 stage 1, unchanged in Stage 2). The TOTAL number of model
# calls per turn is unchanged from Round B (5) -- what changed in Stage 1 is
# that the last one is reserved for synthesis instead of being spendable on
# another investigation branch.
MAX_TOTAL_MODEL_ROUNDS = 5
RESERVED_SYNTHESIS_ROUNDS = 1
MAX_INVESTIGATION_ROUNDS = MAX_TOTAL_MODEL_ROUNDS - RESERVED_SYNTHESIS_ROUNDS

# Sent as a normal turn message on the reserved synthesis round only -- NOT
# part of any system prompt, so system_prompt_sha256 stays byte-identical to
# B26/B27 and the only model-facing difference an F4 run introduces is the
# loop structure itself. Deliberately generic: no metric, fund, asset or
# benchmark-case specific instruction belongs here.
_SYNTHESIS_INSTRUCTION = (
    "Se agoto el presupuesto de investigacion: esta es tu ultima intervencion y no "
    "tienes herramientas disponibles. Responde ahora con la mejor conclusion que "
    "sustente la evidencia ya obtenida. No abras nuevas lineas de investigacion ni "
    "propongas consultas adicionales. Declara de forma natural cualquier incertidumbre "
    "material o dato que no hayas podido verificar."
)

_CHART_BLOCK = re.compile(r"```chart\s*\n(.*?)```", re.DOTALL)


class ActionExecutor(Protocol):
    """The one seam through which AnalystLoop touches the outside world for
    tool execution."""

    def execute(self, request: ToolRequest) -> ToolResult: ...


@dataclass
class LoopResult:
    """`ask()`'s full answer: the neutral Turn plus this turn's complete round
    trajectory (all investigation rounds, including tool exchanges) -- for a
    caller that needs to decide what to retain for the next turn."""

    turn: Turn
    round_trajectory: list[TranscriptItem]


@dataclass
class InvestigationResult:
    """Provider-neutral evidence-gathering trajectory, before any finalization."""

    round_trajectory: list[TranscriptItem]
    tool_calls: list[ToolCall]
    usage: Usage
    termination_reason: str
    final_text: str = ""


@dataclass
class AnalystLoop:
    """One turn's reasoning loop, provider-neutral. `transport` translates
    to/from one provider's wire protocol; `action_executor` runs whatever a
    ToolRequest asks for. AnalystLoop knows neither's internals -- only the
    shapes in transport.py.
    """

    system_prompt: str
    transport: ModelTransport
    action_executor: ActionExecutor
    tool_specs: list[ToolSpec] = field(default_factory=list)

    def investigate(self, message: str, history: list[TranscriptItem] | None = None) -> InvestigationResult:
        started = time.monotonic()
        round_history: list[TranscriptItem] = list(history or [])
        next_message = message
        final_text = ""
        tool_calls_log: list[ToolCall] = []
        total_usage = Usage()
        termination_reason = "budget_exhausted"

        for _ in range(MAX_INVESTIGATION_ROUNDS):
            request = ModelRequest(system_prompt=self.system_prompt, history=round_history, message=next_message, tools=self.tool_specs)
            response = self.transport.complete(request)
            _accumulate(total_usage, response.usage)

            user_text = next_message if next_message else None
            next_message = ""

            if not response.tool_requests:
                final_text = response.text
                round_history = _append_turn(round_history, user_text, response, [])
                termination_reason = "model_terminal"
                break

            results: list[ToolResult] = []
            for index, tr in enumerate(response.tool_requests):
                result = self.action_executor.execute(tr)
                results.append(result)
                tool_calls_log.append(ToolCall(name=tr.name, args=tr.arguments, ok=result.ok, trace=result.trace))
                if result.control and result.control.get("kind") in {"clarification_required", "semantic_rejection"}:
                    result.trace["blocked_followup_tool_calls"] = [request.name for request in response.tool_requests[index + 1:]]
                    termination_reason = str(result.control["kind"])
                    result.trace["termination_reason"] = termination_reason
                    final_text = (_clarification_text(result.control) if termination_reason == "clarification_required"
                                  else _semantic_rejection_text(result.control))
                    break
            round_history = _append_turn(round_history, user_text, response, results)
            if termination_reason in {"clarification_required", "semantic_rejection"}:
                break
        total_usage.latency_ms = (time.monotonic() - started) * 1000
        return InvestigationResult(round_history, tool_calls_log, total_usage, termination_reason, final_text)

    def _legacy_finalize(self, investigation: InvestigationResult) -> LoopResult:
        final_text = investigation.final_text
        round_history = investigation.round_trajectory
        total_usage = investigation.usage
        termination_reason = investigation.termination_reason
        if termination_reason == "budget_exhausted":
            request = ModelRequest(self.system_prompt, round_history, _SYNTHESIS_INSTRUCTION, [])
            response = self.transport.complete(request)
            _accumulate(total_usage, response.usage)
            final_text = response.text
            round_history = _append_turn(round_history, _SYNTHESIS_INSTRUCTION, response, [])
        turn = Turn(
            text=final_text,
            artifacts=_extract_artifacts(final_text),
            tool_calls=investigation.tool_calls,
            usage=total_usage,
            raw={"final_text": final_text, **({"termination_reason": termination_reason}
                                                if termination_reason in {"clarification_required", "semantic_rejection"} else {})},
        )
        return LoopResult(turn=turn, round_trajectory=round_history)

    def finalize(self, investigation: InvestigationResult, output_contract: object | None = None,
                 synthesis_context: str = "") -> LoopResult:
        """Perform one tool-free finalization without interpreting its content.

        `synthesis_context` is opaque extra text the caller appends to the
        reserved synthesis message. AnalystLoop neither builds nor inspects it:
        what an evidence inventory is, and whether one exists, is the session's
        concern. When it is empty the synthesis message stays byte-identical to
        `_SYNTHESIS_INSTRUCTION`.
        """
        if investigation.termination_reason in {"clarification_required", "semantic_rejection"}:
            return self._legacy_finalize(investigation)
        message = f"{_SYNTHESIS_INSTRUCTION}\n\n{synthesis_context}" if synthesis_context else _SYNTHESIS_INSTRUCTION
        request = ModelRequest(self.system_prompt, investigation.round_trajectory, message, [], output_contract)
        response = self.transport.complete(request)
        total_usage = investigation.usage
        _accumulate(total_usage, response.usage)
        history = _append_turn(investigation.round_trajectory, message, response, [])
        turn = Turn(response.text, _extract_artifacts(response.text), investigation.tool_calls, total_usage,
                    raw={"final_text": response.text, "structured_output": response.structured_output})
        return LoopResult(turn, history)

    def ask(self, message: str, history: list[TranscriptItem] | None = None) -> LoopResult:
        """Legacy compatibility wrapper: investigation plus one plain finalization."""
        return self._legacy_finalize(self.investigate(message, history))


def _append_turn(history: list[TranscriptItem], user_text: str | None, response: ModelResponse, results: list[ToolResult]) -> list[TranscriptItem]:
    out = list(history)
    if user_text is not None:
        out.append(TranscriptItem(role="user", text=user_text))
    out.append(TranscriptItem(role="assistant", text=response.text, tool_requests=response.tool_requests, tool_results=results, raw=response.raw_items))
    return out


def _clarification_text(control: dict[str, object]) -> str:
    query = str(control.get("entity_query", "la entidad"))
    status = control.get("resolution_status")
    candidates = control.get("candidates", [])
    candidate_types = {item.get("entity_type") for item in candidates if isinstance(item, dict)}
    if {"fund", "asset"} <= candidate_types:
        return f"¿Te refieres al fondo {query} o a alguno de los activos de {query}?"
    if status == "ambiguous" and candidate_types == {"asset"}:
        names = [str(item.get("canonical_name")) for item in candidates if isinstance(item, dict)]
        return f"Encontré más de un activo que podría coincidir con '{query}': {', '.join(names)}. ¿Cuál buscas?"
    if status == "ambiguous":
        return f"No pude resolver '{query}' a una entidad canónica única. ¿Puedes precisar a qué entidad te refieres?"
    if status == "not_found":
        return f"No encontré una entidad canónica para '{query}'. ¿Puedes precisar a qué entidad te refieres?"
    names = [str(item.get("canonical_name")) for item in candidates if isinstance(item, dict)]
    if len(names) == 1:
        return f"¿Te referías a {names[0]}?"
    return f"No pude resolver '{query}' a una entidad canónica con suficiente confianza. ¿Puedes precisar a qué entidad te refieres?"


def _semantic_rejection_text(control: dict[str, object]) -> str:
    requested = str(control.get("requested_aggregation", "esa operación"))
    requested = {"sum": "sumar", "avg": "promediar", "last": "tomar el último valor"}.get(requested, requested)
    metric = str(control.get("metric_id", "esta métrica")).replace("_", " ")
    alternatives = control.get("allowed_aggregations", [])
    if alternatives:
        return f"No se puede {requested} {metric}; las operaciones permitidas son: {', '.join(map(str, alternatives))}."
    return f"No se puede {requested} {metric}, porque es una métrica de punto en el tiempo o razón y no admite esa agregación."


def _accumulate(total: Usage, call: Usage) -> None:
    total.calls += call.calls or 1
    for field_name in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"):
        addend = getattr(call, field_name)
        if addend is not None:
            setattr(total, field_name, (getattr(total, field_name) or 0) + addend)
    total.provider = total.provider or call.provider
    total.model = total.model or call.model


def _extract_artifacts(text: str) -> list[Artifact]:
    return [Artifact(kind="chart", payload=m.group(1).strip()) for m in _CHART_BLOCK.finditer(text or "")]
