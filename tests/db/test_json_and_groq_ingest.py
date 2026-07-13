import json
import sys

import pytest

from tools.db.connection import apply_migrations, get_conn_for
from tools.db.ingest_eeff_tri_groq import ingest_groq_result


def test_ingest_from_json_uses_canonical_tables_and_is_idempotent(
    tmp_db_path, tmp_path, monkeypatch
):
    from scripts import ingest_from_json

    apply_migrations(tmp_db_path)
    payload = {
        "periodos_reportados": ["2026-03"],
        "lineas": [
            {
                "periodo": "2026-03",
                "section": "Estado de situación",
                "cuenta_codigo": "1000",
                "cuenta_nombre": "Activo",
                "monto_clp": 1000,
            }
        ],
        "valor_cuota": [
            {
                "fecha": "2026-03-31",
                "nemotecnico": "CFITOERI1A",
                "precio_clp": 40000,
                "precio_uf": 1,
                "uf_dia": 40000,
                "cuotas": 10,
            }
        ],
        "dividendos": [
            {
                "fecha_pago": "2026-03-15",
                "nemotecnico": "CFITOERI1A",
                "monto_clp_cuota": 500,
            }
        ],
    }
    json_path = tmp_path / "eeff.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(ingest_from_json, "DB_PATH", tmp_db_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ingest_from_json.py", "--fondo", "TRI", "--json", str(json_path)],
    )

    ingest_from_json.main()
    ingest_from_json.main()

    conn = get_conn_for(tmp_db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM raw_eeff_line").fetchone()[0] == 1
        vc = conn.execute(
            "SELECT fecha FROM raw_valor_cuota_contable"
        ).fetchone()
        assert vc[0] == "2026-03-31"
        div = conn.execute(
            "SELECT fecha_pago, tipo FROM raw_dividendo"
        ).fetchone()
        assert tuple(div) == ("2026-03-15", "dividendo")
        assert conn.execute("SELECT COUNT(*) FROM raw_dividendo").fetchone()[0] == 1
    finally:
        conn.close()


def test_ingest_from_json_rejects_month_when_daily_date_is_required():
    from scripts.ingest_from_json import _normalize_dividendo

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _normalize_dividendo(
            {"fecha_pago": "2026-03", "nemotecnico": "X", "monto_clp_cuota": 1},
            0,
        )


def test_groq_dividend_writes_raw_table_and_remains_visible(tmp_db_path):
    apply_migrations(tmp_db_path)
    parsed = {
        "periodos": [],
        "dividendos": [
            {
                "fecha_pago": "2026-03-15",
                "serie": "A",
                "monto_por_cuota_clp": 500,
                "tipo": "definitivo",
            }
        ],
    }

    first = ingest_groq_result(parsed, "eeff.pdf", "hash-1", tmp_db_path)
    second = ingest_groq_result(parsed, "eeff.pdf", "hash-1", tmp_db_path)

    assert first["dividendos_insertados"] == 1
    assert second["dividendos_insertados"] == 0
    conn = get_conn_for(tmp_db_path)
    try:
        raw = conn.execute(
            "SELECT tipo, monto_clp_cuota FROM raw_dividendo"
        ).fetchone()
        assert tuple(raw) == ("dividendo", 500)
        assert conn.execute("SELECT COUNT(*) FROM fact_dividendo").fetchone()[0] == 1
    finally:
        conn.close()
