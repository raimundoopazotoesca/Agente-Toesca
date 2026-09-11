"""Alpha-only final presentation boundary, deliberately outside F4."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from tools.analyst_runtime.derived_claims import DerivedClaim, render_derived_claim
from tools.analyst_runtime.trend_assertions import AMBIGUOUS, Direction, extract_clause_trend_hits
from tools.analytics.catalog import load_metric_catalog
from tools.analytics.formatting import render_metric_value

_DERIVED_OPERATION_DISPLAY = {
    "difference": "diferencia", "percent_change": "variación porcentual",
    "percentage_point_difference": "diferencia en puntos porcentuales", "ratio": "razón",
}


def _metric_display_name(metric_key: str) -> str:
    if metric_key.startswith("derived:"):
        return _DERIVED_OPERATION_DISPLAY.get(metric_key.removeprefix("derived:"), metric_key)
    try:
        metric = load_metric_catalog().metrics.get(metric_key)
    except Exception:  # noqa: BLE001 -- display must never raise
        metric = None
    return metric.display_name if metric is not None else metric_key

PRESENTATION_INSTRUCTION = """Eres la capa final de presentación de un analista inmobiliario.
El borrador ya fue investigado y decidido por otra capa. Reescribe sólo cómo se
comunica: preserva hechos, cifras, fechas, nombres, unidades, conclusiones y
limitaciones materiales. No agregues ni corrijas contenido. Hazlo natural,
directo y fácil de leer; integra las categorías internas en prosa, sin usarlas
como etiquetas o encabezados. Si una frase responde, termina ahí. Usa Markdown
sólo cuando ayude a leer.
Si la pregunta del usuario es de sí/no, más/menos, cuál es mayor/menor, o
existe/no existe, y el borrador ya contiene esa conclusión, empieza tu
respuesta por la conclusión misma (una palabra o frase corta: "No.", "Más.",
"Sí, ...") y recién después explica o matiza con el resto del borrador. No
inventes una conclusión que el borrador no sustente; si el borrador no la
contiene, no la agregues."""

_CLAIM_REF_PROTOCOL = """Tu salida es un objeto JSON con segmentos. DEBES emitir exactamente un claim_ref por cada claim_id autorizado y ningún otro. No escribas valores, unidades ni cifras en texto libre; el número lo inserta el sistema al resolver claim_ref. No escribas ningún dígito en text; usa únicamente prosa narrativa sin cantidades. Para nombrar la entidad, el periodo o la métrica en tu prosa, usa exactamente los campos "entity", "metric" y "period" ya provistos en cada claim autorizado -- no traduzcas tú códigos internos ni fechas "YYYY-MM"; esos campos ya vienen en español natural, listos para usar tal cual. Nunca escribas claves internas (códigos de fondo/activo, "YYYY-MM", nombres de columnas, "canonical", "coverage", "mapping", "entity_id"). Los claim_ref son opacos: no copies ni reformules sus datos."""


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
    # Deterministic, pre-translated display strings (never computed by the
    # presentation LLM itself) so it can phrase entity/period naturally
    # without touching the raw key / YYYY-MM code.
    entity_display: str | None = None
    period_display: str | None = None
    requested_monetary_unit: str | None = None
    presentation_conversion: dict[str, object] | None = None


def render_claim(claim: AllowedClaim) -> str:
    if claim.metric_key.startswith("derived:"):
        operation = claim.metric_key.removeprefix("derived:")
        return render_derived_claim(DerivedClaim(claim.claim_id, operation, claim.value, claim.unit, claim.lineage))
    catalog_value = render_metric_value(claim.metric_key, claim.value, claim.unit,
                                        {"value": claim.value, "unit": claim.unit,
                                         "presentation_conversion": claim.presentation_conversion},
                                        claim.requested_monetary_unit)
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
    def present(self, *, user_message: str, draft_answer: str, claims: tuple[AllowedClaim, ...] = (),
               trend_index: dict[tuple[str, str], Direction] | None = None) -> PresentationResult: ...


def _entity_mentions(text: str, name: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.UNICODE) is not None


def _extract_trend_directions(
    text: str, claims: tuple[AllowedClaim, ...], trend_index: dict[tuple[str, str], Direction],
) -> dict[tuple[str, str], Direction] | str:
    """A3.3: (entity_id, metric_key) -> direction asserted in ``text``.

    Runs on ALREADY-RENDERED prose (draft_answer / the presenter's own
    output), so there is no claim_id/fragment structure left to bind
    against -- unlike coverage_guard's fragment-adjacency binding. Instead
    this resolves a clause's entity the same way coverage_guard's own
    entity-provenance guard does elsewhere: literal, word-boundary matching
    of a real display name/entity_id already known to be correct (from the
    SAME AllowedClaim list coverage_guard's binding produced) -- never a new
    text-to-entity heuristic. A clause is only resolved when exactly one
    entity is named in it AND trend_index carries exactly one metric_key for
    that entity (mirroring coverage_guard's own null-metric_key single-
    candidate inference pattern); anything less unambiguous is silently
    skipped here, never guessed -- see the A3.3 Design Memo v2 closure notes
    on this layer's narrower, intentionally conservative coverage.
    """
    if not trend_index:
        return {}
    entity_names: dict[str, list[str]] = {}
    for claim in claims:
        names = entity_names.setdefault(claim.entity_id, [])
        for candidate in (claim.entity_display, claim.entity_id):
            if candidate and candidate not in names:
                names.append(candidate)
    hits = extract_clause_trend_hits(text)
    if hits == AMBIGUOUS:
        return AMBIGUOUS
    resolved: dict[tuple[str, str], Direction] = {}
    for hit in hits:
        matched_entities = [entity_id for entity_id, names in entity_names.items()
                            if any(_entity_mentions(hit.clause, name) for name in names)]
        if len(matched_entities) != 1:
            continue
        candidate_keys = [key for key in trend_index if key[0] == matched_entities[0]]
        if len(candidate_keys) != 1:
            continue
        resolved[candidate_keys[0]] = hit.direction
    return resolved


def _trend_consistency_status(draft_answer: str, final_text: str, claims: tuple[AllowedClaim, ...],
                              trend_index: dict[tuple[str, str], Direction] | None) -> str | None:
    """None if consistent; a fail-closed integrity_status string otherwise.

    Rules (A3.3 Design Memo v2 section 9): same normalized direction for a
    key present in both -> ok. Direction changed for a key present in both
    -> fail. A key present only in the FINAL text (the presenter introduced
    a trend assertion the validated draft never made) -> fail. A key present
    only in the draft (the presenter simply omitted it) -> ok, an omission
    is not a corruption.
    """
    if not trend_index:
        return None
    draft_directions = _extract_trend_directions(draft_answer, claims, trend_index)
    final_directions = _extract_trend_directions(final_text, claims, trend_index)
    if final_directions == AMBIGUOUS:
        return "presentation_trend_ambiguous"
    if draft_directions == AMBIGUOUS:
        # The validated draft itself could not be resolved here (should not
        # happen: coverage_guard already rejects an ambiguous clause before
        # this text is ever produced) -- nothing safe to compare against, so
        # this defensive branch treats it as "no known draft assertions"
        # rather than silently trusting the final text's claims.
        draft_directions = {}
    for key, direction in final_directions.items():
        if key not in draft_directions:
            return "presentation_trend_introduced"
        if draft_directions[key] != direction:
            return "presentation_trend_drift"
    return None


class OpenAIResponsesFinalPresenter:
    """One no-tools Responses call with conservative, fail-closed validation."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    def present(self, *, user_message: str, draft_answer: str, claims: tuple[AllowedClaim, ...] = (),
               trend_index: dict[tuple[str, str], Direction] | None = None) -> PresentationResult:
        started = time.monotonic()
        if not claims:
            # There is no factual presentation contract for free-form output.
            return PresentationResult(draft_answer, False, 0.0, None, None, "not_applicable")
        try:
            allowed = [{"claim_id": c.claim_id, "entity": c.entity_display or c.entity_id,
                        "metric": _metric_display_name(c.metric_key),
                        "period": c.period_display or c.period, "unit": c.unit,
                        "aggregation": c.aggregation} for c in claims]
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
            trend_status = _trend_consistency_status(draft_answer, content, claims, trend_index)
            if trend_status is not None:
                return _fallback(draft_answer, trend_status, started, self._model)
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
