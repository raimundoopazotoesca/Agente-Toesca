"""Structured intent extraction: question + conversation state -> IntentResult.

Replaces db_chat's direct SQL generation as the first LLM call. The actual
LLM invocation is injected as `llm_call` so this module has no direct
dependency on db_chat's provider chain (kept untouched per spec) and can be
unit-tested without network calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from tools.analyst.conversation_state import get_state, update_state
from tools.analyst.entity_resolver import resolve_entity
from tools.analyst.semantic_loader import SemanticCatalog, load_semantic_catalog

_CONFIDENCE_CLARIFY_THRESHOLD = 0.5

_INTENT_PROMPT_TEMPLATE = """Extrae de la pregunta del usuario un JSON con:
{{"metric": "<nombre de metrica del catalogo o null>",
 "entities": {{"fondo": "<...>", "activo": "<...>"}},
 "period": "<YYYY-MM, YYYY, o null>",
 "comparison": "<same_period_last_year | previous_period | null>",
 "confidence": <0.0-1.0>}}

Metricas disponibles (nombre: sinonimos):
{metric_catalog}
Pregunta: {question}
Responde SOLO el JSON, sin texto adicional."""


@dataclass
class IntentResult:
    metric: str | None
    entities: dict[str, str] = field(default_factory=dict)
    period: str | None = None
    comparison: str | None = None
    confidence: float = 0.0
    needs_clarification: bool = False


def _extract_json(text: str) -> dict:
    """El LLM a veces envuelve el JSON en ``` o lo antecede con texto.
    Misma estrategia que db_chat._extract_json, duplicada aqui porque este
    modulo no depende de db_chat (llm_call se inyecta para mantenerlo
    testeable sin red)."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _format_metric_catalog(catalog: SemanticCatalog) -> str:
    """Cada linea: nombre_tecnico: sinonimo1, sinonimo2, ...
    Sin esto el LLM solo ve nombres tecnicos (ej. 'vacancia_pct') y debe
    adivinar que 'ocupacion'/'occupancy' mapean a esa metrica por su propio
    conocimiento -- inconsistente entre llamadas. Los sinonimos ya viven en
    semantic/metrics/*.yaml (campo `synonyms`), curados para esto."""
    lines = []
    for name in sorted(catalog.metrics):
        synonyms = catalog.metrics[name].get("synonyms") or []
        syn_str = ", ".join(synonyms) if synonyms else "(sin sinonimos registrados)"
        lines.append(f"- {name}: {syn_str}")
    return "\n".join(lines)


def _build_prompt(question: str) -> str:
    catalog = load_semantic_catalog()
    return _INTENT_PROMPT_TEMPLATE.format(
        metric_catalog=_format_metric_catalog(catalog),
        question=question,
    )


def extract_intent(question: str, session_id: str, llm_call: Callable[[str], str]) -> IntentResult:
    catalog = load_semantic_catalog()
    prompt = _build_prompt(question)
    raw = llm_call(prompt)

    parsed = _extract_json(raw) if raw else {}
    if not parsed:
        return IntentResult(metric=None, confidence=0.0, needs_clarification=True)

    state = get_state(session_id)

    metric = parsed.get("metric") or state["last_metric"]

    entities_raw = parsed.get("entities") or {}
    resolved_entities: dict[str, str] = {}
    for kind, text in entities_raw.items():
        if kind in ("fondo", "activo") and text:
            resolved = resolve_entity(text, kind, catalog)
            resolved_entities[kind] = resolved or text
        elif text:
            resolved_entities[kind] = text
    entities = resolved_entities or state["last_entities"]

    period = parsed.get("period") or state["last_period"]
    comparison = parsed.get("comparison")
    confidence = float(parsed.get("confidence", 0.0))
    needs_clarification = confidence < _CONFIDENCE_CLARIFY_THRESHOLD and not (metric and entities)

    update_state(
        session_id,
        last_metric=metric,
        last_entities=entities,
        last_period=period,
        last_analysis_type=comparison,
    )

    return IntentResult(
        metric=metric,
        entities=entities,
        period=period,
        comparison=comparison,
        confidence=confidence,
        needs_clarification=needs_clarification,
    )
