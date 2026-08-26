"""Agent Behavior & Discoverability v1 goldens.

Four behaviour problems, none of them a governance gap: the capability existed
but was not discoverable (case 12), the evidence existed but the model could
not name it at synthesis time (case 09), the resolved entity/metric/period
existed but the retained history told the model it had no tools (case 03), and
analyst initiative gave way to premature clarification (case 15).

Every assertion here is about SURFACING. None of it may become a new authority:
the last two tests prove the guards decide exactly what they decided before.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.analyst_runtime.actions import (
    ActionRegistry, AnalyticsBreakdownAssetAction, AnalyticsLookupAssetAction,
    AnalyticsLookupFundAction, ListAssetsAction, ResolveEntityAction, RunSqlAction,
)
from tools.analyst_runtime.analyst_loop import _SYNTHESIS_INSTRUCTION, AnalystLoop
from tools.analyst_runtime.evidence_inventory import INVENTORY_HEADER, render_evidence_inventory
from tools.analyst_runtime.live_sandbox import LiveReadOnlySandbox
from tools.analyst_runtime.session import (
    ALPHA_EVIDENCE_INSTRUCTION, DEFAULT_INTERACTIVE_SYSTEM_PROMPT,
    OpenAIResponsesAnalystSession, _alpha_system_prompt,
)
from tools.analytics.catalog import CATALOG_PATH, load_metric_catalog
from tools.analytics.models import DimensionedAccess
from tools.analyst_runtime.transport import ModelResponse, ToolEvidence, ToolRequest

DB = Path("memory/agente_toesca_v2.db")


class RecordingTransport:
    """Scripted responses that also keeps every ModelRequest it received."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return next(self.responses)


def _session(transport, presenter=None):
    registry = ActionRegistry([
        RunSqlAction(LiveReadOnlySandbox(DB)),
        ResolveEntityAction(DB),
        AnalyticsLookupFundAction(DB),
        AnalyticsLookupAssetAction(DB),
        AnalyticsBreakdownAssetAction(DB),
        ListAssetsAction(DB),
    ])
    loop = AnalystLoop("sys", transport, registry, registry.tool_specs())
    return OpenAIResponsesAnalystSession(loop, presenter=presenter, db_path=DB)


# --------------------------------------------------------------------------
# A. capability discoverability (goldens 1, 2, 6)
# --------------------------------------------------------------------------

def test_capability_descriptions_are_generated_from_the_metric_catalog():
    """Golden 1: every metric the catalog marks eligible for an operation is
    named in that operation's description -- no hand-written metric text."""
    catalog = load_metric_catalog().metrics
    for action_class, grain in (
        (AnalyticsLookupFundAction, "fund"),
        (AnalyticsLookupAssetAction, "asset"),
    ):
        description = action_class(DB).tool_spec().description
        # A dimensioned metric belongs to its own capability whatever its
        # grain (it needs the basis/window arguments the plain lookups have no
        # contract for), so it is not expected in these two descriptions.
        expected = [m for m in catalog.values()
                    if m.entity_grain == grain and m.status == "active"
                    and not isinstance(m.access, DimensionedAccess)]
        assert expected, f"catalog defines no active {grain}-grain metric"
        for metric in expected:
            assert metric.key in description
            assert metric.display_name in description
        for metric in catalog.values():
            if metric.entity_grain != grain or isinstance(metric.access, DimensionedAccess):
                assert f"({metric.key}" not in description


def test_fund_ltv_capability_is_discoverable_in_its_tool_description():
    """Golden 6: the capability case 12 reconstructed with raw SQL."""
    description = AnalyticsLookupFundAction(DB).tool_spec().description

    assert "ltv_fondo" in description
    assert "LTV del fondo" in description
    # And the model is told which months it can actually ask for.
    assert "períodos" in description


