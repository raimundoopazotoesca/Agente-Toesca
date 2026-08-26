"""Store-level tests for the Pilot Control Center (v1) read-only queries.

These exercise `WorkspaceStore.pilot_overview`, `list_pilot_users`,
`get_pilot_user_detail`, `list_pilot_conversations`, `get_pilot_conversation_detail`,
and `list_latest_pilot_questions` directly against a real temp-file SQLite DB --
no Flask, no HTTP. Route-level auth/isolation tests live in
tests/analyst_workspace/test_pilot_control_api.py.
"""
from __future__ import annotations

import pytest

from tools.analyst_workspace.store import WorkspaceStore


@pytest.fixture
def store(tmp_path):
    workspace = WorkspaceStore(tmp_path / "workspace.db")
    workspace.initialize()
    return workspace


def _seed(store):
    """Three users, several conversations, messages with and without telemetry, one report."""
    alice = store.create_user("alice", "Alice Ann", "password-a")
    bob = store.create_user("bob", "Bob Ben", "password-b")
    carol = store.create_user("carol", "Carol Cee", "password-c")

    c1 = store.create_conversation(title="NOI PT", owner_user_id=alice).id
    store.append_message(c1, "user", "cual es el NOI de PT este trimestre?")
    a1 = store.append_message(c1, "assistant", "El NOI de PT es X", metadata={
        "latency_ms": 1000.0, "provider": "gemini", "model": "gemini-2.5-flash",
        "sql_queries": ["SELECT 1"], "tool_calls": [{"name": "consultar_noi", "ok": True, "duration_ms": 40}],
        "turn_metrics": {"llm_rounds": 2, "fresh_evidence_count": 3},
    }).id

    c2 = store.create_conversation(title="Vacancia Apoquindo", owner_user_id=bob).id
    store.append_message(c2, "user", "vacancia de apoquindo?")
    b1 = store.append_message(c2, "assistant", "La vacancia es Y", metadata={"latency_ms": 2000.0}).id
    # Second assistant turn with NO telemetry -- must be excluded from latency stats.
    store.append_message(c2, "user", "y en oficinas?")
    store.append_message(c2, "assistant", "En oficinas es Z", metadata=None)

    c3 = store.create_conversation(title="Dividend yield TRI", owner_user_id=carol).id
    store.append_message(c3, "user", "dividend yield de TRI?")
    store.append_message(c3, "assistant", "El DY es W", metadata={"latency_ms": 3000.0})

    report_id = store.create_feedback_report_for_user(bob, c2, b1, "la respuesta no considero oficinas")
    return {"alice": alice, "bob": bob, "carol": carol, "c1": c1, "c2": c2, "c3": c3, "a1": a1, "b1": b1, "report_id": report_id}


# ── Overview ─────────────────────────────────────────────────────────────────

def test_overview_counts_total_users_including_initial_admin(store):
    _seed(store)
    overview = store.pilot_overview()
    # 3 seeded pilot users + the initial admin account created by initialize().
    assert overview["total_users"] == 4


def test_overview_active_users_today_counts_distinct_senders_of_user_messages(store):
    ids = _seed(store)
    overview = store.pilot_overview()
    assert overview["active_users_today"] == 3  # alice, bob, carol all sent a user message
    assert overview["active_users_7d"] == 3


def test_overview_message_and_conversation_counts(store):
    _seed(store)
    overview = store.pilot_overview()
    assert overview["conversations_today"] == 3
    assert overview["user_messages_today"] == 4  # 1 + 2 + 1
    assert overview["assistant_responses_today"] == 4  # 1 + 2 + 1


def test_overview_reports_new_and_total(store):
    _seed(store)
    overview = store.pilot_overview()
    assert overview["reports_new"] == 1
    assert overview["reports_total"] == 1


def test_overview_latency_excludes_missing_telemetry_and_reports_sample_size(store):
    _seed(store)
    overview = store.pilot_overview()
    lat = overview["latency_ms"]
    # 3 assistant messages carry latency_ms (1000, 2000, 3000); the 4th (c2's second
    # assistant reply) has metadata=None and must be excluded, never treated as 0.
    assert lat["sample_size"] == 3
    assert lat["avg_ms"] == 2000.0
    # n=3: p50 rank=ceil(1.5)=2 -> sorted[1]=2000; p90 rank=ceil(2.7)=3 -> sorted[2]=3000
    assert lat["p50_ms"] == 2000.0
    assert lat["p90_ms"] == 3000.0


def test_overview_rating_counts_reflect_message_feedback(store):
    seed = _seed(store)
    overview = store.pilot_overview()
    # No ratings yet: a real (non-null) bucket with zero counts, not a `None` seam.
    assert overview["rating_counts"] == {"total_rated": 0, "up": 0, "down": 0, "positive_rate": None}

    store.set_feedback(seed["a1"], "up", user_id=seed["alice"], _scope_owner_id=seed["alice"])
    store.set_feedback(seed["b1"], "down", user_id=seed["bob"], _scope_owner_id=seed["bob"])
    overview = store.pilot_overview()
    assert overview["rating_counts"] == {"total_rated": 2, "up": 1, "down": 1, "positive_rate": 0.5}


def test_overview_on_empty_workspace_has_zero_counts_and_null_latency(store):
    overview = store.pilot_overview()
    assert overview["total_users"] == 1  # just the initial admin
    assert overview["conversations_today"] == 0
    assert overview["latency_ms"]["sample_size"] == 0
    assert overview["latency_ms"]["avg_ms"] is None
    assert overview["latency_ms"]["p50_ms"] is None


