"""A2 TurnTrace v1: JSON-safe runtime observability without hidden reasoning."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from tools.analyst_runtime.resolution import ResolutionOutcome, unavailable_resolution


TRACE_VERSION = "1"
_OPTIONAL_FIELD_ERRORS = "optional_field_errors"

# Durable TurnTrace action metadata is allowlist-first: only fields the
# contract actually reads/needs survive into persisted storage. A future
# ToolCall.trace key (e.g. a raw provider payload) is dropped by default
# instead of leaking through, unless explicitly added here.
_ALLOWED_ACTION_METADATA_FIELDS = frozenset({
    "tool_name", "status", "success", "duration_ms", "candidates", "resolution",
    "evidence_id", "error", "result", "arguments", "scope", "unknown_fields",
    "semantic_rejection", "requested_limit", "effective_limit", "dialect",
    "metadata_version", "candidate_names", "object_count",
    "requested_entity_types", "fund", "query",
})


@dataclass(frozen=True)
class ReconstructedTurn:
    user_text: str
    resolutions: Mapping[str, Any]
    routing: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    final_answer: str


def build_turn_trace(
    result: Any, *, user_text: str, turn_id: str, conversation_id: str, session_id: str,
    user_message_id: str | None = None, assistant_message_id: str | None = None,
) -> dict[str, Any]:
    optional_errors: list[dict[str, str]] = []
    actions = [_action(call, optional_errors) for call in getattr(result, "tool_calls", ())]
    resolutions = _resolutions(actions)
    usage = getattr(result, "usage", None)
    trace: dict[str, Any] = {
        "trace_version": TRACE_VERSION,
        "identity": {
            "turn_id": turn_id, "conversation_id": conversation_id, "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), "span_type": "analyst_turn",
            **({"user_message_id": user_message_id} if user_message_id else {}),
            **({"assistant_message_id": assistant_message_id} if assistant_message_id else {}),
        },
        "input": {"user_turn_text": user_text},
        "resolution": {name: value.as_dict() for name, value in resolutions.items()},
        "routing": {
            "selected_action_path": [action["name"] for action in actions],
            "reason_code": getattr(result, "termination_reason", None) or "completed",
            "decision": _routing_decision(result),
        },
        "execution": {
            "tool_calls": actions,
            "sql_statements": list(getattr(result, "sql_queries", ()) or ()),
            "evidence_references": _evidence_refs(actions),
        },
        "model": _model(usage),
        "output": {
            "final_answer": str(getattr(result, "text", "")),
            "termination_reason": getattr(result, "termination_reason", None),
        },
        "validation": {"outcome": "not_owned_by_a2"},
        "completion": {"status": "completed"},
    }
    if optional_errors:
        trace[_OPTIONAL_FIELD_ERRORS] = optional_errors
    return trace


def reconstruct_turn(trace: Mapping[str, Any]) -> ReconstructedTurn:
    if trace.get("trace_version") != TRACE_VERSION or trace.get("completion", {}).get("status") != "completed":
        raise ValueError("not a completed TurnTrace v1")
    return ReconstructedTurn(
        str(trace["input"]["user_turn_text"]), trace["resolution"], trace["routing"],
        tuple(trace["execution"].get("evidence_references", ())), str(trace["output"]["final_answer"]),
    )


def _action(call: Any, optional_errors: list[dict[str, str]]) -> dict[str, Any]:
    trace = getattr(call, "trace", {}) or {}
    if not isinstance(trace, Mapping):
        optional_errors.append({"field": "action.trace", "reason_code": "invalid_optional_action_trace"})
        trace = {}
    dropped_count = len(set(trace) - _ALLOWED_ACTION_METADATA_FIELDS)
    if dropped_count:
        # Field names themselves are not recorded here: a dropped key can be an
        # attacker/provider-chosen string (e.g. "prompt"), and echoing key names
        # back into the trace would defeat the allowlist's own purpose.
        optional_errors.append({"field": "action.trace", "reason_code": "unallowlisted_action_trace_fields", "dropped_count": str(dropped_count)})
    safe_metadata = {key: value for key, value in trace.items() if key in _ALLOWED_ACTION_METADATA_FIELDS}
    name = str(getattr(call, "name", "unknown"))
    arguments = getattr(call, "args", {}) or {}
    safe_args = {key: value for key, value in arguments.items() if key in {"query", "entity_types", "fund", "metric_id", "period", "periodo", "limit", "filters"}}
    return {"name": name, "ok": bool(getattr(call, "ok", False)), "duration_ms": getattr(call, "duration_ms", None), "arguments": safe_args, "metadata": safe_metadata}


def _resolutions(actions: list[Mapping[str, Any]]) -> dict[str, ResolutionOutcome]:
    entity = unavailable_resolution("not_requested")
    metric = unavailable_resolution("not_observed")
    period = unavailable_resolution("not_observed")
    for action in actions:
        metadata = action["metadata"]
        if action["name"] == "resolve_entity":
            status = metadata.get("resolution", {}).get("status") if isinstance(metadata.get("resolution"), Mapping) else metadata.get("resolution_status")
            entity = ResolutionOutcome(status if status in {"resolved", "ambiguous"} else "unknown", method="entity_resolver", reason_code=None if status in {"resolved", "ambiguous"} else str(status or "not_found"), evidence={"internal_status": status or "not_found"}, candidates=tuple(metadata.get("candidates", ())))
        args = action["arguments"]
        if args.get("metric_id"):
            metric = ResolutionOutcome("resolved", str(args["metric_id"]), "action_argument")
        if args.get("period") or args.get("periodo"):
            period = ResolutionOutcome("resolved", str(args.get("period") or args.get("periodo")), "action_argument")
    return {"entity": entity, "metric": metric, "period": period}


def _routing_decision(result: Any) -> str:
    termination = getattr(result, "termination_reason", None)
    if termination in {"clarification_required", "semantic_rejection"}:
        return "fail_closed"
    return "runtime_finalization"


def _evidence_refs(actions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"action": action["name"], "evidence_id": action["metadata"].get("evidence_id")}
            for action in actions if action["metadata"].get("evidence_id")]


def _model(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    return {key: value for key, value in {
        "provider": getattr(usage, "provider", None), "model": getattr(usage, "model", None),
        "calls": getattr(usage, "calls", None), "retry_count": getattr(usage, "retries", None),
        "input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None),
        "latency_ms": getattr(usage, "llm_latency_ms", None) or getattr(usage, "latency_ms", None),
    }.items() if value is not None}

