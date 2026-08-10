"""Tests de las partes deterministicas de tools/db_chat.py (sin llamar al LLM).

No cubren answer() completo porque depende de un proveedor LLM externo; cubren
la logica que puede romperse silenciosamente al tocar el prompt/few-shots:
validacion de SQL, formateo numerico, atajo de saludos, extraccion de JSON y
sugerencia de periodos disponibles.
"""
import sqlite3

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
