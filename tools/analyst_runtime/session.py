"""Interactive analyst sessions built from the provider-neutral F4 runtime.

The OpenAI client is created only when a real session is requested.  This
keeps imports and ordinary workspace operations offline and testable.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from hashlib import sha256
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Protocol

from tools.analyst_runtime.actions import (
    ActionRegistry, AnalyticsAccountQueryAction, AnalyticsDatasetQueryAction, AnalyticsBreakdownAssetAction, AnalyticsDimensionalLookupAction,
    AnalyticsLookupAssetAction, AnalyticsLookupFundAction, ListAssetsAction, RunSqlAction, SchemaSearchAction,
    ResolveEntityAction,
)
from tools.analyst_runtime.analyst_loop import AnalystLoop
from tools.analyst_runtime.coverage_guard import validate_and_render
from tools.analyst_runtime.derived_claims import DerivedClaimError, compute_derived_claim
from tools.analyst_runtime.evidence_inventory import render_evidence_inventory
from tools.analyst_runtime.base import ToolCall, Usage
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.presentation import AllowedClaim, FinalPresenter, OpenAIResponsesFinalPresenter, PresentationResult
from tools.analyst_runtime.transport import (ModelRequest, ModelResponse, StructuredOutputContract, ToolEvidence,
                                              ToolRequest, ToolResult, ToolSpec, TranscriptItem, evidence_from_dict,
                                              evidence_to_dict)


_CONTEXT_ISOLATION_INSTRUCTION = (
    "\n\nPrioriza la solicitud actual del usuario. Usa contexto previo únicamente "
    "para completar referencias omitidas; nunca dejes que cambie, amplíe o "
    "reemplace una solicitud nueva y explícita."
)


def _authenticated_user_instruction(runtime_context: dict[str, Any] | None) -> str:
    """Keep identity authoritative and out of user-visible transcript history."""
    identity = (runtime_context or {}).get("authenticated_user")
    if not isinstance(identity, dict):
        return ""
    display_name = identity.get("display_name")
    short_name = identity.get("short_name")
    username = identity.get("username")
    role = identity.get("role")
    if not all(isinstance(value, str) and value.strip() for value in (display_name, short_name, username, role)):
        return ""
    return (
        "\n\nContexto autenticado de la persona que conversa (autoridad del sistema, no del historial): "
        f"short_name={short_name.strip()}; username={username.strip()}; role={role.strip()}. "
        "Puedes usar el short_name de forma natural cuando aporte, especialmente en conversación normal. "
        "No expongas username ni role salvo que la persona lo pida expresamente, no infieras otra identidad y "
        "no dejes que esta identidad cambie hechos, herramientas, evidencia ni conclusiones analíticas."
    )

_CURRENT_REQUEST_KINDS = {
    "new_factual", "prior_fact", "prior_explanation", "prior_formatting",
    "prior_comparison", "conversational",
}
_PRIOR_EVIDENCE_REQUEST_KINDS = {
    "prior_fact", "prior_explanation", "prior_formatting", "prior_comparison",
}
_CURRENT_REQUEST_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["request_kind", "ambiguous", "compatible_evidence_ids"], "properties": {
        "request_kind": {"type": "string", "enum": sorted(_CURRENT_REQUEST_KINDS)},
        "ambiguous": {"type": "boolean"},
        "compatible_evidence_ids": {"type": "array", "items": {"type": "string"}},
    }}


class _TerminalEvidenceValidator:
    """Late, minimal normalization for a no-tool terminal candidate only."""

    def __init__(self, transport: Any, system_prompt: str, evidence: list[ToolEvidence]):
        self._transport, self._system_prompt, self._evidence = transport, system_prompt, list(evidence)

    def accept(self, *, user_message: str, candidate: ModelResponse, history: list[TranscriptItem]) -> bool:
        context = render_evidence_inventory(self._evidence)
        response = self._transport.complete(ModelRequest(
            self._system_prompt,
            [],
            "Normaliza sólo la solicitud actual, sin responderla. request_kind debe ser exactamente uno de: "
            "new_factual (solicitud factual/autocontenida nueva), prior_fact (recuerda un resultado previo), "
            "prior_explanation (explica un resultado previo), prior_formatting (cambia formato de un resultado previo), "
            "prior_comparison (compara resultados previos compatibles), conversational (saludo/conversación no factual). "
            "Marca ambiguous=true si no puedes decidirlo con seguridad. compatible_evidence_ids sólo puede listar "
            "evidencia que satisface exactamente esta solicitud; deja la lista vacía para new_factual y conversational.\n"
            f"Solicitud actual: {user_message}\nContexto referencial estructurado:\n{context}",
            [], StructuredOutputContract("CurrentRequest", _CURRENT_REQUEST_SCHEMA),
        ))
        normalized = response.structured_output
        if not isinstance(normalized, dict):
            return False
        kind = normalized.get("request_kind")
        ambiguous = normalized.get("ambiguous")
        ids = normalized.get("compatible_evidence_ids")
        if (kind not in _CURRENT_REQUEST_KINDS or not isinstance(ambiguous, bool)
                or not isinstance(ids, list) or not all(isinstance(item, str) and item for item in ids)):
            return False
        if ambiguous:
            return False
        if kind == "conversational":
            return not ids
        if kind not in _PRIOR_EVIDENCE_REQUEST_KINDS:
            return False
        allowed = {item.evidence_id for item in self._evidence}
        return bool(ids) and len(ids) == len(set(ids)) and set(ids) <= allowed
from tools.analyst_runtime.synthesis_schema import SYNTHESIS_ENVELOPE_SCHEMA
from tools.analytics.humanize import entity_display_name, format_period, format_period_as_of, format_period_range
from tools.analytics.monetary import requested_monetary_unit

INTERACTIVE_EVIDENCE_INSTRUCTION = """Responde en español, distingue datos verificados de inferencias y usa la
herramienta SQL sólo para consultas de lectura cuando necesites evidencia."""

ALPHA_EVIDENCE_INSTRUCTION = """Responde en español. Distingue internamente entre evidencia, inferencias,
hipótesis y supuestos para decidir qué puedes afirmar. Usa la herramienta SQL
sólo para consultas de lectura cuando necesites evidencia. No conviertas esas
categorías en etiquetas visibles para el usuario; si una limitación o
incertidumbre es material para interpretar la respuesta, explícala de forma
natural dentro de la respuesta.

