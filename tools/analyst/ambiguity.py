"""Decides whether to proceed with SQL generation, or ask for clarification,
based on the resolved IntentResult plus lightweight grounding signals.

Kept deliberately simple: this is an early short-circuit for the clearest
"we truly have nothing to go on" case only. It does not replace the existing
`clarify` mechanism inside the SQL-generation prompt (tools/db_chat.py's
_SQL_SYSTEM instructs the model to ask for clarification itself when it's
unsure) -- it just avoids spending an LLM call on SQL generation when we
already know, deterministically, that we have no metric, no entities, no
verified-query hint, and no conversation history to fall back on.
"""
from __future__ import annotations

from dataclasses import dataclass

from tools.analyst.intent import IntentResult

_CLARIFY_MESSAGE = (
    "¿Podrías especificar qué métrica te interesa (ej. vacancia, NOI, TIR, "
    "dividend yield) y a qué fondo o activo te refieres (TRI, PT, Apo, o un "
    "activo específico)?"
)


@dataclass
class AmbiguityDecision:
    action: str  # "proceed" | "clarify"
    reason: str
    clarify_message: str | None = None


def decide(
    intent: IntentResult,
    verified_hint: dict | None,
    has_history: bool,
) -> AmbiguityDecision:
    if not intent.needs_clarification:
        return AmbiguityDecision("proceed", "intent confidence sufficient or metric/entities inherited from state")

    if verified_hint is not None:
        return AmbiguityDecision("proceed", "low confidence but a verified-query hint grounds the question")

    if has_history:
        return AmbiguityDecision("proceed", "low confidence but conversation history provides context")

    return AmbiguityDecision(
        "clarify",
        "low confidence intent with no metric, no entities, no verified hint, no history",
        clarify_message=_CLARIFY_MESSAGE,
    )
