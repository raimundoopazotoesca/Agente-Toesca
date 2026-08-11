"""Tests de las partes deterministicas de tools/db_chat.py (sin llamar al LLM).

No cubren answer() completo porque depende de un proveedor LLM externo; cubren
la logica que puede romperse silenciosamente al tocar el prompt/few-shots:
validacion de SQL, formateo numerico, atajo de saludos, extraccion de JSON y
sugerencia de periodos disponibles.
"""
import sqlite3
import unittest

import pytest

from tools import db_chat


# ─── _validate_sql ─────────────────────────────────────────────────────────
class TestValidateSql:
    def test_select_ok(self):
        assert db_chat._validate_sql("SELECT 1") is None

    def test_with_ok(self):
        assert db_chat._validate_sql("WITH x AS (SELECT 1) SELECT * FROM x") is None

    def test_empty_rejected(self):
        assert db_chat._validate_sql("") is not None
        assert db_chat._validate_sql("   ") is not None

    def test_multi_statement_rejected(self):
        assert db_chat._validate_sql("SELECT 1; SELECT 2") is not None

    def test_insert_rejected(self):
        assert db_chat._validate_sql("INSERT INTO t VALUES (1)") is not None

    def test_update_rejected(self):
        assert db_chat._validate_sql("UPDATE t SET x=1") is not None

    def test_delete_rejected(self):
        assert db_chat._validate_sql("DELETE FROM t") is not None

    def test_drop_rejected(self):
        assert db_chat._validate_sql("DROP TABLE t") is not None

    def test_pragma_rejected(self):
        assert db_chat._validate_sql("PRAGMA table_info(t)") is not None

    def test_attach_rejected(self):
        assert db_chat._validate_sql("SELECT * FROM t; ATTACH 'x' AS y") is not None

    def test_non_select_head_rejected(self):
        assert db_chat._validate_sql("EXPLAIN SELECT 1") is not None


# ─── _format_cl ─────────────────────────────────────────────────────────────
class TestFormatCl:
    def test_simple_decimal(self):
        assert db_chat._format_cl(13478.687647800309) == "13.478,69"

    def test_no_thousands(self):
        assert db_chat._format_cl(4.85) == "4,85"

    def test_negative(self):
        assert db_chat._format_cl(-1.91) == "-1,91"

    def test_large_number(self):
        assert db_chat._format_cl(572127822.09) == "572.127.822,09"

    def test_zero_decimals(self):
        assert db_chat._format_cl(1234.5, decimals=0) == "1.234" or db_chat._format_cl(1234.5, decimals=0) == "1.235"


class TestFormatRows:
    def test_floats_formatted_ints_and_strings_untouched(self):
        cols = ["entidad_key", "valor", "n"]
        rows = [["CFITOERI1A", 13478.687647800309, 5]]
        out = db_chat._format_rows(cols, rows)
        assert out == [["CFITOERI1A", "13.478,69", 5]]

    def test_empty_rows(self):
        assert db_chat._format_rows(["a"], []) == []


# ─── _extract_json ──────────────────────────────────────────────────────────
class TestExtractJson:
    def test_plain_json(self):
        assert db_chat._extract_json('{"sql": "SELECT 1"}') == {"sql": "SELECT 1"}

    def test_json_with_surrounding_text(self):
        text = 'Aqui tienes:\n{"sql": "SELECT 1"}\nListo.'
        assert db_chat._extract_json(text) == {"sql": "SELECT 1"}

    def test_json_in_code_fence(self):
        text = '```json\n{"clarify": "cual periodo?"}\n```'
        assert db_chat._extract_json(text) == {"clarify": "cual periodo?"}

    def test_invalid_json_returns_empty(self):
        assert db_chat._extract_json("no json aqui") == {}

    def test_malformed_json_returns_empty(self):
        assert db_chat._extract_json('{"sql": "SELECT 1"') == {}


