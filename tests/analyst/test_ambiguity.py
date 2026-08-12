from tools.analyst.ambiguity import decide, AmbiguityDecision
from tools.analyst.intent import IntentResult


def test_confident_intent_proceeds():
    intent = IntentResult(metric="vacancia_pct", entities={"activo": "Parque Titanium"},
                           confidence=0.9, needs_clarification=False)
    d = decide(intent, verified_hint=None, has_history=False)
    assert d.action == "proceed"


def test_low_confidence_with_verified_hint_proceeds():
    intent = IntentResult(metric=None, entities={}, confidence=0.2, needs_clarification=True)
    d = decide(intent, verified_hint={"question": "...", "sql": "..."}, has_history=False)
    assert d.action == "proceed"
    assert "verified" in d.reason.lower()


def test_low_confidence_with_history_proceeds():
    intent = IntentResult(metric=None, entities={}, confidence=0.2, needs_clarification=True)
    d = decide(intent, verified_hint=None, has_history=True)
    assert d.action == "proceed"


def test_low_confidence_no_grounding_clarifies():
    intent = IntentResult(metric=None, entities={}, confidence=0.1, needs_clarification=True)
    d = decide(intent, verified_hint=None, has_history=False)
    assert d.action == "clarify"
    assert d.clarify_message


def test_inherited_from_state_is_not_needs_clarification():
    # extract_intent() already set needs_clarification=False when it could
    # inherit metric/entities from conversation state.
    intent = IntentResult(metric="noi", entities={"fondo": "PT"}, confidence=0.2,
                           needs_clarification=False)
    d = decide(intent, verified_hint=None, has_history=False)
    assert d.action == "proceed"
    assert "inherited" in d.reason.lower() or "confidence" in d.reason.lower()