Antes de concluir, verifica que la evidencia alcance para el deliverable exacto,
no sólo para una observación prudente. Si la conclusión requiere relación entre
entidades, comparación, contribución relativa o cambio en el tiempo, reúne una
base comparable suficiente cuando una consulta de lectura razonable pueda cambiar
materialmente la respuesta. Si no puede obtenerse, explica naturalmente el
alcance de lo observado.

Trata los identificadores de entidades resueltos por las capacidades gobernadas
como entidades, aunque también puedan parecer abreviaturas temporales o
financieras en lenguaje natural.

Cuando la entidad y el alcance ya están suficientemente determinados y lo único
abierto es el ángulo analítico, investiga con las capacidades disponibles y
entrega una lectura útil antes de pedir más precisión. Pide aclaración sólo
cuando existan varias interpretaciones que cambien materialmente qué entidad o
qué alcance se está analizando."""

DEFAULT_INTERACTIVE_SYSTEM_PROMPT = (
    "Eres el Asistente Inmobiliario Toesca.\n"
    f"{INTERACTIVE_EVIDENCE_INSTRUCTION}"
    "\nPara consultas de cuentas contables u operacionales a nivel de activo, usa la capacidad "
    "analytics_account_query cuando el concepto solicitado esté disponible; es la autoridad de mappings, "
    "signo, unidad, cobertura y base contable. No sustituyas esa capacidad por búsquedas SQL de nombres de cuenta."
)

ALPHA_PRODUCT_VOICE = """\
Comunica como un analista inmobiliario competente que trabaja junto al equipo
de Toesca: natural, directo, profesional y preciso. Responde primero lo que
importa; profundiza sólo cuando agrega valor. Señala hallazgos y criterio
analítico cuando estén respaldados por la evidencia, y expresa la incertidumbre
de forma natural cuando no alcance para concluir.

La trazabilidad, verificación y procedencia son responsabilidades internas:
no las expongas rutinariamente. En respuestas simples, no agregues definiciones
del KPI, metodología, fuente, consultas, códigos de período ni advertencias
operativas salvo que el usuario las pida o sean materiales para interpretar el
resultado. Una respuesta completa no tiene que ser larga: si una frase resuelve
la pregunta, una frase es suficiente.

Las categorías epistemológicas sirven para razonar, no para organizar visualmente
la respuesta. No uses por defecto encabezados, etiquetas ni prefijos como dato
verificado, inferencia, hipótesis, supuesto o evidencia. Expresa hechos,
interpretaciones y limitaciones con lenguaje natural integrado en la respuesta.

Modela esa presentación así: ante una pregunta simple, responde "La vacancia fue
**5,9%**." y termina. Ante una pregunta analítica, responde "Lo más relevante es
la concentración de la vacancia en pocos activos. Esto sugiere que una mejora en
ellos podría mover materialmente el indicador." Si la incertidumbre es material,
di "El dato apunta a una mejora, aunque la cobertura del período es parcial."