def test_a_new_catalog_metric_appears_in_its_tool_description_with_no_code_change(tmp_path):
    """Golden 2: strict generalization. A throwaway metric added to a catalog
    fixture shows up in the relevant description with zero prompt edits."""
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["metrics"].append({
        "key": "zzz_metrica_de_prueba_fondo",
        "display_name": "Métrica de prueba del fondo",
        "description": "Métrica inventada sólo para este test.",
        "unit": "pct_0_100",
        "entity_grain": "fund",
        "period_grain": "month",
        "source_kind": "canonical",
        "access": {"kind": "derived_kpi", "entity_type": "fondo", "kpi": "zzz_prueba"},
        "aggregation": "non_additive",
        "allowed_dimensions": ["fund", "period"],
        "status": "active",
        "related_metrics": [],
        "methodology": "prueba_v1",
    })
    catalog_path = tmp_path / "catalog_test.yaml"
    catalog_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    fund_spec = AnalyticsLookupFundAction(DB, catalog_path=catalog_path).tool_spec()
    asset_spec = AnalyticsLookupAssetAction(DB, catalog_path=catalog_path).tool_spec()

    assert "zzz_metrica_de_prueba_fondo" in fund_spec.description
    assert "Métrica de prueba del fondo" in fund_spec.description
    assert "zzz_metrica_de_prueba_fondo" in fund_spec.parameters["properties"]["metric"]["enum"]
    # Grain routing stays catalog-driven: a fund metric never leaks into the
    # asset capability.
    assert "zzz_metrica_de_prueba_fondo" not in asset_spec.description


def test_a_metric_without_observable_periods_still_lists_its_identity(tmp_path):
    """The period hint degrades, it never guesses: an unobservable metric
    keeps its name in the description instead of blocking spec building."""
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["metrics"] = [m for m in raw["metrics"] if m["key"] == "ltv_fondo"]
    raw["metrics"][0]["related_metrics"] = []
    catalog_path = tmp_path / "catalog_only.yaml"
    catalog_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    description = AnalyticsLookupFundAction(tmp_path / "missing.db", catalog_path=catalog_path).tool_spec().description

    assert "ltv_fondo" in description
    assert "períodos" not in description


# --------------------------------------------------------------------------
# B. evidence discoverability in synthesis (goldens 3, 4, 5)
# --------------------------------------------------------------------------

def test_synthesis_inventory_names_the_evidence_the_investigation_really_produced():
    """Golden 3: real evidence_ids from a scripted investigation, no invention."""
    transport = RecordingTransport([
        ModelResponse("", [ToolRequest("call_assets", "list_assets", {"fund": "TRI", "period": "2026-06"})]),
        ModelResponse("Listo."),
        ModelResponse("ok", structured_output={"fragments": [{"type": "text", "text": "Listo."}],
                                               "canonical_metric_claims": [], "governed_dataset_claims": []}),
    ])
    session = _session(transport)

    session.ask("Dame los activos de TRI")

    synthesis_message = transport.requests[-1].message
    assert synthesis_message.startswith(_SYNTHESIS_INSTRUCTION)
    assert INVENTORY_HEADER in synthesis_message
    assert "evidence_id=call_assets" in synthesis_message
    assert "clase=governed_dataset" in synthesis_message
    assert "herramienta=list_assets" in synthesis_message
    assert "cobertura=" in synthesis_message
    # Identity only: the inventory never restates the payload.
    assert "vigente_hasta" not in synthesis_message


def test_inventory_is_absent_when_the_investigation_produced_no_evidence():
    """No evidence, no inventory: the reserved synthesis message stays
    byte-identical to the frozen instruction."""
    transport = RecordingTransport([
        ModelResponse("", [ToolRequest("sql", "run_sql", {"query": "SELECT 1"})]),
        ModelResponse("Nada relevante."),
        ModelResponse("ok", structured_output={"fragments": [{"type": "raw_text", "text": "Nada relevante."}],
                                               "canonical_metric_claims": [], "governed_dataset_claims": []}),
    ])

    _session(transport).ask("Explora")

    assert transport.requests[-1].message == _SYNTHESIS_INSTRUCTION


