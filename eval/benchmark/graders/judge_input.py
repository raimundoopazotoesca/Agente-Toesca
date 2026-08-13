"""Builds the neutral, observable bundle handed to the rubric judge.

Architecture neutrality (design doc section 3, and this feature's own
brief) means the judge sees exactly what a human reviewer looking only at
the transcript and the sandbox trace would see -- nothing that reveals
which system produced the response.

Explicitly INCLUDED: the case spec (question/expected_behavior/
forbidden_claims), materialized ground truth, the response text, the SQL
the sandbox actually captured (not self-reported), a best-effort replay of
those queries' results (read via a trusted connection -- this is
benchmark-side evidence gathering, same trust level as ground_truth.py),
neutral tool-call outcomes (query + ok, no timing), and the deterministic
grader's own results.

Explicitly EXCLUDED, and never touched by this module: `Turn.usage`
(carries provider/model), `Turn.raw` (track-internal payload). Track A/B
adapter modules are never imported here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eval.benchmark.adapters.base import Turn
from eval.benchmark.graders.deterministic import DeterministicResult
from eval.benchmark.graders.ground_truth import ResolvedFact
from eval.benchmark.snapshot import SnapshotSandbox

MAX_RESULT_ROWS = 20


@dataclass
class JudgeInput:
    question: str
    expected_behavior: list[str]
    forbidden_claims: list[str]
    ground_truth: dict[str, dict[str, Any]]
    response_text: str
    executed_sql: list[str]
    query_results: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    deterministic: dict[str, Any]
    tool_requirements: dict[str, Any] | None
    clarification_expected: bool | str | None

    def to_prompt_dict(self) -> dict[str, Any]:
        """Plain-dict rendering for the judge prompt. Field order matters
        for readability, not correctness -- kept stable for prompt caching."""
        return {
            "question": self.question,
            "expected_behavior": self.expected_behavior,
            "forbidden_claims": self.forbidden_claims,
            "clarification_expected": self.clarification_expected,
            "tool_requirements": self.tool_requirements,
            "ground_truth": self.ground_truth,
            "response_text": self.response_text,
            "executed_sql": self.executed_sql,
            "query_results": self.query_results,
            "artifacts": self.artifacts,
            "tool_trace": self.tool_trace,
            "deterministic_grader_results": self.deterministic,
        }


def _replay_query(sandbox: SnapshotSandbox, sql: str) -> dict[str, Any]:
    """Best-effort re-execution of a captured query on a trusted connection,
    to give the judge actual result data instead of just the SQL text.
    Never fails loudly: a query that no longer runs cleanly (e.g. one the
    sandbox's authorizer already logged as a violation) is reported as an
    error entry, not raised -- the judge still needs to see *that* it
    failed, not crash the whole input build over it.
    """
    conn = sandbox.connect(guard=False)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description or []]
        rows = [list(r) for r in cur.fetchmany(MAX_RESULT_ROWS)]
        return {"sql": sql, "columns": cols, "rows": rows}
    except Exception as exc:  # noqa: BLE001 -- surfaced as data, not raised
        return {"sql": sql, "error": str(exc)}
    finally:
        conn.close()


def _summarize_deterministic(result: DeterministicResult) -> dict[str, Any]:
    """Only the deterministic grader's *findings*, not internal fields
    that would leak track identity (there are none here -- DeterministicResult
    is already track-neutral -- but this is the seam where that guarantee
    is enforced, so keep it explicit rather than passing the dataclass
    through as-is)."""
    verdict = result.gate_verdict
    return {
        "dimension_scores": dict(result.dimension_scores),
        "unscored_dimensions": sorted(result.unscored_dimensions),
        "facts_found": list(result.facts_found),
        "facts_missing": list(result.facts_missing),
        "entities_found": result.entities_found,
        "period_ok": result.period_ok,
        "no_numeric_claim": result.no_numeric_claim,
        "is_fatal": result.is_fatal,
        "fatal_gates_triggered": [c.gate for c in verdict.fatal_triggered] if verdict else [],
        "ceiling_gates_triggered": [
            {"gate": c.gate, "ceiling": c.ceiling, "detail": c.detail} for c in verdict.ceiling_triggered
        ] if verdict else [],
        "gates_pending_judge": [c.gate for c in verdict.pending_judge] if verdict else [],
    }


def build_judge_input(
    turn_spec: dict[str, Any],
    turn: Turn,
    resolved: dict[str, ResolvedFact],
    deterministic_result: DeterministicResult,
    sandbox: SnapshotSandbox,
) -> JudgeInput:
    ground_truth = {
        ref: {"value": fact.value, "unit": fact.unit} for ref, fact in resolved.items()
    }

    unique_queries = list(dict.fromkeys(turn.queries))  # de-dup, preserve order
    query_results = [_replay_query(sandbox, q) for q in unique_queries]

    artifacts = [
        {"kind": a.kind, "payload": a.payload, "spec": a.spec} for a in turn.artifacts
    ]
    tool_trace = [
        {"args": tc.args, "ok": tc.ok} for tc in turn.tool_calls
    ]

    return JudgeInput(
        question=turn_spec["question"],
        expected_behavior=turn_spec.get("expected_behavior") or [],
        forbidden_claims=turn_spec.get("forbidden_claims") or [],
        ground_truth=ground_truth,
        response_text=turn.text,
        executed_sql=unique_queries,
        query_results=query_results,
        artifacts=artifacts,
        tool_trace=tool_trace,
        deterministic=_summarize_deterministic(deterministic_result),
        tool_requirements=turn_spec.get("tool_requirements"),
        clarification_expected=turn_spec.get("clarification_expected"),
    )