Cuando una capacidad gobernada informe una base contable (por ejemplo,
devengado/EERR) y la pregunta del usuario esté formulada en términos de caja
("pagamos", "desembolsamos", "salió de la cuenta"), acláralo con una frase
natural y breve -- no la omitas ni la etiquetes con el nombre interno del
campo; dilo como lo diría un analista ("este monto es el gasto contable del
período, no necesariamente lo efectivamente pagado en caja").

Adapta la extensión y la presentación a la pregunta. Usa Markdown sólo cuando
ayude a leer: negritas para cifras o hallazgos clave, tablas para comparaciones
que lo justifiquen, y headings o listas sólo cuando una respuesta más extensa
los necesite. No conviertas respuestas simples en informes, no repitas
metodología o advertencias si no son materiales y no uses HTML, CSS ni estilos
inline. No suenes como un sistema de consultas ni como un chatbot genérico."""


def _alpha_system_prompt(core_prompt: str) -> str:
    """Reformulate Alpha's evidence rule without changing frozen F4 prompts."""
    if core_prompt.count(INTERACTIVE_EVIDENCE_INSTRUCTION) != 1:
        raise ValueError("Alpha prompt expected exactly once the interactive evidence instruction")
    alpha_core_prompt = core_prompt.replace(
        INTERACTIVE_EVIDENCE_INSTRUCTION,
        ALPHA_EVIDENCE_INSTRUCTION,
    )
    return f"{alpha_core_prompt}\n\n{ALPHA_PRODUCT_VOICE}"


@dataclass
class AnalystSessionResult:
    """Safe, provider-neutral result exposed to the workspace layer."""

    text: str
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    sql_queries: list[str] = field(default_factory=list)
    presentation_applied: bool | None = None
    presentation_provider: str | None = None
    presentation_model: str | None = None
    presentation_latency_ms: float | None = None
    presentation_integrity_status: str | None = None
    original_answer_hash: str | None = None
    presented_answer_hash: str | None = None
    termination_reason: str | None = None
    durable_memory: dict[str, Any] | None = None
    hydrated_claim_count: int = 0
    reused_evidence_count: int = 0
    fresh_evidence_count: int = 0


class AnalystSession(Protocol):
    def ask(self, text: str) -> AnalystSessionResult: ...


class AnalystSessionFactory(Protocol):
    def create(self, conversation: Any, visible_messages: list[Any], runtime_context: dict[str, Any] | None = None) -> AnalystSession: ...


@dataclass
class OpenAIResponsesTransport:
    """OpenAI Responses translation that preserves opaque history in memory."""

    client: Any
    model: str
    tool_specs: list[ToolSpec]

    def complete(self, request: ModelRequest) -> ModelResponse:
        request_input = self._render_history(request.history)
        if request.message:
            request_input.append({"role": "user", "content": request.message})
        kwargs = dict(
            model=self.model,
            instructions=request.system_prompt,
            input=request_input,
            tools=[_tool_spec_to_responses(spec) for spec in self.tool_specs],
            tool_choice="auto" if request.tools else "none",
            store=False,
        )
        if request.output_contract:
            kwargs["text"] = {"format": {"type": "json_schema", "name": request.output_contract.name, "schema": request.output_contract.schema, "strict": request.output_contract.strict}}
        response = self.client.responses.create(**kwargs)
        items = [_item_dict(item) for item in response.output]
        usage_raw = getattr(response, "usage", None)
        input_details = getattr(usage_raw, "input_tokens_details", None)
        output_details = getattr(usage_raw, "output_tokens_details", None)
        return ModelResponse(
            text=_visible_text(response, items),
            tool_requests=[
                ToolRequest(call_id=item.get("call_id", ""), name=item.get("name", ""),
                            arguments=_safe_json_loads(item.get("arguments")))
                for item in items if item.get("type") == "function_call"
            ],
            raw_items=items,
            usage=Usage(
                provider="openai", model=self.model, calls=1,
                input_tokens=getattr(usage_raw, "input_tokens", None),
                output_tokens=getattr(usage_raw, "output_tokens", None),
                reasoning_tokens=getattr(output_details, "reasoning_tokens", None),
                cached_tokens=getattr(input_details, "cached_tokens", None),
            ),
            structured_output=_structured_output(response, request.output_contract is not None),
        )

    @staticmethod
    def _render_history(history: list[TranscriptItem]) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for item in history:
            if item.role == "user":
                rendered.append({"role": "user", "content": item.text or ""})
            elif item.raw:
                # Opaque provider output survives ONLY for an item still part
                # of the in-progress investigation (see analyst_loop.py). A
                # completed turn's items have ``raw`` stripped by
                # ``_stripped_for_cross_turn_history`` before being retained,
                # so this branch never fires for historical tool traces.
                rendered.extend(item.raw)
                rendered.extend(
                    {"type": "function_call_output", "call_id": result.call_id, "output": result.content}
                    for result in item.tool_results
                )
            else:
                # Restart reconstruction and stripped cross-turn history both
                # have only visible transcript text; any ``tool_results`` kept
                # alongside them are for evidence lookup only (see
                # ``_evidence_for_current_answer``) and must NOT be echoed as
                # ``function_call_output`` without their originating
                # ``function_call`` -- that would send the provider an
                # orphaned tool result it never asked for.
                rendered.append({"role": "assistant", "content": item.text or ""})
        return rendered


class OpenAIResponsesAnalystSession:
    """Keeps the provider's opaque replay trajectory only in process memory."""

    def __init__(self, loop: AnalystLoop, history: list[TranscriptItem] | None = None, presenter: FinalPresenter | None = None, db_path: Path | None = None, durable_evidence: list[ToolEvidence] | None = None,
                 hydrated_claim_count: int = 0):
        self._loop = loop
        self._history: list[TranscriptItem] = list(history or [])
        self._presenter = presenter
        self._db_path = db_path
        self._durable_evidence = list(durable_evidence or [])
        self._hydrated_claim_count = hydrated_claim_count
        self._active_monetary_unit: str | None = None

    def ask(self, text: str) -> AnalystSessionResult:
        explicit_monetary_unit = requested_monetary_unit(text)
        if explicit_monetary_unit is not None:
            self._active_monetary_unit = explicit_monetary_unit
        requested_unit = explicit_monetary_unit or self._active_monetary_unit
        retained_history_length = len(self._history)
        historical_evidence = list(self._durable_evidence) + [
            result.evidence for item in self._history for result in item.tool_results
            if result.evidence is not None
        ]
        self._loop.terminal_validator = (
            _TerminalEvidenceValidator(self._loop.transport, self._loop.system_prompt, historical_evidence)
            if historical_evidence else None
        )
        investigation = self._loop.investigate(text, history=self._history)
        evidence = _evidence_for_current_answer(
            investigation, retained_history_length, self._durable_evidence,
        )
        canonical = [item for item in evidence if item.evidence_class == "canonical_metric" and len(item.facts) == 1]
        governed = [item for item in evidence if item.evidence_class == "governed_dataset"]
        supporting = [item for item in evidence if item.evidence_class == "controlled_sql"]
        validation = None
        no_evidence = None
        if investigation.termination_reason in {"clarification_required", "semantic_rejection"}:
            result = self._loop._legacy_finalize(investigation)
        elif not _has_account_coverage_none(investigation):
            # Any tool call -- not just a canonical/governed one -- may have
            # surfaced entity data (e.g. run_sql). Structured finalization plus
            # coverage_guard is what closes the raw-only enumeration bypass.
            #
            # A turn that made NO new tool call this round is included here
            # too (deliberately, no longer excluded): the "toolless" case is
            # exactly a follow-up like "which one was more, and by how much?"
            # that answers purely from evidence RETAINED from prior turns
            # (``evidence`` above walks the full round_trajectory, retained
            # history included). Sending it through the legacy path let the
            # model compute and print unbound arithmetic ("una diferencia de
            # 7.693,41 UF... 102% superior") straight into free text, with
            # none of coverage_guard's unbound-quantity / derived-claim
            # binding guarantees applied -- the exact fact-integrity gap this
            # fix closes. Routing it through the SAME structured envelope +
            # coverage_guard validation as a tool-calling turn means any
            # arithmetic must arrive as a derived_metric_ref bound against
            # already-validated claims, or the response fails closed exactly
            # as it would for a tool-calling turn. A genuinely toolless,
            # purely conversational turn with no quantitative facts at all
            # still passes: its envelope is just a text fragment with no
            # claims, and no tool call is forced to get there -- ``finalize``
            # below is one more no-tools model round, not a new investigation
            # round.
            result = self._loop.finalize(
                _investigation_for_current_synthesis(investigation, retained_history_length),
                StructuredOutputContract("SynthesisEnvelope", SYNTHESIS_ENVELOPE_SCHEMA),
                synthesis_context=render_evidence_inventory(evidence),
            )
            # ``finalize`` may relay an early deterministic termination from
            # the loop. Such a result has no model-produced synthesis envelope
            # and must never be forced through the structured-output parser.
            if result.turn.raw.get("termination_reason") not in {"clarification_required", "semantic_rejection"}:
                envelope = _materialize_governed_dataset_claims(
                    result.turn.raw.get("structured_output") or {}, governed,
                )
                envelope = _materialize_canonical_claims_from_governed_evidence(envelope, governed)
                result.turn.raw["structured_output"] = envelope
                validation = validate_and_render(envelope, canonical, governed, self._db_path,
                                                 requested_unit, supporting_evidence=supporting)
                result.turn.text = validation.content
                result.turn.raw.update(validation.trace)
        else:
            result = self._loop._legacy_finalize(investigation)
            # Only override with the canned NONE sentence when THIS turn
            # actually re-queried the account and got no evidence again.
            # Without this guard, a follow-up turn that asks a NEW question
            # about the same prior NONE (e.g. "does that mean it was zero?")
            # and makes no new tool call at all still matched stale
            # analytics_account_query evidence retained from a PRIOR turn's
            # history, and had the model's own (correct, on-topic) answer to
            # the new question silently replaced by a verbatim repeat of the
            # old answer. Gating on "this turn queried the account again"
            # keeps the override for its real purpose -- a fresh NONE result
            # -- without reaching backward into unrelated history.
            queried_account_this_turn = any(call.name == "analytics_account_query" for call in investigation.tool_calls)
            no_evidence = _account_no_evidence_payload(investigation) if queried_account_this_turn else None
            if no_evidence is not None:
                result.turn.text = _account_no_evidence_text(no_evidence, self._db_path)
                result.turn.raw["account_no_evidence"] = no_evidence
        turn = result.turn
        termination_reason = turn.raw.get("termination_reason")
        current_turn_items = investigation.round_trajectory[retained_history_length:]
        tool_error_this_turn = any(not tool_result.ok for item in current_turn_items for tool_result in item.tool_results)
        turn_failed = (
            termination_reason in {"clarification_required", "semantic_rejection"}
            or (validation is not None and not validation.valid)
            or tool_error_this_turn
        )
        self._history = _retained_history(investigation, turn.text, retained_history_length, text, turn_failed)
        has_tables = bool(validation is not None and validation.valid and validation.tables)
        presentation = (_clarification_presentation(turn.text) if termination_reason == "clarification_required"
                        else _semantic_rejection_presentation(turn.text) if termination_reason == "semantic_rejection"
                        else _conflict_presentation(turn.text) if validation and not validation.valid
                        # FinalPresenter's own protocol allows it to add Markdown
                        # "when it helps readability", including a claim_ref-backed
                        # table of its own -- harmless on its own, but when a
                        # governed table is ALSO about to be appended below, that
                        # freelanced structure duplicates it. Skipping the rephrase
                        # pass here (empty claims -> verbatim deterministic draft,
                        # see FinalPresenter.present) removes the only place a
                        # second table could come from, rather than trying to
                        # detect/strip one after the fact.
                        else self._present(turn.text, text, () if has_tables else
                                            _allowed_claims(result.turn.raw.get("structured_output") or {}, evidence, self._db_path,
                                                            requested_unit)))
        turn.raw["presenter_invoked"] = presentation.applied or (self._presenter is not None and not (validation and not validation.valid))
        # Tables are deterministic Markdown rendered by coverage_guard and
        # appended here, AFTER presentation -- never passed through
        # FinalPresenter's numeric-redaction rephrasing pass (see
        # CoverageValidation.tables docstring).
        tables = validation.tables if has_tables else ()
        final_text = presentation.content + ("\n\n" + "\n\n".join(tables) if tables else "")
        durable_memory = None
        envelope = result.turn.raw.get("structured_output") if isinstance(result.turn.raw, dict) else None
        if validation is not None and validation.valid and evidence and isinstance(envelope, dict):
            durable_memory = {"evidence": [_evidence_to_memory(item) for item in evidence], "envelope": envelope}
        elif no_evidence is not None:
            durable_memory = {"evidence": [{"evidence_id": "none:" + _answer_hash(json.dumps(no_evidence, sort_keys=True)),
                "evidence_class": "governed_dataset", "source": {"tool_name": "analytics_account_query"},
                "scope": {key: no_evidence.get(key) for key in ("entity", "entity_type", "period", "concept_id") if no_evidence.get(key) is not None},
                "semantic_contract": {"metric_key": no_evidence.get("concept_id")}, "provenance": no_evidence.get("lineage") or {},
                "coverage": no_evidence.get("coverage") or {"status": "none"}, "facts": []}],
                "envelope": {"canonical_metric_claims": [], "derived_metric_claims": []}}
        return AnalystSessionResult(
            text=final_text,
            usage=turn.usage,
            tool_calls=turn.tool_calls,
            sql_queries=[call.args["query"] for call in turn.tool_calls if call.name == "run_sql" and "query" in call.args],
            presentation_applied=presentation.applied,
            presentation_provider=presentation.provider,
            presentation_model=presentation.model,
            presentation_latency_ms=presentation.latency_ms,
            presentation_integrity_status=presentation.integrity_status,
            original_answer_hash=_answer_hash(turn.text),
            presented_answer_hash=_answer_hash(final_text),
            termination_reason=termination_reason,
            durable_memory=durable_memory,
            hydrated_claim_count=self._hydrated_claim_count,
            reused_evidence_count=len(self._durable_evidence),
            fresh_evidence_count=len(evidence) - len(self._durable_evidence),
        )

    def _present(self, draft: str, user_message: str, claims: tuple[AllowedClaim, ...] = ()) -> PresentationResult:
        if self._presenter is None:
            return PresentationResult(draft, False, None, None, None, "not_configured")
        return self._presenter.present(user_message=user_message, draft_answer=draft, claims=claims)


def _display_period(period_value: str, aggregation: str | None) -> str:
    """Deterministic period phrasing for an :class:`AllowedClaim`.

    ``period_value`` may be a single ``YYYY-MM`` or a ``start..end`` range
    (an aggregation over several months) -- both come from the same raw
    ``period`` field on the evidence fact, never a new source of truth.
    """
    if ".." in period_value:
        start, end = period_value.split("..", 1)
        return format_period_range(start, end)
    if aggregation == "point_in_time":
        return format_period_as_of(period_value)
    return format_period(period_value)


def _allowed_claims(envelope: dict[str, Any], evidence: list[ToolEvidence],
                     db_path: Path | None = None, requested_unit: str | None = None) -> tuple[AllowedClaim, ...]:
    by_evidence_id = {item.evidence_id: item for item in evidence}
    source_claims = envelope.get("canonical_metric_claims", [])
    if not isinstance(source_claims, list):
        return ()
    claims: list[AllowedClaim] = []
    facts_by_claim_id: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    keys = ("metric_key", "value", "unit", "entity_id", "period", "space_type", "space_types", "measurement_unit")
    for item in source_claims:
        if not isinstance(item, dict):
            return ()
        claim_id, evidence_id = item.get("claim_id"), item.get("evidence_id")
        source = by_evidence_id.get(evidence_id)
        if not isinstance(claim_id, str) or claim_id in seen or source is None:
            return ()
        fact = next((candidate for candidate in source.facts
                     if all(candidate.get(key) == item.get(key) for key in keys)), None)
        if fact is None:
            return ()
        seen.add(claim_id)
        facts_by_claim_id[claim_id] = fact
        aggregation = source.semantic_contract.get("aggregation")
        period_value = str(fact["period"])
        claims.append(AllowedClaim(
            claim_id=claim_id, evidence_id=source.evidence_id,
            metric_key=str(fact["metric_key"]), entity_id=str(fact["entity_id"]),
            value=float(fact["value"]), unit=str(fact["unit"]), period=period_value,
            aggregation=aggregation,
            lineage=deepcopy(source.provenance),
            # Precomputed, deterministic display strings so the presentation
            # LLM phrases the entity/period in natural language without ever
            # having to translate a raw key or YYYY-MM code itself.
            entity_display=entity_display_name(fact["entity_id"], db_path),
            period_display=_display_period(period_value, aggregation),
            requested_monetary_unit=requested_unit,
            presentation_conversion=deepcopy(fact.get("presentation_conversion")),
        ))

    # Derived (arithmetic) claims re-bind operands by claim_id against the
    # SAME already-validated facts above -- never against a display string --
    # so a difference/percent_change the presenter narrates is exactly the
    # value coverage_guard.validate_and_render already computed and rendered
    # into the draft. A derived claim referencing an unknown/unbound operand
    # is dropped fail-closed rather than guessed at.
    derived_source = envelope.get("derived_metric_claims", [])
    if isinstance(derived_source, list):
        for item in derived_source:
            if not isinstance(item, dict):
                continue
            claim_id = item.get("claim_id")
            if not isinstance(claim_id, str) or claim_id in seen:
                continue
            lhs_fact = facts_by_claim_id.get(item.get("lhs_claim_id"))
            rhs_fact = facts_by_claim_id.get(item.get("rhs_claim_id"))
            operation = item.get("operation")
            if lhs_fact is None or rhs_fact is None or not isinstance(operation, str):
                continue
            try:
                derived = compute_derived_claim(claim_id, operation, lhs_fact, rhs_fact,
                                                 item.get("lhs_claim_id"), item.get("rhs_claim_id"))
            except DerivedClaimError:
                continue
            seen.add(claim_id)
            claims.append(AllowedClaim(
                claim_id=claim_id, evidence_id="", metric_key=f"derived:{operation}",
                entity_id="", value=derived.value, unit=derived.unit, period="",
                aggregation=None, lineage=derived.lineage,
            ))
    return tuple(claims)


def _has_account_coverage_none(investigation: Any) -> bool:
    """A NONE account query has no numeric fact to bind.

    It must use the ordinary finalization path so the assistant can state the
    evidence limitation naturally, instead of sending an empty dataset through
    the deterministic fact renderer.
    """
    statuses = [
        call.trace["coverage"].get("status")
        for call in investigation.tool_calls
        if call.name == "analytics_account_query" and isinstance(call.trace, dict)
        and isinstance(call.trace.get("coverage"), dict)
    ]
    return bool(statuses) and set(statuses) == {"none"}


def _account_no_evidence_payload(investigation: Any) -> dict[str, Any] | None:
    account_payloads: list[dict[str, Any]] = []
    parent_scope: dict[str, Any] | None = None
    for item in reversed(investigation.round_trajectory):
        for result in reversed(item.tool_results):
            if result.evidence is not None and result.evidence.producer.tool_name == "list_assets":
                scope = result.evidence.scope
                if isinstance(scope.get("fund"), str):
                    parent_scope = {"entity": scope["fund"], "entity_type": "fund"}
            if result.trace.get("tool_name") != "analytics_account_query":
                continue
            coverage = result.trace.get("coverage")
            if not isinstance(coverage, dict) or coverage.get("status") != "none":
                continue
            try:
                payload = json.loads(result.content)
            except (TypeError, json.JSONDecodeError):
                return None
            if isinstance(payload, dict):
                account_payloads.append(payload)
    if not account_payloads:
        return None
    # A parent scope exists only when a governed enumeration established the
    # child universe. Every observed child here is NONE, so the parent is NONE
    # too; retain the requested parent rather than an arbitrary child.
    payload = account_payloads[0]
    if parent_scope:
        return {**payload, **parent_scope, "coverage": {**payload.get("coverage", {}), "status": "none", "composition": "all_children_none"}}
    return payload


def _account_no_evidence_text(payload: dict[str, Any], db_path: Path | None = None) -> str:
    """Human phrasing for a NONE account-coverage answer -- deterministic,
    metadata-driven (account-concept catalog display name, entity catalog,
    period formatter); never a raw internal identifier."""
    concept_id = payload.get("concept_id")
    concept = _account_concept_display_name(concept_id) if concept_id else "este concepto"
    raw_entity = payload.get("entity")
    entity = entity_display_name(raw_entity, db_path) if isinstance(raw_entity, str) else "la entidad solicitada"
    raw_period = payload.get("period")
    period = _display_period_phrase(raw_period) if isinstance(raw_period, str) else "el período solicitado"
    return (f"No encontré evidencia de gasto en {concept} para {entity} {period}. "
            "Esto no implica que el gasto haya sido cero, sólo que no hay datos gobernados que lo respalden.")


def _display_period_phrase(period_value: str) -> str:
    if ".." in period_value:
        start, end = period_value.split("..", 1)
        return format_period_range(start, end)
    return format_period(period_value)


def _account_concept_display_name(concept_id: str) -> str:
    try:
        from tools.analytics.account_concepts import AccountConceptCatalog
        return AccountConceptCatalog.load().get(concept_id).display_name.lower()
    except Exception:  # noqa: BLE001 -- display must never raise
        return str(concept_id).replace("_", " ")


def _evidence_for_current_answer(investigation: Any, retained_history_length: int,
                                 durable_evidence: list[ToolEvidence]) -> list[ToolEvidence]:
    """Select evidence without letting replay override a new tool-backed turn.

    ``round_trajectory`` starts with the retained transcript.  If this turn
    invokes any tool, its result is the current factual boundary: prior raw
    replay and durable facts may help the model plan, but cannot be cited in
    place of the evidence it just requested.  A genuinely tool-less follow-up
    still receives the prior validated facts it needs for comparison or
    arithmetic.
    """
    prior_items = investigation.round_trajectory[:retained_history_length]
    current_items = investigation.round_trajectory[retained_history_length:]
    current_results = [result for item in current_items for result in item.tool_results]
    current_evidence = [result.evidence for result in current_results if result.evidence is not None]
    if current_results:
        return current_evidence
    return list(durable_evidence) + [
        result.evidence for item in prior_items for result in item.tool_results
        if result.evidence is not None
    ]


def _materialize_governed_dataset_claims(envelope: dict[str, Any], evidence: list[ToolEvidence]) -> dict[str, Any]:
    """Make governed dataset claim identity evidence-owned, never model-owned."""
    if not isinstance(envelope, dict):
        return envelope
    by_id = {item.evidence_id: item for item in evidence if item.evidence_class == "governed_dataset"}
    materialized = deepcopy(envelope)
    claims = materialized.get("governed_dataset_claims")
    if not isinstance(claims, list):
        return materialized
    out = []
    for claim in claims:
        if not isinstance(claim, dict):
            out.append(claim); continue
        item = by_id.get(claim.get("evidence_id"))
        if item is None:
            out.append(claim); continue
        groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for fact in item.facts:
            groups.setdefault((fact.get("metric_key"), fact.get("period")), []).append(fact)
        if len(groups) != 1:
            out.append(claim); continue
        (metric_key, period), facts = next(iter(groups.items()))
        coverage = item.coverage or {}
        out.append({"claim_id": claim.get("claim_id"), "evidence_id": item.evidence_id,
                    "metric_key": metric_key,
                    "entity_ids": [str(fact.get("entity_id")) for fact in facts],
                    "period": period, "universe_kind": coverage.get("universe_kind")})
    materialized["governed_dataset_claims"] = out
    return materialized


def _materialize_canonical_claims_from_governed_evidence(envelope: dict[str, Any], evidence: list[ToolEvidence]) -> dict[str, Any]:
    """Make a canonical claim's identity evidence-owned when it cites ONE
    row inside a governed_dataset grouping (e.g. to promote a ranked/
    grouped row into a table cell).

    Once the entity that row belongs to is located, metric_key/period/
    value/unit are already fully determined by the evidence -- restating
    them is redundant, and a plain restatement slip (the observed failure:
    citing the query's requested filter period instead of a `group_by`
    aggregate's real, often-null, period) must not turn a real, evidence-
    backed row into a full coverage_guard rejection. This mirrors
    _materialize_governed_dataset_claims's treatment of
    governed_dataset_claims, applied to the sibling path where a single
    governed_dataset row is cited as a canonical_metric_claims entry.

    A claim whose (entity_id[, metric_key][, space_type]) does not locate
    EXACTLY one fact is left untouched, so coverage_guard's own binding
    still fails it closed exactly as before -- this never manufactures a
    fact that doesn't exist, and never resolves a genuine ambiguity on the
    model's behalf.
    """
    if not isinstance(envelope, dict):
        return envelope
    by_id = {item.evidence_id: item for item in evidence if item.evidence_class == "governed_dataset"}
    materialized = deepcopy(envelope)
    claims = materialized.get("canonical_metric_claims")
    if not isinstance(claims, list):
        return materialized
    out = []
    for claim in claims:
        if not isinstance(claim, dict):
            out.append(claim); continue
        item = by_id.get(claim.get("evidence_id"))
        if item is None:
            out.append(claim); continue
        matches = [fact for fact in item.facts
                   if fact.get("entity_id") == claim.get("entity_id")
                   and fact.get("space_type") == claim.get("space_type")]
        if claim.get("metric_key") is not None:
            matches = [fact for fact in matches if fact.get("metric_key") == claim.get("metric_key")]
        elif len({fact.get("metric_key") for fact in matches}) > 1:
            matches = []
        if len(matches) != 1:
            out.append(claim); continue
        fact = matches[0]
        out.append({**claim, "metric_key": fact.get("metric_key"), "period": fact.get("period"),
                    "value": fact.get("value"), "unit": fact.get("unit")})
    materialized["canonical_metric_claims"] = out
    return materialized


def _investigation_for_current_synthesis(investigation: Any, retained_history_length: int) -> Any:
    """Keep stale replay out of a tool-backed turn's final synthesis.

    The current tools have already resolved a new explicit request.  Their
    tool-free synthesis must therefore see only this turn's trajectory;
    otherwise the model can repeat a prior answer despite correct current
    tool execution.  Tool-less follow-ups retain prior trajectory normally.
    """
    current_items = investigation.round_trajectory[retained_history_length:]
    if any(item.tool_results for item in current_items):
        return replace(investigation, round_trajectory=list(current_items))
    return investigation


def _stripped_for_cross_turn_history(item: TranscriptItem) -> TranscriptItem:
    """Drop provider wire trace at a completed turn boundary.

    Raw traces are investigation state, not conversational memory: a turn's
    ``function_call``/``function_call_output`` items, ``call_id``s and
    invocation trace exist so the SAME investigation can chain tool rounds
    (see analyst_loop.py's ``investigate``). Once a turn ends, replaying that
    trace into the NEXT turn's planner input has no conversational purpose --
    it only biases the next turn's first tool choice toward whatever domain
    the last turn happened to use (the recency-bias root cause this closes).

    What must survive for legitimate follow-ups is the semantic outcome, not
    the mechanism: each ``ToolResult.evidence`` (a normalized, already-bound
    fact) is kept so evidence pooling (``ask()``'s ``historical_evidence``,
    ``_evidence_for_current_answer``) keeps working; the wire-only fields
    (``content``, ``trace``, ``call_id``) that only ever fed
    ``function_call_output`` rendering are cleared alongside ``raw`` so
    ``_render_history`` cannot echo them either.
    """
    if item.role != "assistant":
        return item
    return replace(
        item, raw=None, tool_requests=[],
        tool_results=[replace(result, call_id="", content="", trace={}) for result in item.tool_results],
    )


def _retained_history(investigation: Any, answer_text: str, retained_history_length: int,
                       user_text: str, turn_failed: bool) -> list[TranscriptItem]:
    """Cross-turn retention policy (AnalystLoop deliberately leaves it to the
    session, see analyst_loop.py's docstring).

    Retain the INVESTIGATION trajectory -- the user's question plus the real
    tool calls and their results, which is where the resolved entity, metric
    and period actually live in structured form -- followed by the answer the
    user saw. The finalization exchange is dropped: its user message is the
    reserved synthesis instruction ("this is your last intervention, you have
    no tools, do not open new lines of investigation"), which is true of that
    round only. Replaying it as conversation history told the model, on the
    NEXT turn, that it had no tools -- so a follow-up that merely shifts the
    period was answered by refusing instead of by looking it up. Its assistant
    message is the raw SynthesisEnvelope JSON, which is likewise noise next
    turn; the rendered answer replaces it.

    A turn that ends WITHOUT accepted evidence (a tool error, a rejected
    structured synthesis, a safe refusal) is different: its tool trajectory
    is planner scratch -- schema lookups, an erroring or inconclusive tool
    call, a fallback attempt -- not settled fact. Replaying that scratch as
    ordinary history biases the NEXT turn's own tool choice toward whatever
    domain this failed attempt happened to be exploring, even when the next
    request is explicit and unrelated (see test_stale_structured_output.py's
    failed-turn-lifecycle tests). Only the ordinary fact that the exchange
    happened -- the user's question and the answer they saw -- may survive;
    the tool_requests/tool_results are dropped, so `ask()`'s historical
    evidence pool for the next turn drops them too, automatically.
    """
    if turn_failed:
        history = list(investigation.round_trajectory[:retained_history_length])
        history.append(TranscriptItem(role="user", text=user_text))
        history.append(TranscriptItem(role="assistant", text=answer_text))
        return [_stripped_for_cross_turn_history(item) for item in history[-12:]]
    history = list(investigation.round_trajectory)
    if investigation.termination_reason != "model_terminal":
        # The trajectory already ends with the model's own answer when
        # ``model_terminal``; otherwise append the rendered synthesis text.
        history.append(TranscriptItem(role="assistant", text=answer_text))
    # Durable evidence is persisted separately.  Bound transient provider
    # replay so old clarification/tool trajectories cannot outrank a new,
    # self-contained user request after a long topic-switching conversation.
    # Every item -- including ones already retained (and already stripped)
    # from a prior turn -- passes through the cross-turn strip again here;
    # for those it is a no-op, and for this turn's own items it is what
    # removes their raw provider trace before they become history.
    return [_stripped_for_cross_turn_history(item) for item in history[-12:]]


def _clarification_presentation(content: str) -> PresentationResult:
    return PresentationResult(content, False, None, None, None, "clarification_required")


def _semantic_rejection_presentation(content: str) -> PresentationResult:
    return PresentationResult(content, False, None, None, None, "semantic_rejection")


def _conflict_presentation(content: str) -> PresentationResult:
    return PresentationResult(content, False, None, None, None, "canonical_conflict")


class OpenAIResponsesAnalystSessionFactory:
    """Build the real local F4 session without any benchmark dependency."""

    def __init__(
        self,
        knowledge_db_path: Path,
        system_prompt: str = DEFAULT_INTERACTIVE_SYSTEM_PROMPT,
        model: str = "gpt-5.6-terra",
        client_factory: Callable[[], Any] | None = None,
        presenter_factory: Callable[[Any, str], FinalPresenter] | None = OpenAIResponsesFinalPresenter,
    ):
        self.knowledge_db_path = Path(knowledge_db_path)
        self.system_prompt = _alpha_system_prompt(system_prompt)
        self.model = model
        self._client_factory = client_factory or _default_openai_client
        self._presenter_factory = presenter_factory

    def create(self, conversation: Any, visible_messages: list[Any], runtime_context: dict[str, Any] | None = None) -> AnalystSession:
        # A restarted process has no safe provider-native replay.  Replaying
        # persisted visible prose can still carry a stale answer into a new,
        # explicit request, so structured Durable Context is the only
        # cross-process conversational context.
        del conversation
        sandbox = LiveReadOnlySandbox(self.knowledge_db_path)
        action = RunSqlAction(sandbox=sandbox)
        registry = ActionRegistry([
            action,
            ResolveEntityAction(self.knowledge_db_path),
            SchemaSearchAction(self.knowledge_db_path),
            AnalyticsLookupFundAction(self.knowledge_db_path),
            AnalyticsLookupAssetAction(self.knowledge_db_path),
            AnalyticsBreakdownAssetAction(self.knowledge_db_path),
            AnalyticsDimensionalLookupAction(self.knowledge_db_path),
            AnalyticsDatasetQueryAction(self.knowledge_db_path),
            AnalyticsAccountQueryAction(self.knowledge_db_path),
            ListAssetsAction(self.knowledge_db_path),
        ])
        client = self._client_factory()
        transport = OpenAIResponsesTransport(client, self.model, registry.tool_specs())
        # A restart has no provider-native items, but its visible transcript is
        # still transient context: keep the same bounded tail used by native
        # in-process replay. Durable claims/evidence are hydrated separately.
        history: list[TranscriptItem] = []
        durable = (runtime_context or {}).get("durable_analytical_context", {})
        durable_evidence = [_memory_to_evidence(item) for item in durable.get("evidence", []) if isinstance(item, dict)]
        claims = durable.get("claims", [])
        if claims:
            history.append(TranscriptItem(role="assistant", text=(
                "Contexto analítico durable validado (usa estas claims sólo mediante el contrato estructurado; "
                "no copies cifras a prose). Si el usuario pide actual/latest/refresh, consulta evidencia gobernada nueva: " +
                json.dumps({"canonical_metric_claims": claims, "derived_metric_claims": durable.get("derived_claims", [])}, ensure_ascii=False))))
        presenter = self._presenter_factory(client, self.model) if self._presenter_factory else None
        return OpenAIResponsesAnalystSession(
            AnalystLoop(self.system_prompt + _CONTEXT_ISOLATION_INSTRUCTION + _authenticated_user_instruction(runtime_context), transport, registry, registry.tool_specs()), history=history, presenter=presenter,
            db_path=self.knowledge_db_path, durable_evidence=durable_evidence,
            hydrated_claim_count=len(claims) + len(durable.get("derived_claims", [])),
        )


def _default_openai_client() -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required to create a live analyst session")
    from openai import OpenAI

    return OpenAI(max_retries=0)


def _evidence_to_memory(item: ToolEvidence) -> dict[str, Any]:
    """Serialize only validated factual evidence; never provider/tool transcripts."""
    return evidence_to_dict(item)


def _memory_to_evidence(item: dict[str, Any]) -> ToolEvidence:
    return evidence_from_dict(deepcopy(item))


def _item_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    return dict(item)


def _visible_text(response: Any, items: list[dict[str, Any]]) -> str:
    if getattr(response, "output_text", None):
        return response.output_text
    return "".join(
        content.get("text", "")
        for item in items if item.get("type") == "message"
        for content in item.get("content") or [] if content.get("type") == "output_text"
    )


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _structured_output(response: Any, required: bool) -> dict[str, Any] | None:
    if not required: return None
    value = getattr(response, "output_parsed", None)
    if hasattr(value, "model_dump"): value = value.model_dump()
    if not isinstance(value, dict):
        # `client.responses.create()` (unlike the `.parse()` helper) never
        # sets `output_parsed`; the real, provider-validated JSON comes back
        # as `output_text` and must be decoded explicitly.
        text = getattr(response, "output_text", None)
        try:
            value = json.loads(text) if text else None
        except json.JSONDecodeError:
            value = None
    if not isinstance(value, dict): raise ValueError("structured_output_required")
    return value


def _tool_spec_to_responses(spec: ToolSpec) -> dict[str, Any]:
    return {"type": "function", "name": spec.name, "description": spec.description, "parameters": spec.parameters}


def _answer_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
