"""Fund Financial Surface v1 -- conversation-level QA through the real stack.

Every test here drives the PRODUCTION session that
`OpenAIResponsesAnalystSessionFactory` builds (real ActionRegistry, real
system prompt, real evidence inventory, real coverage_guard, real
deterministic renderer) against the read-only knowledge database. Only the
provider transport is scripted, because that is the one component that would
otherwise be a network call; the model's tool calls and synthesis envelopes
are exactly the shapes the schema allows it to emit.

What this proves that an executor-level test cannot: that a figure survives
the whole path question -> governed tool -> ToolEvidence -> bound claim ->
coverage_guard -> human sentence, and that an unbound one does not.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.analyst_runtime.session import OpenAIResponsesAnalystSessionFactory
from tools.analyst_runtime.transport import ModelResponse, ToolRequest

DB = Path("memory/agente_toesca_v2.db")

_ARGS = {"metric": None, "fund": None, "period": None, "period_end": None, "aggregation": None,
         "series": None, "credit": None, "valuation_basis": None, "return_basis": None,
         "return_window": None, "flow_type": None}


def args(**kwargs) -> dict:
    return {**_ARGS, **kwargs}


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.index = 0

    def complete(self, request):
        response = self.responses[self.index]
        if request.tools and response.structured_output is not None:
            # The scripted investigation is over: the next scripted item is the
            # synthesis envelope, which the loop only asks for in its tool-free
            # finalization round. Close investigation with a terminal reply
            # instead of writing that boilerplate into every script.
            return ModelResponse("listo")
        self.index += 1
        return response


def build_session(responses, runtime_context=None):
    factory = OpenAIResponsesAnalystSessionFactory(DB, client_factory=lambda: object(),
                                                   presenter_factory=None)
    session = factory.create(None, [], runtime_context)
    session._loop.transport = ScriptedTransport(responses)
    return session


def lookup(call_id, **kwargs) -> ToolRequest:
    return ToolRequest(call_id, "analytics_lookup_dimensional", args(**kwargs))


def claim(claim_id: str, evidence_id: str, fact: dict) -> dict:
    """Reproduce one governed row exactly as the synthesis schema requires."""
    return {"claim_id": claim_id, "evidence_id": evidence_id,
            "metric_key": fact["metric_key"], "value": fact["value"], "unit": fact["unit"],
            "entity_id": fact["entity_id"], "period": fact["period"],
            "space_type": None, "space_types": None, "measurement_unit": None}


def envelope(fragments, canonical=(), governed=(), derived=(), tables=()):
    return ModelResponse("ok", structured_output={
        "fragments": list(fragments), "canonical_metric_claims": list(canonical),
        "governed_dataset_claims": list(governed), "derived_metric_claims": list(derived),
        "table_claims": list(tables)})


def governed_facts(call_id, **kwargs):
    """Execute the same governed call the scripted model will make, so the
    test's expected claims are the tool's real output, never handwritten."""
    factory = OpenAIResponsesAnalystSessionFactory(DB, client_factory=lambda: object(),
                                                   presenter_factory=None)
    registry = factory.create(None, [])._loop.action_executor
    result = registry.execute(lookup(call_id, **kwargs))
    assert result.ok, result.content
    return result


# --------------------------------------------------------------------------
# Trajectory 1: TIR, series follow-up, window follow-up, table
# --------------------------------------------------------------------------

def test_trajectory_market_tir_series_follow_up_and_table():
    a = governed_facts("t_a", metric="tir_serie", fund="TRI", period="2026-06", series="A",
                       return_basis="market", return_window="since_inception").evidence.facts[0]
    session = build_session([
        ModelResponse("", [lookup("t_a", metric="tir_serie", fund="TRI", period="2026-06", series="A",
                                  return_basis="market", return_window="since_inception")]),
        envelope([{"type": "text", "text": "La TIR bursátil desde inicio de la serie A de TRI fue "},
                  {"type": "canonical_metric_ref", "claim_id": "c1"},
                  {"type": "text", "text": " a junio de 2026."}],
                 canonical=[claim("c1", "t_a", a)]),
    ])

    first = session.ask("¿Cuál fue la TIR bursátil desde inicio de TRI serie A en junio 2026?")

    assert "-7,29%" in first.text
    assert first.durable_memory is not None
    contract = first.durable_memory["evidence"][0]["semantic_contract"]
    assert contract["metric_key"] == "tir_serie"
    assert contract["dimensions"] == {"return_basis": "market", "return_window": "since_inception",
                                      "series": "A"}

    # "¿Y la C?" -- same metric/basis/window, only the series changes.
    c = governed_facts("t_c", metric="tir_serie", fund="TRI", period="2026-06", series="C",
                       return_basis="market", return_window="since_inception").evidence.facts[0]
    session._loop.transport = ScriptedTransport([
        ModelResponse("", [lookup("t_c", metric="tir_serie", fund="TRI", period="2026-06", series="C",
                                  return_basis="market", return_window="since_inception")]),
        envelope([{"type": "text", "text": "Para la serie C fue "},
                  {"type": "canonical_metric_ref", "claim_id": "c2"}, {"type": "text", "text": "."}],
                 canonical=[claim("c2", "t_c", c)]),
    ])
    second = session.ask("¿Y la C?")
    assert "-6,19%" in second.text
    assert second.durable_memory["evidence"][-1]["semantic_contract"]["dimensions"]["series"] == "C"

    # "Ahora U12M." -- only the window changes.
    u12 = governed_facts("t_u", metric="tir_serie", fund="TRI", period="2026-06", series="C",
                         return_basis="market", return_window="trailing_12m").evidence.facts[0]
    session._loop.transport = ScriptedTransport([
        ModelResponse("", [lookup("t_u", metric="tir_serie", fund="TRI", period="2026-06", series="C",
                                  return_basis="market", return_window="trailing_12m")]),
        envelope([{"type": "text", "text": "En los últimos 12 meses fue "},
                  {"type": "canonical_metric_ref", "claim_id": "c3"}, {"type": "text", "text": "."}],
                 canonical=[claim("c3", "t_u", u12)]),
    ])
    third = session.ask("Ahora U12M.")
    assert third.durable_memory["evidence"][-1]["semantic_contract"]["dimensions"]["return_window"] == "trailing_12m"

    # "Pon las tres series en una tabla." -- one governed breakdown, three cells.
    breakdown = governed_facts("t_all", metric="tir_serie", fund="TRI", period="2026-06",
                               return_basis="market", return_window="since_inception").evidence
    cells = [claim(f"s{index}", "t_all", fact) for index, fact in enumerate(breakdown.facts)]
    session._loop.transport = ScriptedTransport([
        ModelResponse("", [lookup("t_all", metric="tir_serie", fund="TRI", period="2026-06",
                                  return_basis="market", return_window="since_inception")]),
        envelope([{"type": "text", "text": "TIR bursátil desde inicio por serie:"}],
                 canonical=cells,
                 tables=[{"claim_id": "tbl", "cell_claim_ids": [item["claim_id"] for item in cells],
                          "order_by": None}]),
    ])
    fourth = session.ask("Pon las tres series en una tabla.")
    assert "| Serie |" in fourth.text
    assert "serie A de TRI" in fourth.text and "serie I de TRI" in fourth.text
    assert "-7,29%" in fourth.text and "-6,19%" in fourth.text and "-11,91%" in fourth.text


# --------------------------------------------------------------------------
# Trajectory 2: market unit value -> book unit value -> discount
# --------------------------------------------------------------------------

def test_trajectory_unit_values_and_governed_discount():
    market = governed_facts("u_m", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                            series="A", valuation_basis="market").evidence.facts[0]
    book = governed_facts("u_b", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                          series="A", valuation_basis="book").evidence.facts[0]

    session = build_session([
        ModelResponse("", [lookup("u_m", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                                  series="A", valuation_basis="market")]),
        envelope([{"type": "text", "text": "La cuota bursátil de la serie A cerró marzo en "},
                  {"type": "canonical_metric_ref", "claim_id": "m"}, {"type": "text", "text": "."}],
                 canonical=[claim("m", "u_m", market)]),
    ])
    first = session.ask("¿Cuál era el valor cuota bursátil de TRI A en marzo 2026, en pesos?")
    assert "16.839 CLP" in first.text

    session._loop.transport = ScriptedTransport([
        ModelResponse("", [lookup("u_b", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                                  series="A", valuation_basis="book")]),
        envelope([{"type": "text", "text": "El valor contable de la misma serie fue "},
                  {"type": "canonical_metric_ref", "claim_id": "b"}, {"type": "text", "text": "."}],
                 canonical=[claim("b", "u_b", book)]),
    ])
    second = session.ask("¿Y el contable?")
    assert "32.342 CLP" in second.text

    # Discount is DERIVED from the two already-bound claims, never arithmetic
    # written in prose.
    session._loop.transport = ScriptedTransport([
        ModelResponse("", [
            lookup("d_b", metric="valor_cuota_serie", fund="TRI", period="2026-03", series="A",
                   valuation_basis="book"),
            lookup("d_m", metric="valor_cuota_serie", fund="TRI", period="2026-03", series="A",
                   valuation_basis="market"),
        ]),
        envelope([{"type": "text", "text": "La serie A transa con "},
                  {"type": "derived_metric_ref", "claim_id": "disc"},
                  {"type": "text", "text": " respecto de su valor libro de marzo."}],
                 canonical=[claim("cb", "d_b", book), claim("cm", "d_m", market)],
                 derived=[{"claim_id": "disc", "operation": "discount_premium",
                           "lhs_claim_id": "cb", "rhs_claim_id": "cm"}]),
    ])
    third = session.ask("¿A qué descuento estaba respecto de libro, en pesos?")
    assert "un descuento de 47,9%" in third.text


def test_discount_across_different_periods_fails_closed():
    """A daily market quote against an older book close is exactly the
    unaligned comparison the surface must refuse."""
    market = governed_facts("x_m", metric="valor_cuota_serie", fund="TRI", period="2026-08",
                            series="A", valuation_basis="market").evidence.facts[0]
    book = governed_facts("x_b", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                          series="A", valuation_basis="book").evidence.facts[0]
    session = build_session([
        ModelResponse("", [
            lookup("x_b", metric="valor_cuota_serie", fund="TRI", period="2026-03", series="A",
                   valuation_basis="book"),
            lookup("x_m", metric="valor_cuota_serie", fund="TRI", period="2026-08", series="A",
                   valuation_basis="market"),
        ]),
        envelope([{"type": "text", "text": "Transa con "},
                  {"type": "derived_metric_ref", "claim_id": "disc"}, {"type": "text", "text": "."}],
                 canonical=[claim("cb", "x_b", book), claim("cm", "x_m", market)],
                 derived=[{"claim_id": "disc", "operation": "discount_premium",
                           "lhs_claim_id": "cb", "rhs_claim_id": "cm"}]),
    ])

    result = session.ask("¿A qué descuento transa TRI A hoy respecto de libro?")

    assert "descuento de" not in result.text
    assert result.presentation_integrity_status == "canonical_conflict"


# --------------------------------------------------------------------------
# Trajectory 3: distributions and capital reductions
# --------------------------------------------------------------------------

def test_trajectory_distributions_then_capital_reductions():
    dividends = governed_facts("v_d", metric="distribucion_por_cuota_serie", fund="TRI",
                               period="2025-01", period_end="2025-12", series="A",
                               flow_type="dividend").evidence
    cells = [claim(f"d{index}", "v_d", fact) for index, fact in enumerate(dividends.facts)]
    session = build_session([
        ModelResponse("", [lookup("v_d", metric="distribucion_por_cuota_serie", fund="TRI",
                                  period="2025-01", period_end="2025-12", series="A",
                                  flow_type="dividend")]),
        envelope([{"type": "text", "text": "La serie A repartió cuatro dividendos por cuota en 2025:"}],
                 canonical=cells,
                 tables=[{"claim_id": "tb", "cell_claim_ids": [item["claim_id"] for item in cells],
                          "order_by": None}]),
    ])

    first = session.ask("Muéstrame los dividendos de TRI A durante 2025.")
    assert "| Período |" in first.text
    assert "abr-2025" in first.text and "dic-2025" in first.text
    assert "0,0066 UF" in first.text  # a sub-UF per-unit amount never rounds to 0

    # No capital reductions exist for this series: the governed result is
    # empty and the answer must say so without claiming a zero.
    empty = governed_facts("v_r", metric="distribucion_por_cuota_serie", fund="TRI",
                           period="2025-01", period_end="2025-12", series="A",
                           flow_type="capital_reduction")
    assert empty.evidence is None
    assert '"status": "none"' in empty.content

    session._loop.transport = ScriptedTransport([
        ModelResponse("", [lookup("v_r", metric="distribucion_por_cuota_serie", fund="TRI",
                                  period="2025-01", period_end="2025-12", series="A",
                                  flow_type="capital_reduction")]),
        envelope([{"type": "text", "text": "No hay registro de disminuciones de capital de la serie A "
                                           "en ese año; eso no permite afirmar que no existieran."}]),
    ])
    second = session.ask("¿Hubo disminuciones de capital también?")
    assert "disminuciones de capital" in second.text


# --------------------------------------------------------------------------
# Trajectory 4: capital and units
# --------------------------------------------------------------------------

def test_trajectory_subscribed_capital_then_units():
    capital = governed_facts("k_c", metric="capital_suscrito_serie", fund="TRI", period="2026-08",
                             series="A").evidence.facts[0]
    session = build_session([
        ModelResponse("", [lookup("k_c", metric="capital_suscrito_serie", fund="TRI",
                                  period="2026-08", series="A")]),
        envelope([{"type": "text", "text": "La última observación de capital suscrito de la serie A es "},
                  {"type": "canonical_metric_ref", "claim_id": "k"}, {"type": "text", "text": "."}],
                 canonical=[claim("k", "k_c", capital)]),
    ])
    first = session.ask("¿Cuál es el capital suscrito de TRI A?")
    assert "478.441 UF" in first.text

    units = governed_facts("k_u", metric="cuotas_en_circulacion_serie", fund="TRI", period="2026-08",
                           series="A").evidence.facts[0]
    session._loop.transport = ScriptedTransport([
        ModelResponse("", [lookup("k_u", metric="cuotas_en_circulacion_serie", fund="TRI",
                                  period="2026-08", series="A")]),
        envelope([{"type": "text", "text": "Tiene "}, {"type": "canonical_metric_ref", "claim_id": "u"},
                  {"type": "text", "text": " en circulación."}],
                 canonical=[claim("u", "k_u", units)]),
    ])
    second = session.ask("¿Y cuántas cuotas tiene?")
    assert "475.667 cuotas" in second.text


# --------------------------------------------------------------------------
# Trajectory 5: ambiguity
# --------------------------------------------------------------------------

def test_bare_tir_question_asks_back_instead_of_choosing_a_variant():
    session = build_session([
        ModelResponse("", [lookup("amb", metric="tir_serie", fund="TRI", period="2026-06")]),
    ])

    result = session.ask("¿Cuál es la TIR de TRI?")

    assert result.termination_reason == "semantic_rejection"
    assert "base de la rentabilidad" in result.text
    assert "bursátil" in result.text and "contable" in result.text
    assert "desde inicio" in result.text and "U12M" in result.text


def test_a_fully_specified_question_does_not_clarify_gratuitously():
    fact = governed_facts("ok", metric="dividend_yield_serie", fund="TRI", period="2026-06",
                          series="A", valuation_basis="market").evidence.facts[0]
    session = build_session([
        ModelResponse("", [lookup("ok", metric="dividend_yield_serie", fund="TRI", period="2026-06",
                                  series="A", valuation_basis="market")]),
        envelope([{"type": "text", "text": "El dividend yield bursátil fue "},
                  {"type": "canonical_metric_ref", "claim_id": "dy"}, {"type": "text", "text": "."}],
                 canonical=[claim("dy", "ok", fact)]),
    ])

    result = session.ask("DY bursátil de TRI A en junio 2026.")

    assert result.termination_reason != "semantic_rejection"
    assert "2,64%" in result.text


# --------------------------------------------------------------------------
# Claim binding integrity
# --------------------------------------------------------------------------

def test_a_financial_figure_written_as_free_text_is_rejected():
    fact = governed_facts("nb", metric="tir_serie", fund="TRI", period="2026-06", series="A",
                          return_basis="market", return_window="since_inception").evidence.facts[0]
    session = build_session([
        ModelResponse("", [lookup("nb", metric="tir_serie", fund="TRI", period="2026-06", series="A",
                                  return_basis="market", return_window="since_inception")]),
        envelope([{"type": "text", "text": "La TIR bursátil desde inicio fue -7,29%."}],
                 canonical=[claim("c", "nb", fact)]),
    ])

    result = session.ask("¿Cuál fue la TIR bursátil desde inicio de TRI A en junio 2026?")

    assert result.presentation_integrity_status == "canonical_conflict"


def test_a_claim_that_misreports_the_governed_value_fails_closed():
    fact = governed_facts("mm", metric="dividend_yield_serie", fund="TRI", period="2026-06",
                          series="A", valuation_basis="market").evidence.facts[0]
    tampered = claim("c", "mm", fact)
    tampered["value"] = 0.05
    session = build_session([
        ModelResponse("", [lookup("mm", metric="dividend_yield_serie", fund="TRI", period="2026-06",
                                  series="A", valuation_basis="market")]),
        envelope([{"type": "text", "text": "El DY fue "},
                  {"type": "canonical_metric_ref", "claim_id": "c"}], canonical=[tampered]),
    ])

    result = session.ask("¿DY bursátil de TRI A en junio 2026?")

    assert "5,00%" not in result.text
    assert result.presentation_integrity_status == "canonical_conflict"


def test_series_identity_never_collides_between_share_classes():
    a = governed_facts("ia", metric="tir_serie", fund="TRI", period="2026-06", series="A",
                       return_basis="market", return_window="since_inception").evidence.facts[0]
    i = governed_facts("ii", metric="tir_serie", fund="TRI", period="2026-06", series="I",
                       return_basis="market", return_window="since_inception").evidence.facts[0]
    assert a["entity_id"] != i["entity_id"]
    # A claim bound to series A's evidence cannot carry series I's identity.
    crossed = claim("c", "ia", i)
    session = build_session([
        ModelResponse("", [lookup("ia", metric="tir_serie", fund="TRI", period="2026-06", series="A",
                                  return_basis="market", return_window="since_inception")]),
        envelope([{"type": "text", "text": "TIR: "}, {"type": "canonical_metric_ref", "claim_id": "c"}],
                 canonical=[crossed]),
    ])

    result = session.ask("¿TIR bursátil desde inicio de la serie A de TRI?")

    assert result.presentation_integrity_status == "canonical_conflict"


def test_durable_context_restores_dimensions_for_a_toolless_follow_up():
    first_facts = governed_facts("dm", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                                 series="A", valuation_basis="book").evidence
    session = build_session([
        ModelResponse("", [lookup("dm", metric="valor_cuota_serie", fund="TRI", period="2026-03",
                                  series="A", valuation_basis="book")]),
        envelope([{"type": "text", "text": "El valor libro fue "},
                  {"type": "canonical_metric_ref", "claim_id": "v"}],
                 canonical=[claim("v", "dm", first_facts.facts[0])]),
    ])
    first = session.ask("¿Valor cuota contable de TRI A al 31 de marzo de 2026?")
    # The stored fact stays native CLP; the global UF default renders it
    # through the governed same-date UF reference the source row carries, so
    # the conversion is traceable rather than assumed -- and a sub-UF amount
    # is never rounded away to "1 UF".
    assert "0,8118 UF" in first.text
    memory = first.durable_memory
    assert memory["evidence"][0]["facts"][0]["unit"] == "clp"
    assert memory["evidence"][0]["facts"][0]["valuation_basis"] == "book"
    assert memory["evidence"][0]["facts"][0]["series"] == "A"

    # A brand-new session (a restart) rebuilt from the durable memory can still
    # bind the same claim with no new tool call.
    resumed = build_session([
        envelope([{"type": "text", "text": "Ese valor libro fue "},
                  {"type": "canonical_metric_ref", "claim_id": "v"}],
                 canonical=[claim("v", "dm", first_facts.facts[0])]),
    ], runtime_context={"durable_analytical_context": {"evidence": memory["evidence"]}})

    second = resumed.ask("Recuérdame ese valor.")
    assert "0,8118 UF" in second.text

    # ...and the same restored claim renders the native CLP figure when the
    # user asks for pesos, with no re-query.
    in_pesos = build_session([
        envelope([{"type": "text", "text": "En pesos fue "},
                  {"type": "canonical_metric_ref", "claim_id": "v"}],
                 canonical=[claim("v", "dm", first_facts.facts[0])]),
    ], runtime_context={"durable_analytical_context": {"evidence": memory["evidence"]}})
    assert "32.342 CLP" in in_pesos.ask("Dímelo en pesos.").text