def test_render_evidence_inventory_is_derived_only_from_tool_evidence():
    evidence = [ToolEvidence(
        evidence_id="e1", evidence_class="governed_dataset",
        source={"tool_name": "analytics_breakdown_asset", "source_kind": "canonical"},
        scope={"fund": "TRI"}, semantic_contract={"metric_key": "noi_mensual_activo"},
        coverage={"status": "partial", "observed_count": 4, "eligible_count": 12, "universe_kind": "fund_assets"},
        facts=({"metric_key": "noi_mensual_activo", "value": 1.0, "unit": "clp", "entity_id": "INMOSA", "period": "2026-06"},),
    )]

    rendered = render_evidence_inventory(evidence)

    assert "evidence_id=e1" in rendered
    assert "metrica=noi_mensual_activo" in rendered
    assert "alcance=fund=TRI" in rendered
    assert "entidades=INMOSA" in rendered
    assert "cobertura=partial (4/12, universo=fund_assets)" in rendered
    assert "1.0" not in rendered
    assert render_evidence_inventory([]) == ""


def _governed_turn(claim_evidence_id: str):
    """One investigation producing governed evidence, then a synthesis whose
    single governed claim points at `claim_evidence_id`."""
    return [
        ModelResponse("", [ToolRequest("call_assets", "list_assets", {"fund": "PT", "period": "2026-06"})]),
        ModelResponse("Listo."),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "governed_dataset_ref", "claim_id": "c1"}],
            "canonical_metric_claims": [],
            "governed_dataset_claims": [{
                "claim_id": "c1", "evidence_id": claim_evidence_id, "metric_key": None,
                "entity_ids": ["Torre A", "Boulevard"], "period": "2026-06", "universe_kind": "fund_assets",
            }],
        }),
    ]


def test_inventory_does_not_change_authority_for_a_correct_citation():
    """Golden 4: a citation that binds still has to pass the same guard checks
    -- the inventory buys the model no credit it did not earn."""
    transport = RecordingTransport(_governed_turn("call_assets"))
    session = _session(transport)

    result = session.ask("Dame los activos de PT")

    assert INVENTORY_HEADER in transport.requests[-1].message
    assert result.presentation_integrity_status != "canonical_conflict"
    assert "Torre A" in result.text and "Boulevard" in result.text


def test_a_nonexistent_evidence_id_still_fails_closed_with_the_inventory_present():
    """Golden 5: literal fail-closed parity. The inventory names `call_assets`;
    a claim naming something else is rejected exactly as before this stage."""
    transport = RecordingTransport(_governed_turn("evidencia_inexistente"))
    session = _session(transport)

    result = session.ask("Dame los activos de PT")

    assert "evidence_id=call_assets" in transport.requests[-1].message
    assert result.presentation_integrity_status == "canonical_conflict"
    assert "no puedo confirmar" in result.text.lower()


# --------------------------------------------------------------------------
# C. follow-up continuity (golden 7)
# --------------------------------------------------------------------------

def test_followup_turn_keeps_the_resolved_entity_metric_and_period_and_drops_the_synthesis_round():
    """Golden 7: the surfacing mechanism itself. Turn 2's history must carry
    turn 1's real governed fact (entity + metric + period) through the
    normalized evidence it retains -- NOT through a replayed raw tool_request
    (that channel is the cross-turn recency-bias root cause and is closed at
    the turn boundary, see session.py's ``_stripped_for_cross_turn_history``)
    -- and must NOT carry the reserved synthesis instruction, which claims
    there are no tools."""
    turn_one = [
        ModelResponse("", [ToolRequest("call_ltv", "analytics_lookup_asset",
                                       {"metric": "ltv_activo", "assets": ["Apo3001"],
                                        "period": "2026-06", "period_end": None})]),
        ModelResponse("Listo."),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "canonical_metric_ref", "claim_id": "c1"}],
            "canonical_metric_claims": [{
                "claim_id": "c1", "evidence_id": "call_ltv", "metric_key": "ltv_activo",
                "value": _observed_ltv(), "unit": "ratio_0_1", "entity_id": "Apo3001", "period": "2026-06",
            }],
            "governed_dataset_claims": [],
        }),
    ]
    turn_two = [
        ModelResponse("Segunda vuelta."),
        ModelResponse("", structured_output={
            "request_kind": "prior_fact", "ambiguous": False,
            "compatible_evidence_ids": ["call_ltv"],
        }),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "text", "text": "Segunda vuelta."}],
            "canonical_metric_claims": [], "governed_dataset_claims": [], "derived_metric_claims": [],
        }),
    ]
    transport = RecordingTransport(turn_one + turn_two)
    session = _session(transport)

    session.ask("¿Cuál es el LTV de Apoquindo 3001 en junio de 2026?")
    session.ask("¿Y el mes anterior?")

    followup_history = transport.requests[-1].history
    facts = [fact for item in followup_history for result in item.tool_results
             if result.evidence is not None for fact in result.evidence.facts]
    assert any(fact.get("entity_id") == "Apo3001" and fact.get("metric_key") == "ltv_activo"
               and fact.get("period") == "2026-06" for fact in facts)
    # The raw call itself -- name, call_id, arguments -- is investigation
    # scratch, not conversational memory: it must NOT survive the turn
    # boundary (that replay is exactly the cross-turn recency-bias root
    # cause this fix closes).
    assert not any(item.tool_requests for item in followup_history)
    assert not any(_SYNTHESIS_INSTRUCTION in (item.text or "") for item in followup_history)
    # The user still sees the rendered answer, not the envelope JSON.
    assert any(item.role == "assistant" and "fragments" not in (item.text or "")
               for item in followup_history)
    # And turn 2 really is allowed tools again (its investigation round --
    # the request immediately before the reserved, tool-free finalize round
    # that now also runs for a toolless turn, see session.py).
    assert transport.requests[-3].tools