# ── Users view ───────────────────────────────────────────────────────────────

def test_list_pilot_users_never_exposes_password_hash_or_session_fields(store):
    _seed(store)
    for row in store.list_pilot_users():
        assert "password_hash" not in row
        assert "token_hash" not in row
        assert "session" not in row


def test_list_pilot_users_per_user_metrics(store):
    ids = _seed(store)
    by_username = {u["username"]: u for u in store.list_pilot_users()}
    bob = by_username["bob"]
    assert bob["conversation_count"] == 1
    assert bob["user_message_count"] == 2
    assert bob["assistant_response_count"] == 2
    assert bob["report_count"] == 1
    assert bob["latency_ms"]["sample_size"] == 1
    assert bob["latency_ms"]["avg_ms"] == 2000.0
    assert bob["rating_summary"] is None  # seam for future Message Feedback


def test_get_pilot_user_detail_returns_recent_conversations(store):
    ids = _seed(store)
    detail = store.get_pilot_user_detail(ids["bob"])
    assert detail["username"] == "bob"
    assert detail["report_count"] == 1
    titles = [c["title"] for c in detail["recent_conversations"]]
    assert titles == ["Vacancia Apoquindo"]
    conv = detail["recent_conversations"][0]
    assert conv["user_message_count"] == 2
    assert conv["assistant_message_count"] == 2
    assert conv["report_count"] == 1


def test_get_pilot_user_detail_returns_none_for_unknown_user(store):
    _seed(store)
    assert store.get_pilot_user_detail("does-not-exist") is None


# ── Conversations view ───────────────────────────────────────────────────────

def test_list_pilot_conversations_spans_all_owners_newest_first(store):
    ids = _seed(store)
    conversations = store.list_pilot_conversations()
    assert len(conversations) == 3
    # newest updated_at first
    updated = [c["updated_at"] for c in conversations]
    assert updated == sorted(updated, reverse=True)


def test_list_pilot_conversations_filters_by_user(store):
    ids = _seed(store)
    conversations = store.list_pilot_conversations(user_id=ids["carol"])
    assert len(conversations) == 1
    assert conversations[0]["owner_username"] == "carol"


def test_list_pilot_conversations_search_matches_title_case_insensitively(store):
    _seed(store)
    conversations = store.list_pilot_conversations(search="vacancia")
    assert len(conversations) == 1
    assert conversations[0]["title"] == "Vacancia Apoquindo"


def test_list_pilot_conversations_never_fabricates_rating_summary(store):
    _seed(store)
    for c in store.list_pilot_conversations():
        assert c["rating_summary"] is None


# ── Conversation detail (read-only viewer) ──────────────────────────────────

def test_conversation_detail_shows_only_role_and_content_no_hidden_fields(store):
    ids = _seed(store)
    detail = store.get_pilot_conversation_detail(ids["c1"])
    for m in detail["messages"]:
        assert set(m.keys()) >= {"id", "role", "content", "created_at", "reports"}
        assert m["role"] in {"user", "assistant"}


def test_conversation_detail_diagnostics_only_present_for_assistant_messages(store):
    ids = _seed(store)
    detail = store.get_pilot_conversation_detail(ids["c1"])
    by_role = {m["role"]: m for m in detail["messages"]}
    assert "diagnostics" not in by_role["user"]
    assert by_role["assistant"]["diagnostics"] is not None


def test_conversation_detail_diagnostics_excludes_raw_sql_and_unlisted_keys(store):
    ids = _seed(store)
    detail = store.get_pilot_conversation_detail(ids["c1"])
    diag = [m for m in detail["messages"] if m["role"] == "assistant"][0]["diagnostics"]
    assert "sql_queries" not in diag  # raw SQL text is deliberately never exposed
    assert diag["provider"] == "gemini"
    assert diag["tool_calls"][0]["name"] == "consultar_noi"


def test_conversation_detail_message_missing_telemetry_has_null_diagnostics(store):
    ids = _seed(store)
    detail = store.get_pilot_conversation_detail(ids["c2"])
    assistant_msgs = [m for m in detail["messages"] if m["role"] == "assistant"]
    assert any(m["diagnostics"] is None for m in assistant_msgs)


def test_conversation_detail_anchors_report_to_correct_message(store):
    ids = _seed(store)
    detail = store.get_pilot_conversation_detail(ids["c2"])
    anchored = [m for m in detail["messages"] if m["id"] == ids["b1"]][0]
    assert len(anchored["reports"]) == 1
    assert anchored["reports"][0]["comment"] == "la respuesta no considero oficinas"
    assert anchored["reports"][0]["status"] == "new"
    other = [m for m in detail["messages"] if m["role"] == "assistant" and m["id"] != ids["b1"]][0]
    assert other["reports"] == []


def test_conversation_detail_returns_none_for_unknown_conversation(store):
    _seed(store)
    assert store.get_pilot_conversation_detail("does-not-exist") is None


# ── Latest questions feed ───────────────────────────────────────────────────

def test_latest_questions_newest_first_across_all_users(store):
    _seed(store)
    questions = store.list_latest_pilot_questions()
    created = [q["created_at"] for q in questions]
    assert created == sorted(created, reverse=True)
    assert {q["owner_username"] for q in questions} == {"alice", "bob", "carol"}


def test_latest_questions_only_includes_user_role_messages(store):
    _seed(store)
    for q in store.list_latest_pilot_questions():
        assert "content" in q and "conversation_title" in q


def test_latest_questions_respects_limit(store):
    _seed(store)
    assert len(store.list_latest_pilot_questions(limit=2)) == 2
