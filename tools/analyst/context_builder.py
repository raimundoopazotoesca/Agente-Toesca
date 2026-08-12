"""Boundary that turns a user question + conversation state into everything
tools/db_chat.py's SQL-generation prompt needs: a structured IntentResult,
resolved entities/metric/period, business definitions, a verified-query hint,
and an ambiguity decision -- assembled as labeled (title, content) sections
ready to splice into the chat-completion `messages` list.

This does NOT call the LLM for SQL generation and does NOT touch
_validate_sql/_run_sql -- it only prepares context for the existing pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tools.analyst.ambiguity import AmbiguityDecision, decide
from tools.analyst.intent import IntentResult, extract_intent
from tools.analyst.semantic_loader import load_semantic_catalog
from tools.analyst.temporal import TemporalResolution, resolve_temporal
from tools.analyst.verified_queries_repo import find_similar


@dataclass
class AnalystContext:
    intent: IntentResult
    decision: AmbiguityDecision
    temporal: TemporalResolution | None
    verified_hint: dict | None
    prompt_sections: list[tuple[str, str]] = field(default_factory=list)


def _metric_time_behavior(metric_name: str | None) -> str | None:
    if not metric_name:
        return None
    catalog = load_semantic_catalog()
    metric = catalog.metrics.get(metric_name)
    return metric.get("time_behavior") if metric else None


def _build_sections(
    question: str,
    intent: IntentResult,
    temporal: TemporalResolution | None,
    verified_hint: dict | None,
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []

    intent_lines = [f"metric: {intent.metric or '(sin resolver)'}"]
    for kind, value in intent.entities.items():
        intent_lines.append(f"entity[{kind}]: {value}")
    if intent.comparison:
        intent_lines.append(f"comparison: {intent.comparison}")
    intent_lines.append(f"confidence: {intent.confidence:.2f}")
    sections.append(("RESOLVED INTENT", "\n".join(intent_lines)))

    if intent.metric:
        catalog = load_semantic_catalog()
        metric_def = catalog.metrics.get(intent.metric)
        if metric_def:
            def_lines = [
                f"business_definition: {metric_def.get('business_definition', '')}",
                f"formula: {metric_def.get('formula', '')}",
                f"unit: {metric_def.get('unit', '')}",
            ]
            sections.append(("BUSINESS DEFINITIONS", "\n".join(def_lines)))

    period_lines = []
    if intent.period:
        period_lines.append(f"period (from intent): {intent.period}")
    if temporal is not None:
        period_lines.append(f"temporal phrase resolved: {temporal.label}")
        if temporal.period:
            period_lines.append(f"resolved period: {temporal.period}")
        if temporal.period_range:
            period_lines.append(f"resolved range: {temporal.period_range[0]} a {temporal.period_range[1]}")
        if temporal.comparison_period:
            period_lines.append(f"comparison: {temporal.comparison_period}")
        if temporal.data_gap_warning:
            period_lines.append(f"advertencia: {temporal.data_gap_warning}")
    if period_lines:
        sections.append(("PERIOD / COMPARISON", "\n".join(period_lines)))

    if verified_hint:
        sections.append((
            "VERIFIED EXAMPLE",
            f"Q: {verified_hint['question']}\nSQL: {verified_hint['sql']}\n"
            f"Notas: {verified_hint.get('notes', '')}",
        ))

    return sections


def build_context(
    question: str,
    session_id: str,
    history: list[dict],
    llm_call: Callable[[str], str],
) -> AnalystContext:
    intent = extract_intent(question, session_id, llm_call)

    verified = find_similar(question, top_k=1)
    verified_hint = verified[0] if verified else None

    time_behavior = _metric_time_behavior(intent.metric)
    temporal = resolve_temporal(question, time_behavior=time_behavior)

    has_history = bool(history)
    decision = decide(intent, verified_hint=verified_hint, has_history=has_history)

    prompt_sections = (
        [] if decision.action == "clarify" else _build_sections(question, intent, temporal, verified_hint)
    )

    return AnalystContext(
        intent=intent,
        decision=decision,
        temporal=temporal,
        verified_hint=verified_hint,
        prompt_sections=prompt_sections,
    )
