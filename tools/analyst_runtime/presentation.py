"""Alpha-only final presentation boundary, deliberately outside F4."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from tools.analytics.formatting import render_metric_value

PRESENTATION_INSTRUCTION = """Eres la capa final de presentación de un analista inmobiliario.
El borrador ya fue investigado y decidido por otra capa. Reescribe sólo cómo se
comunica: preserva hechos, cifras, fechas, nombres, unidades, conclusiones y
limitaciones materiales. No agregues ni corrijas contenido. Hazlo natural,
directo y fácil de leer; integra las categorías internas en prosa, sin usarlas
como etiquetas o encabezados. Si una frase responde, termina ahí. Usa Markdown
sólo cuando ayude a leer."""

_CLAIM_REF_PROTOCOL = """Tu salida es un objeto JSON con segmentos. DEBES emitir exactamente un claim_ref por cada claim_id autorizado y ningún otro. No escribas valores, unidades, entidades, periodos ni agregaciones en texto libre. No escribas ningún dígito en text; usa únicamente prose narrativa sin cantidades. Los claim_ref son opacos: no copies ni reformules sus datos."""


@dataclass(frozen=True)
class PresentationResult:
    content: str
    applied: bool
    latency_ms: float | None
    provider: str | None
    model: str | None
    integrity_status: str


@dataclass(frozen=True)
class AllowedClaim:
    claim_id: str
    evidence_id: str
    metric_key: str
    entity_id: str
    value: float
    unit: str
    period: str
    aggregation: str | None = None
    lineage: dict[str, object] = field(default_factory=dict)


def render_claim(claim: AllowedClaim) -> str:
    catalog_value = render_metric_value(claim.metric_key, claim.value, claim.unit)
    if catalog_value == f"{claim.value}{claim.unit}":
        value = f"{claim.value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        rendered_value = f"{value} {claim.unit}" if claim.unit else value
    else:
        rendered_value = catalog_value
    return rendered_value


def render_segments(output: dict[str, object], claims: tuple[AllowedClaim, ...]) -> str:
    """Materialize opaque claim references; the model never supplies values."""
    by_id = {claim.claim_id: claim for claim in claims}
    segments = output.get("segments")
    if not isinstance(segments, list):
        raise ValueError("malformed presentation output")
    rendered: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("malformed presentation segment")
        if segment.get("type") == "text" and isinstance(segment.get("text"), str):
            rendered.append(segment["text"])
        elif segment.get("type") == "claim_ref" and isinstance(segment.get("claim_id"), str):
            claim = by_id.get(segment["claim_id"])
            if claim is None:
                raise ValueError("unknown claim_ref")
            rendered.append(render_claim(claim))
        else:
            raise ValueError("malformed presentation segment")
    return "".join(rendered)


def validate_structured_output(output: object, claims: tuple[AllowedClaim, ...]) -> str:
    """Validate presentation output without deriving facts from prose."""
    if not isinstance(output, dict):
        raise ValueError("malformed presentation output")
    segments = output.get("segments")
    if not isinstance(segments, list):
        raise ValueError("malformed presentation output")
    expected = [claim.claim_id for claim in claims]
    if len(set(expected)) != len(expected):
        raise ValueError("malformed allowed claims")
    referenced: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("malformed presentation segment")
        if segment.get("type") == "text":
            content = segment.get("text")
            if not isinstance(content, str):
                raise ValueError("malformed presentation segment")
            if any(character.isdecimal() for character in content):
                raise ValueError("business quantity in free prose")
        elif segment.get("type") == "claim_ref":
            claim_id = segment.get("claim_id")
            if not isinstance(claim_id, str):
                raise ValueError("malformed presentation segment")
            referenced.append(claim_id)
        else:
            raise ValueError("malformed presentation segment")
    if set(referenced) - set(expected):
        raise ValueError("unknown claim_ref")
    if len(referenced) != len(expected) or set(referenced) != set(expected):
        raise ValueError("allowed claim omitted or repeated")
    return render_segments(output, claims)


def _redact_numeric_literals(text: str) -> str:
    """Keep narrative context out of the presentation model's numeric copy path."""
    redacted: list[str] = []
    index = 0
    while index < len(text):
        if text[index].isdecimal():
            while index < len(text) and (text[index].isdecimal() or text[index] in ".,%-"):
                index += 1
            redacted.append("[claim_ref]")
        else:
            redacted.append(text[index])
            index += 1
    return "".join(redacted)


class FinalPresenter(Protocol):
    def present(self, *, user_message: str, draft_answer: str, claims: tuple[AllowedClaim, ...] = ()) -> PresentationResult: ...


class OpenAIResponsesFinalPresenter:
    """One no-tools Responses call with conservative, fail-closed validation."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    def present(self, *, user_message: str, draft_answer: str, claims: tuple[AllowedClaim, ...] = ()) -> PresentationResult:
        started = time.monotonic()
        if not claims:
            # There is no factual presentation contract for free-form output.
            return PresentationResult(draft_answer, False, 0.0, None, None, "not_applicable")
        try:
            allowed = [{"claim_id": c.claim_id, "metric_key": c.metric_key, "entity_id": c.entity_id,
                        "period": c.period, "unit": c.unit, "aggregation": c.aggregation} for c in claims]
            schema = {"type":"object","additionalProperties":False,"required":["segments"],"properties":{"segments":{"type":"array","items":{"anyOf":[{"type":"object","additionalProperties":False,"required":["type","text"],"properties":{"type":{"type":"string","const":"text"},"text":{"type":"string"}}},{"type":"object","additionalProperties":False,"required":["type","claim_id"],"properties":{"type":{"type":"string","const":"claim_ref"},"claim_id":{"type":"string"}}}]}}}}
            response = self._client.responses.create(
                model=self._model,
                instructions=PRESENTATION_INSTRUCTION + "\n\n" + _CLAIM_REF_PROTOCOL,
                input=[{"role": "user", "content": f"Pregunta:\n{user_message}\n\nBorrador narrativo (las cantidades ya fueron eliminadas; no las restaures en texto):\n{_redact_numeric_literals(draft_answer)}\n\nClaims autorizados (referéncialos, no escribas valores):\n{json.dumps(allowed, ensure_ascii=False)}\n\nEjemplo de un único claim c1: {{\"segments\":[{{\"type\":\"text\",\"text\":\"el resultado fue \"}},{{\"type\":\"claim_ref\",\"claim_id\":\"c1\"}}]}}. Sustituye c1 por CADA claim_id autorizado exactamente una vez."}],
                tools=[], tool_choice="none", store=False,
                text={"format":{"type":"json_schema","name":"PresentationSegments","schema":schema,"strict":True}},
            )
            output = json.loads(str(getattr(response, "output_text", "") or ""))
            content = validate_structured_output(output, claims)
            status = "passed"
            return PresentationResult(content, True, _elapsed_ms(started), "openai", self._model, status)
        except (json.JSONDecodeError, ValueError) as exc:
            return _fallback(draft_answer, f"invalid_structured_output:{exc}", started, self._model)
        except Exception as exc:
            return _fallback(draft_answer, f"provider_error:{exc}", started, self._model)


def _fallback(draft: str, status: str, started: float, model: str) -> PresentationResult:
    return PresentationResult(draft, False, _elapsed_ms(started), "openai", model, status)


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000
