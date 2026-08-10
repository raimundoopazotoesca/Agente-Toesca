"""Tests para tools.db.ingest_mercado_bodegas."""
from __future__ import annotations

import pytest

from tools.db import ingest_mercado_bodegas as mod
from tools.db.connection import apply_migrations, get_conn_for

TEXTO_GPS_1S_2026 = """Zona Clase Producción Inventario
Final
Participación
de Mercado
Vacancia
Actual
Tasa de
Vacancia Actual
Vacancia
Anterior Absorción Precio Promedio
Arriendo
Precio Promedio
Arriendo
(m²) (m²) (%) (m²) (%) (m²) (m²) (UF/m2
) (US$/m2
)
Centro A/B - 289.789 4,6% 1.340 0,5% - -1.340 0,226 9,21
Nor-Poniente A/B - 1.308.661 20,6% 40.475 3,1% 48.739 8.264 0,161 6,55
Norte A/B 8.000 1.430.841 22,5% 44.049 3,1% 45.682 9.633 0,157 6,39
Poniente A/B - 2.452.838 38,6% 201.620 8,2% 228.978 27.358 0,154 6,26
Sur A/B 119.000 874.007 13,8% 117.718 13,5% 62.778 64.060 0,146 5,94
Gran Santiago 127.000 6.356.136 100% 405.201 6,37% 386.177 107.976 0,146 5,93"""


def test_parse_tabla_bodegas_ok():
    filas = mod.parse_tabla_bodegas(TEXTO_GPS_1S_2026)
    assert len(filas) == 6
    centro = next(f for f in filas if f["zona"] == "Centro")
    assert centro["clase"] == "A/B"
    assert centro["es_total"] == 0
    assert centro["produccion_m2"] is None
    assert centro["inventario_final_m2"] == 289789.0
    assert centro["participacion_pct"] == 4.6
    assert centro["vacancia_actual_m2"] == 1340.0
    assert centro["tasa_vacancia_pct"] == 0.5
    assert centro["vacancia_anterior_m2"] is None
    assert centro["absorcion_m2"] == -1340.0
    assert centro["precio_uf_m2"] == 0.226
    assert centro["precio_usd_m2"] == 9.21

    total = next(f for f in filas if f["zona"] == "Gran Santiago")
    assert total["es_total"] == 1
    assert total["clase"] is None
    assert total["produccion_m2"] == 127000.0
    assert total["tasa_vacancia_pct"] == 6.37


def test_parse_tabla_bodegas_zona_faltante():
    texto_incompleto = "\n".join(TEXTO_GPS_1S_2026.splitlines()[:-3])
    result = mod.validate(texto_incompleto, "2026-06")
    assert not result.ok
    assert any("Faltan" in e for e in result.errors)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    monkeypatch.setattr(mod, "DB_PATH", db_path)
    return db_path


def test_commit_inserta_filas(db):
    result = mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    assert result["status"] == "ok"
    assert result["filas_insertadas"] == 6
    assert result["filas_superseded"] == 0

    con = get_conn_for(db)
    n = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert n == 6


def test_commit_idempotente_mismo_texto(db):
    mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    result2 = mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    assert result2["status"] == "skipped_duplicate"
    assert result2["filas_insertadas"] == 0


def test_commit_reemplaza_periodo_con_texto_distinto(db):
    mod.commit(TEXTO_GPS_1S_2026, "2026-06")
    texto_v2 = TEXTO_GPS_1S_2026.replace("289.789", "300.000")
    result2 = mod.commit(texto_v2, "2026-06")
    assert result2["status"] == "ok"
    assert result2["filas_superseded"] == 6

    con = get_conn_for(db)
    vigentes = con.execute(
        "SELECT COUNT(*) FROM raw_mercado_bodegas WHERE periodo='2026-06' AND superseded_at IS NULL"
    ).fetchone()[0]
    con.close()
    assert vigentes == 6