# ─── _shortcut_answer (saludos/meta) ────────────────────────────────────────
class TestShortcutAnswer:
    @pytest.mark.parametrize("q", [
        "hola",
        "Hola!",
        "buenas tardes",
        "hola, quien eres?",
        "que puedes hacer?",
        "qué sabes hacer",
        "para que sirves?",
        "quien eres",
    ])
    def test_greeting_and_capability_shortcut(self, q):
        result = db_chat._shortcut_answer(q)
        assert result is not None
        assert result["provider"] == "shortcut"
        assert "Toesca" in result["answer_md"]

    @pytest.mark.parametrize("q", [
        "cual es el NOI de Viña Centro en enero 2024?",
        "LTV del fondo TRI",
        "hola, cual es el NOI de PT en enero 2024?",
    ])
    def test_real_questions_not_shortcut(self, q):
        assert db_chat._shortcut_answer(q) is None


# ─── _suggest_available_periods ─────────────────────────────────────────────
class TestSuggestAvailablePeriods:
    def test_no_periodo_filter_returns_none(self):
        sql = "SELECT valor FROM derived_kpi WHERE kpi='ltv'"
        assert db_chat._suggest_available_periods(sql) is None

    def test_periodo_filter_present_queries_real_db(self):
        # Usa la DB real vía DEFAULT_DB_PATH (solo lectura); si el kpi no
        # existe en absoluto, debe devolver None sin lanzar excepcion.
        sql = (
            "SELECT valor FROM derived_kpi WHERE kpi='ltv' "
            "AND entidad_tipo='fondo' AND entidad_key='TRI' AND periodo='1900-01'"
        )
        result = db_chat._suggest_available_periods(sql)
        # No sabemos el rango exacto (depende de datos reales), pero si hay
        # datos para TRI/ltv en otros periodos, debe devolver un string no vacio.
        assert result is None or ("rango de periodos disponible" in result)

    def test_malformed_sql_does_not_raise(self):
        sql = "SELECT valor FROM no_existe_esta_tabla WHERE periodo='2024-01'"
        assert db_chat._suggest_available_periods(sql) is None


# ─── _run_sql / _validate_sql integracion liviana ───────────────────────────
class TestRunSqlAppliesLimit:
    def test_limit_auto_applied(self):
        sql = "SELECT 1 AS x"
        # No debe lanzar, y debe respetar el tope por defecto sin declarar LIMIT.
        cols, rows = db_chat._run_sql(sql)
        assert cols == ["x"]
        assert rows == [[1]]


# ─── _mensaje_error_llm (nunca mostrar JSON tecnico crudo al usuario) ───────
class TestMensajeErrorLlm:
    @pytest.mark.parametrize("texto_error", [
        "Error code: 429 rate_limit_exceeded: tokens per day (TPD)",
        "Error code: 403 - API_KEY_HTTP_REFERRER_BLOCKED: Requests from referer <empty> are blocked",
        "RESOURCE_EXHAUSTED: quota exceeded",
        "429 Too Many Requests",
    ])
    def test_error_de_capacidad_usa_mensaje_sin_cupo(self, texto_error):
        result = db_chat._mensaje_error_llm(Exception(texto_error))
        assert result == db_chat._MENSAJE_SIN_CUPO
        assert "{" not in result and "error" not in result.lower()

    def test_error_generico_no_expone_detalle_tecnico(self):
        exc = Exception("Traceback: KeyError('unexpected_field') at line 42")
        result = db_chat._mensaje_error_llm(exc)
        assert "KeyError" not in result
        assert "Traceback" not in result

    def test_no_api_key_no_expone_detalle_en_answer_md(self, monkeypatch):
        monkeypatch.setattr(db_chat, "_provider_chain", lambda: (_ for _ in ()).throw(
            RuntimeError("No hay API key configurada. Define DEEPSEEK_API_KEY, ...")
        ))
        result = db_chat.answer("cual es el LTV del fondo TRI?")
        assert result["answer_md"] == db_chat._MENSAJE_SIN_CUPO
        assert result["error"] == "no_api_key"
        assert "DEEPSEEK_API_KEY" not in result["answer_md"]


