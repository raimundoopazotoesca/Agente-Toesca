"""Unit tests for the pure markdown-formatting module (no Flask, no DB).

These exercise export_markdown.py directly against hand-built dicts shaped
like WorkspaceStore.get_feedback_report()/get_pilot_conversation_detail()
output, so content-correctness bugs are caught without spinning up a Flask
test client.
"""
from __future__ import annotations

from tools.analyst_workspace import export_markdown


def _report(**overrides):
    base = {
        "id": "report-1",
        "reporter_user_id": "user-1",
        "reporter_display_name": "Alice",
        "conversation_id": "conv-1",
        "anchor_message_id": "msg-2",
        "comment": "No comparó los activos.",
        "conversation_snapshot": [
            {"message_id": "msg-1", "role": "user", "content": "¿Cuál es el NOI de PT?", "created_at": "2026-08-01T10:00:00Z"},
            {"message_id": "msg-2", "role": "assistant", "content": "El NOI de PT es X.", "created_at": "2026-08-01T10:00:05Z"},
        ],
        "technical_context": {"provider": "openai", "model": "gpt-5", "latency_ms": 1234.5},
        "status": "new",
        "created_at": "2026-08-01T10:01:00Z",
        "updated_at": "2026-08-01T10:01:00Z",
        "live_rating": "down",
    }
    base.update(overrides)
    return base


def _conversation(**overrides):
    base = {
        "id": "conv-1",
        "title": "Consulta NOI",
        "created_at": "2026-08-01T10:00:00Z",
        "updated_at": "2026-08-01T10:00:05Z",
        "archived": False,
        "owner_user_id": "user-1",
        "owner_display_name": "Alice",
        "owner_username": "alice",
        "rating_summary": {"total_rated": 1, "up": 0, "down": 1, "positive_rate": 0.0},
        "messages": [
            {"id": "msg-1", "role": "user", "content": "¿Cuál es el NOI de PT?", "created_at": "2026-08-01T10:00:00Z", "reports": []},
            {
                "id": "msg-2", "role": "assistant", "content": "El NOI de PT es X.",
                "created_at": "2026-08-01T10:00:05Z", "reports": [],
                "diagnostics": {"provider": "openai", "model": "gpt-5", "latency_ms": 900.0, "sql_count": 2},
                "rating": "down",
            },
        ],
    }
    base.update(overrides)
    return base


# ── Feedback reports export ─────────────────────────────────────────────────

def test_feedback_export_includes_aggregate_metadata_header():
    md = export_markdown.build_feedback_reports_export([_report(status="new"), _report(id="report-2", status="resolved")])
    assert "**Total reportes:** 2" in md
    assert "**Estado `new`:** 1" in md
    assert "**Estado `resolved`:** 1" in md


def test_feedback_export_preserves_exact_comment_text_verbatim():
    tricky = "# Not a real heading\n```python\nprint('hola')\n```\n| a | b |\n|---|---|\n| 1 | 2 |"
    md = export_markdown.build_feedback_reports_export([_report(comment=tricky)])
    assert tricky in md


def test_feedback_export_includes_immutable_snapshot_content():
    md = export_markdown.build_feedback_reports_export([_report()])
    assert "¿Cuál es el NOI de PT?" in md
    assert "El NOI de PT es X." in md


def test_feedback_export_marks_the_reported_response():
    md = export_markdown.build_feedback_reports_export([_report()])
    assert "respuesta reportada" in md


def test_feedback_export_shows_live_rating_distinct_from_snapshot():
    md = export_markdown.build_feedback_reports_export([_report(live_rating="down")])
    assert "👎 down" in md


def test_feedback_export_unrated_is_explicit():
    md = export_markdown.build_feedback_reports_export([_report(live_rating=None)])
    assert "sin calificar" in md


def test_feedback_export_missing_diagnostics_is_explicit_not_invented():
    md = export_markdown.build_feedback_reports_export([_report(technical_context=None)])
    diagnostics_section = md.split("Diagnóstico técnico")[-1]
    assert "sin telemetría" in diagnostics_section
    assert "None" not in diagnostics_section


