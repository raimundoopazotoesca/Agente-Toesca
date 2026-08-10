from tools.analyst.conversation_state import get_state, update_state, clear_state


def test_unseen_session_returns_defaults():
    clear_state("test-session-1")
    state = get_state("test-session-1")
    assert state == {
        "last_metric": None,
        "last_entities": {},
        "last_period": None,
        "last_analysis_type": None,
    }


def test_update_and_retrieve():
    clear_state("test-session-2")
    update_state("test-session-2", last_metric="vacancia_pct", last_entities={"activo": "Torre A"})
    state = get_state("test-session-2")
    assert state["last_metric"] == "vacancia_pct"
    assert state["last_entities"] == {"activo": "Torre A"}
    assert state["last_period"] is None


def test_sessions_are_isolated():
    clear_state("test-session-3a")
    clear_state("test-session-3b")
    update_state("test-session-3a", last_metric="noi")
    assert get_state("test-session-3b")["last_metric"] is None