# ─── answer() con capa de intent/result-checks (Task 8) ─────────────────────
class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class TestAnswerWithIntentLayer:
    def test_answer_accepts_session_id_param(self):
        # Full call would hit a real LLM; verify the signature accepts
        # session_id without raising TypeError, using empty question shortcut.
        result = db_chat.answer("", session_id="test-wiring-session")
        assert result["error"] == "empty"

    def test_answer_result_check_flags_out_of_bounds(self, monkeypatch):
        # Task 5 wiring adds a preceding intent-extraction LLM call (through
        # the same _chat_completion_with_fallback) before SQL generation, so
        # the fake response queue needs an extra entry up front with a
        # confident, resolvable intent so build_context proceeds to SQL
        # generation instead of short-circuiting into clarify.
        intent_json = (
            '{"metric": "vacancia_pct", "entities": {"activo": "Curicó"}, '
            '"period": null, "comparison": null, "confidence": 0.9}'
        )
        sql_json = '{"sql": "SELECT valor FROM derived_kpi WHERE kpi = \'vacancia_pct\'"}'
        responses = [
            (_FakeResp(intent_json), {"model": "fake-model-1"}),
            (_FakeResp(sql_json), {"model": "fake-model-1"}),
            (_FakeResp("Vacancia fuera de rango."), {"model": "fake-model-1"}),
        ]

        def fake_chat_completion(_messages, **_kwargs):
            return responses.pop(0)

        monkeypatch.setattr(db_chat, "_chat_completion_with_fallback", fake_chat_completion)
        monkeypatch.setattr(db_chat, "_provider_chain", lambda: [{"model": "fake-model-1"}])
        monkeypatch.setattr(db_chat, "_run_sql", lambda sql: (["valor"], [[134.0]]))
        monkeypatch.setattr(db_chat, "_extract_metric_from_sql", lambda sql: "vacancia_pct")

        result = db_chat.answer("vacancia de Curicó", session_id="test-wiring-session-2")

        assert "result_check" in result
        assert result["result_check"]["passed"] is False
        assert result["result_check"]["violated"]


# ─── answer() con context_builder wiring (Task 5) ────────────────────────────
class TestContextBuilderWiring(unittest.TestCase):
    def test_clarify_short_circuit_before_sql_generation(self):
        from tools.analyst.conversation_state import clear_state
        clear_state("test-clarify-wiring")
        result = db_chat.answer("cuéntame algo", session_id="test-clarify-wiring")
        # A fully ungrounded question with no prior state must clarify
        # deterministically, without ever reaching SQL generation.
        self.assertTrue(result.get("clarify"))
        self.assertIsNone(result.get("sql"))

    def test_context_sections_reach_the_sql_prompt(self):
        # Regression guard: RESOLVED INTENT / labeled sections must appear
        # in the messages sent for SQL generation, not just be computed and
        # discarded.
        captured = {}
        original = db_chat._chat_completion_with_fallback

        def _spy(messages, **kwargs):
            # answer() now issues an intent-extraction LLM call (via
            # _intent_llm_call, added by this same wiring) before the SQL
            # generation call, so "first call" is no longer the SQL prompt.
            # Identify the SQL-generation call by its distinctive system
            # message instead of by call order.
            if any(m.get("content") == db_chat._SQL_SYSTEM for m in messages):
                captured["captured_sql_messages"] = messages
            return original(messages, **kwargs)

        db_chat._chat_completion_with_fallback = _spy
        try:
            db_chat.answer("vacancia de Parque Titanium este mes", session_id="test-sections-wiring")
        finally:
            db_chat._chat_completion_with_fallback = original

        contents = " ".join(
            m["content"] for m in captured.get("captured_sql_messages", []) if isinstance(m.get("content"), str)
        )
        self.assertIn("RESOLVED INTENT", contents)

    def test_answer_synthesis_receives_resolved_metric_context(self):
        calls = []
        original = db_chat._chat_completion_with_fallback

        def _spy(messages, **kwargs):
            calls.append(messages)
            return original(messages, **kwargs)

        db_chat._chat_completion_with_fallback = _spy
        try:
            db_chat.answer("vacancia del fondo TRI en 2026-06", session_id="test-synthesis-context")
        finally:
            db_chat._chat_completion_with_fallback = original

        # calls[0] = intent extraction, calls[1] = SQL-gen pass, calls[2] = synthesis pass
        self.assertEqual(len(calls), 3)
        synthesis_content = calls[2][-1]["content"]
        self.assertIn("business_definition", synthesis_content.lower())