def test_feedback_export_empty_list_still_produces_valid_document():
    md = export_markdown.build_feedback_reports_export([])
    assert "**Total reportes:** 0" in md
    assert "sin reportes" in md


def test_feedback_export_utf8_accents_ene_uf_percent_emoji():
    md = export_markdown.build_feedback_reports_export([_report(
        comment="Vacancia 12,5% en UF/m² — año — ñandú 🏢",
    )])
    assert "Vacancia 12,5% en UF/m² — año — ñandú 🏢" in md
    md.encode("utf-8")  # must not raise


# ── Batch conversation export ───────────────────────────────────────────────

def test_conversations_export_aggregate_metadata():
    md = export_markdown.build_conversations_export([_conversation(), _conversation(id="conv-2", owner_user_id="user-2")])
    assert "**Conversaciones:** 2" in md
    assert "**Usuarios distintos:** 2" in md
    assert "**Mensajes de usuario:** 2" in md
    assert "**Respuestas del asistente:** 2" in md
    assert "**Respuestas calificadas:** 2 (\U0001F44D 0 · \U0001F44E 2)" in md
    assert "**Respuestas reportadas:** 0" in md


def test_conversations_export_preserves_exact_transcript_with_code_fence_and_table():
    tricky = "## Fake heading\n```js\nconsole.log(1)\n```\n| x | y |\n|---|---|\n| 1 | 2 |"
    md = export_markdown.build_conversations_export([_conversation(messages=[
        {"id": "m1", "role": "user", "content": tricky, "created_at": "t", "reports": []},
    ])])
    assert tricky in md


def test_conversations_export_reported_message_shows_report_note():
    conv = _conversation(messages=[
        {"id": "m1", "role": "user", "content": "hola", "created_at": "t1", "reports": []},
        {
            "id": "m2", "role": "assistant", "content": "respuesta", "created_at": "t2",
            "rating": None, "diagnostics": None,
            "reports": [{"id": "r1", "status": "new", "comment": "mala respuesta", "reporter_display_name": "Bob", "created_at": "t3", "updated_at": "t3"}],
        },
    ])
    md = export_markdown.build_conversations_export([conv])
    assert "reportado: sí" in md
    assert "mala respuesta" in md
    assert "Bob" in md


def test_conversations_export_missing_diagnostics_explicit():
    conv = _conversation(messages=[
        {"id": "m2", "role": "assistant", "content": "x", "created_at": "t", "rating": None, "diagnostics": None, "reports": []},
    ])
    md = export_markdown.build_conversations_export([conv])
    assert "sin telemetría" in md


def test_conversations_export_unrated_message_is_explicit():
    conv = _conversation(messages=[
        {"id": "m2", "role": "assistant", "content": "x", "created_at": "t", "rating": None, "diagnostics": {}, "reports": []},
    ])
    md = export_markdown.build_conversations_export([conv])
    assert "sin calificar" in md


def test_conversations_export_empty_list_still_valid_document():
    md = export_markdown.build_conversations_export([])
    assert "**Conversaciones:** 0" in md
    assert "sin conversaciones" in md


def test_conversations_export_diagnostics_are_rendered_verbatim_from_caller_input():
    # This module trusts its caller to have already applied the safe
    # allowlist (WorkspaceStore._SAFE_TECHNICAL_CONTEXT_KEYS /
    # _safe_turn_diagnostics) before handing it a diagnostics dict --
    # export_markdown itself does not re-filter. The actual "forbidden
    # fields never leave the server" guarantee is therefore an HTTP-level
    # test (tests/analyst_workspace/test_pilot_export_api.py), which seeds
    # real metadata_json through the store and asserts on the response body.
    conv = _conversation(messages=[
        {
            "id": "m2", "role": "assistant", "content": "x", "created_at": "t", "rating": None,
            "diagnostics": {"provider": "openai", "latency_ms": 1.0},
            "reports": [],
        },
    ])
    md = export_markdown.build_conversations_export([conv])
    assert "openai" in md
    assert "1.0" in md


def test_conversations_export_multiple_conversations_are_hr_separated():
    md = export_markdown.build_conversations_export([_conversation(), _conversation(id="conv-2")])
    assert md.count("\n\n---\n\n") >= 2