def _observed_ltv() -> float:
    import sqlite3

    connection = sqlite3.connect(f"{DB.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT valor FROM derived_kpi WHERE entidad_tipo='activo' AND kpi='ltv' "
            "AND entidad_key='Apo3001' AND periodo='2026-06'"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        pytest.skip("fixture LTV row absent from the live knowledge database")
    return row[0]


# --------------------------------------------------------------------------
# D. analyst initiative vs premature clarification (goldens 8, 9)
# --------------------------------------------------------------------------

def test_analyst_instruction_separates_open_angle_from_open_entity():
    """Golden 8: the distinction is stated once, generally, with no metric,
    fund, asset or KPI checklist attached to it."""
    prompt = _alpha_system_prompt(DEFAULT_INTERACTIVE_SYSTEM_PROMPT)
    normalized = " ".join(ALPHA_EVIDENCE_INSTRUCTION.split())

    assert "lo único abierto es el ángulo analítico" in normalized
    assert "entrega una lectura útil antes de pedir más precisión" in normalized
    assert "cambien materialmente qué entidad o qué alcance" in normalized
    assert ALPHA_EVIDENCE_INSTRUCTION in prompt
    for forbidden in ("LTV", "NOI", "vacancia", "TRI", "Apoquindo", "ltv_fondo"):
        assert forbidden not in ALPHA_EVIDENCE_INSTRUCTION


def test_a_vague_but_entity_resolved_request_can_be_investigated_and_answered():
    """Golden 8 (integration): nothing in the runtime forces a vague-but-
    resolvable analytical request into clarification -- the model investigates
    and the turn completes normally."""
    transport = RecordingTransport([
        ModelResponse("", [ToolRequest("call_ltv", "analytics_lookup_fund",
                                       {"metric": "ltv_fondo", "fund": "TRI",
                                        "period": "2026-06", "period_end": None})]),
        ModelResponse("Listo."),
        ModelResponse("ok", structured_output={
            "fragments": [{"type": "text", "text": "El fondo se ve estable."}],
            "canonical_metric_claims": [], "governed_dataset_claims": []}),
    ])
    session = _session(transport)

    result = session.ask("¿cómo viene TRI este trimestre?")

    assert result.termination_reason is None
    assert result.text == "El fondo se ve estable."


def test_true_entity_ambiguity_still_stops_the_turn_for_clarification():
    """Golden 9: regression. An entity that resolves to several canonical
    candidates still terminates the turn with clarification_required."""
    transport = RecordingTransport([
        ModelResponse("", [ToolRequest("call_resolve", "resolve_entity",
                                       {"query": "Apoquindo", "entity_types": ["asset"], "fund": None})]),
    ])
    session = _session(transport)

    result = session.ask("¿cómo viene Apoquindo este trimestre?")

    assert result.termination_reason == "clarification_required"
    assert "cuál buscas" in result.text.lower()
