"""Tests del parser y ingester de EEFFs TRI por serie."""
import os
import sqlite3

import pytest

from tools.db.ingest_eeff_tri_series import parse_eeff_tri_notas, ingest_parsed_data
from tools.db.connection import apply_migrations, get_conn_for

TEXTO_2025 = """
(22)  Cuotas emitidas

El valor de las cuotas suscritas y pagadas del Fondo al 31 de diciembre de 2025 tienen
un valor cuota de $ 31.869,3926 para la Serie A, $ 32.252,4814 para la Serie C y
$ 32.390,2518 para la Serie I. El valor de las cuotas
suscritas y pagadas del Fondo al 31 de diciembre de 2024 tienen un valor cuota de $ 28.927,7231para la Serie
A, $ 29.311,3182 para la Serie C y $ 29.450,0778 para la Serie I.

31 de Diciembre de 2025
Serie A
Fecha
31 de Diciembre de 2025

31 de Diciembre de 2025
Serie C
Fecha
31 de Diciembre de 2025

31 de Diciembre de 2025
Serie I
Fecha
31 de Diciembre de 2025

Por Emitir  Comprometidas
-

-

Suscritas
475.667

Pagadas
475.667

Por Emitir  Comprometidas
-

-

Suscritas
1.252.928

Pagadas
1.252.928

Por Emitir  Comprometidas
-

-

Suscritas
1.091.101

Pagadas
1.091.101
"""


# ── Parser tests ────────────────────────────────────────────────────────────

def test_parse_valor_cuota_periodo_actual():
    result = parse_eeff_tri_notas(TEXTO_2025)
    assert "2025-12-31" in result
    vc = result["2025-12-31"]["valor_cuota"]
    assert abs(vc["A"] - 31869.3926) < 0.01
    assert abs(vc["C"] - 32252.4814) < 0.01
    assert abs(vc["I"] - 32390.2518) < 0.01


def test_parse_valor_cuota_periodo_anterior():
    result = parse_eeff_tri_notas(TEXTO_2025)
    assert "2024-12-31" in result
    vc = result["2024-12-31"]["valor_cuota"]
    assert abs(vc["A"] - 28927.7231) < 0.01
    assert abs(vc["C"] - 29311.3182) < 0.01
    assert abs(vc["I"] - 29450.0778) < 0.01


def test_parse_cuotas_suscritas():
    result = parse_eeff_tri_notas(TEXTO_2025)
    cuotas = result["2025-12-31"]["cuotas"]
    assert cuotas["A"] == 475667.0
    assert cuotas["C"] == 1252928.0
    assert cuotas["I"] == 1091101.0


def test_parse_texto_sin_nota_cuotas():
    """No debe explotar con texto sin la sección relevante."""
    result = parse_eeff_tri_notas("Texto sin datos relevantes")
    assert result == {}


# ── Ingester tests ───────────────────────────────────────────────────────────

def _make_db(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    conn.execute(
        """INSERT OR IGNORE INTO raw_uf_diaria(fecha, valor, fuente)
           VALUES('2025-12-31', 39695.94, 'test')"""
    )
    conn.commit()
    conn.close()


def test_ingest_escribe_valor_cuota_contable(tmp_db_path):
    _make_db(tmp_db_path)
    parsed = {
        "2025-12-31": {
            "valor_cuota": {"A": 31869.3926, "C": 32252.4814, "I": 32390.2518},
            "cuotas": {"A": 475667.0, "C": 1252928.0, "I": 1091101.0},
        }
    }
    ingest_parsed_data(parsed, "test_eeff.pdf", "abc123", tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT nemotecnico, precio_clp, precio_uf FROM raw_valor_cuota_contable "
        "WHERE fecha='2025-12-31' ORDER BY nemotecnico"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    nemos = [r[0] for r in rows]
    assert "CFITOERI1A" in nemos
    a_row = next(r for r in rows if r[0] == "CFITOERI1A")
    assert abs(a_row[1] - 31869.3926) < 0.01
    # precio_uf = 31869.3926 / 39695.94 ≈ 0.8029
    assert a_row[2] is not None and abs(a_row[2] - 0.8029) < 0.01


def test_ingest_escribe_cuotas_en_circulacion(tmp_db_path):
    _make_db(tmp_db_path)
    parsed = {
        "2025-12-31": {
            "valor_cuota": {},
            "cuotas": {"A": 475667.0, "C": 1252928.0, "I": 1091101.0},
        }
    }
    ingest_parsed_data(parsed, "test_eeff.pdf", "abc123", tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT nemotecnico, cuotas FROM raw_cuota_en_circulacion "
        "WHERE fecha='2025-12-31' ORDER BY nemotecnico"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    d = {r[0]: r[1] for r in rows}
    assert d["CFITOERI1A"] == 475667.0
    assert d["CFITOERI1C"] == 1252928.0
    assert d["CFITOERI1I"] == 1091101.0


def test_ingest_idempotente(tmp_db_path):
    """Ejecutar dos veces con el mismo file_hash no duplica filas."""
    _make_db(tmp_db_path)
    parsed = {
        "2025-12-31": {
            "valor_cuota": {"A": 31869.0},
            "cuotas": {"A": 475667.0},
        }
    }
    ingest_parsed_data(parsed, "test.pdf", "samehash", tmp_db_path)
    ingest_parsed_data(parsed, "test.pdf", "samehash", tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM raw_valor_cuota_contable WHERE file_hash='samehash'"
    ).fetchone()[0]
    conn.close()
    assert n == 1
