"""Test de humo: fetch_fondo inyecta datos reales de mercado en page4 para Apo."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from tools.db.connection import apply_migrations


def test_merge_mercado_rows_con_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO raw_mercado_oficinas
           (periodo, proveedor, submercado, clase, es_total, inventario_m2,
            absorcion_trim_m2, absorcion_u12m_m2, vacancia_pct, renta_uf_m2,
            renta_usd_m2, produccion_trim_m2, produccion_u12m_m2, construccion_m2,
            file_hash, source_row)
           VALUES ('2025-09','JLL','Las Condes (CBD)','Total',0,1733422,9388,39913,
                    5.6,0.57,24.63,7013,36704,104187,'HASH1',0)"""
    )
    con.commit()
    con.close()

    filas = bf._fetch_mercado_rows(db_path, "2025-09")
    assert len(filas) == 1
    assert filas[0]["inventario_m2"] == 1733422.0
    assert filas[0]["vacancia_pct"] == 5.6


def test_merge_mercado_rows_sin_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    filas = bf._fetch_mercado_rows(db_path, "2025-09")
    assert filas == []
