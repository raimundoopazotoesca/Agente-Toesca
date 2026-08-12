import tools.analyst.conversation_state as conversation_state
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


def test_state_size_is_capped_with_oldest_eviction():
    conversation_state._STATE.clear()
    cap = conversation_state._MAX_SESSIONS
    for i in range(cap + 50):
        update_state(f"cap-session-{i}", last_metric="noi")
        assert len(conversation_state._STATE) <= cap

    assert len(conversation_state._STATE) == cap
    # Oldest sessions (0..49) must have been evicted first.
    assert "cap-session-0" not in conversation_state._STATE
    assert "cap-session-49" not in conversation_state._STATE
    # Most recently inserted session must survive.
    assert f"cap-session-{cap + 49}" in conversation_state._STATE

    conversation_state._STATE.clear()
