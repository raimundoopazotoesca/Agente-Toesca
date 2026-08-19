"""Alpha-only final presentation boundary, deliberately outside F4."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Protocol


PRESENTATION_INSTRUCTION = """Eres la capa final de presentación de un analista inmobiliario.
El borrador ya fue investigado y decidido por otra capa. Reescribe sólo cómo se
comunica: preserva hechos, cifras, fechas, nombres, unidades, conclusiones y
limitaciones materiales. No agregues ni corrijas contenido. Hazlo natural,
directo y fácil de leer; integra las categorías internas en prosa, sin usarlas
como etiquetas o encabezados. Si una frase responde, termina ahí. Usa Markdown
sólo cuando ayude a leer."""

_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:\s?(?:%|UF|m²|m2|CLP|M\$|\$))?")
_CAVEAT_ANCHORS = (
    "no puedo afirmar", "no es posible determinar", "cobertura parcial",
    "cobertura es parcial",
    "falta información", "evidencia parcial", "no necesariamente",
    "con la evidencia disponible", "no está completo",
)


@dataclass(frozen=True)
class PresentationResult:
    content: str
    applied: bool
    latency_ms: float | None
    provider: str | None
    model: str | None
    integrity_status: str


class FinalPresenter(Protocol):
    def present(self, *, user_message: str, draft_answer: str) -> PresentationResult: ...


class OpenAIResponsesFinalPresenter:
    """One no-tools Responses call with conservative, fail-closed validation."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    def present(self, *, user_message: str, draft_answer: str) -> PresentationResult:
        started = time.monotonic()
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=PRESENTATION_INSTRUCTION,
                input=[{"role": "user", "content": f"Pregunta:\n{user_message}\n\nBorrador:\n{draft_answer}"}],
                tools=[], tool_choice="none", store=False,
            )
            content = str(getattr(response, "output_text", "") or "").strip()
            status = _integrity_status(draft_answer, content)
            if status != "passed":
                return _fallback(draft_answer, status, started, self._model)
            return PresentationResult(content, True, _elapsed_ms(started), "openai", self._model, status)
        except Exception:
            return _fallback(draft_answer, "provider_error", started, self._model)


def _integrity_status(draft: str, presented: str) -> str:
    if not presented:
        return "empty"
    if len(presented) < max(8, len(draft) // 7):
        return "too_short"
    draft_numbers = _numbers(draft)
    presented_numbers = _numbers(presented)
    if draft_numbers != presented_numbers:
        return "failed_facts"
    draft_lower = _normalize(draft)
    presented_lower = _normalize(presented)
    if any(anchor in draft_lower and anchor not in presented_lower for anchor in _CAVEAT_ANCHORS):
        return "failed_caveat"
    return "passed"


def _numbers(text: str) -> set[str]:
    return {match.group(0).replace(" ", "") for match in _NUMBER.finditer(text.replace("**", ""))}


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _fallback(draft: str, status: str, started: float, model: str) -> PresentationResult:
    return PresentationResult(draft, False, _elapsed_ms(started), "openai", model, status)


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000
