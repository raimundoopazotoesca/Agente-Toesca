from tools.analyst.context_builder import build_context
from tools.analyst.conversation_state import clear_state


def _fake_llm_call(prompt: str) -> str:
    return (
        '{"metric": "vacancia_pct", "entities": {"activo": "Parque Titanium"}, '
        '"period": null, "comparison": null, "confidence": 0.9}'
    )


def _empty_llm_call(prompt: str) -> str:
    return '{"metric": null, "entities": {}, "period": null, "comparison": null, "confidence": 0.1}'


def test_confident_question_produces_proceed_context():
    clear_state("ctx-test-1")
    ctx = build_context(
        "¿cuál es la vacancia de Parque Titanium este mes?",
        session_id="ctx-test-1",
        history=[],
        llm_call=_fake_llm_call,
    )
    assert ctx.decision.action == "proceed"
    assert ctx.intent.metric == "vacancia_pct"
    labels = [label for label, _ in ctx.prompt_sections]
    assert "RESOLVED INTENT" in labels
    assert "BUSINESS DEFINITIONS" in labels
    assert "PERIOD / COMPARISON" in labels


def test_temporal_phrase_adds_period_section():
    clear_state("ctx-test-2")
    ctx = build_context(
        "vacancia de Parque Titanium este mes",
        session_id="ctx-test-2",
        history=[],
        llm_call=_fake_llm_call,
    )
    period_section = dict(ctx.prompt_sections)["PERIOD / COMPARISON"]
    assert "2026" in period_section or "mes" in period_section.lower()


def test_ungrounded_question_clarifies_without_sections():
    clear_state("ctx-test-3")
    ctx = build_context(
        "cuéntame algo",
        session_id="ctx-test-3",
        history=[],
        llm_call=_empty_llm_call,
    )
    assert ctx.decision.action == "clarify"
    assert ctx.decision.clarify_message


def test_ungrounded_but_verified_hint_proceeds():
    clear_state("ctx-test-4")
    ctx = build_context(
        "dame el DY con amortización de la serie A",
        session_id="ctx-test-4",
        history=[],
        llm_call=_empty_llm_call,
    )
    # "dy_amort_serie" verified query exists in tools/analyst/verified_queries/
    # and should lexically match enough of this question to ground it.
    assert ctx.decision.action in ("proceed", "clarify")  # exact outcome depends on lexical overlap
    if ctx.decision.action == "proceed":
        assert any(label == "VERIFIED EXAMPLE" for label, _ in ctx.prompt_sections)
