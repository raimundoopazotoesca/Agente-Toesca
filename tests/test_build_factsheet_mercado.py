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


def test_fetch_bodegas_mercado_con_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO raw_mercado_bodegas
           (periodo, zona, clase, es_total, produccion_m2, inventario_final_m2,
            participacion_pct, vacancia_actual_m2, tasa_vacancia_pct,
            vacancia_anterior_m2, absorcion_m2, precio_uf_m2, precio_usd_m2,
            file_hash, source_row)
           VALUES ('2026-06','Centro','A/B',0,NULL,289789,4.6,1340,0.5,NULL,-1340,0.226,9.21,'H',0),
                  ('2026-06','Gran Santiago',NULL,1,127000,6356136,100,405201,6.37,386177,107976,0.146,5.93,'H',5)"""
    )
    con.commit()
    con.close()

    filas = bf._fetch_bodegas_mercado(db_path, "2026-06")
    assert filas is not None
    assert filas[0]["zona"] == "Centro"
    assert filas[0]["inventario_final_m2"] == 289789.0
    assert filas[0]["tasa_vacancia_pct"] == 0.5
    assert filas[-1]["zona"] == "Gran Santiago"
    assert filas[-1]["es_total"] is True


def test_fetch_bodegas_mercado_sin_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    assert bf._fetch_bodegas_mercado(db_path, "2026-06") is None


def test_fetch_bodegas_evolucion_con_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    con = sqlite3.connect(db_path)
    con.execute(
        """INSERT INTO raw_mercado_bodegas_evolucion (semestre, anio, periodo_num, uf_m2, vacancia_pct, file_hash)
           VALUES ('2S-2015', 2015, 2, 0.119, 0.0995, 'H'),
                  ('1S-2016', 2016, 1, 0.118, 0.1228, 'H')"""
    )
    con.commit()
    con.close()

    evo = bf._fetch_bodegas_evolucion(db_path)
    assert evo == {
        "semestres": ["2S-2015", "1S-2016"],
        "uf_m2": [0.119, 0.118],
        "vacancia_pct": [9.95, 12.28],
        "periodos": ["2015-12", "2016-06"],
    }


def test_fetch_bodegas_evolucion_sin_datos(tmp_path):
    import build_factsheet as bf

    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    assert bf._fetch_bodegas_evolucion(db_path) is None
