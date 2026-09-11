"""Gap C: noi_mensual/ingresos_mensual deben materializarse tambien por
activo_key individual (Apo4501, Apo4700), no solo bajo el agregado legacy
'Apoquindo' -- ver docs/A3_POST_A3.3_GAP_REGISTER.md (Gap C) y
docs/matriz-claves-ambiguas-apoquindo.md.

Todos los tests corren contra una DB aislada en tmp_path (baseline.sql +
migrations via el fixture `tmp_db` de tests/conftest.py), nunca contra
memory/agente_toesca_v2.db, e ingieren solo el fixture sintetico ya
existente en tests/db/test_ingest_er_apoquindo.py.
"""
from __future__ import annotations

import importlib

import pytest

from tests.db.test_ingest_er_apoquindo import _build_fixture_xlsx
from tools.db import ingest_er_apoquindo


@pytest.fixture
def apoquindo_db(tmp_db_path, tmp_db, tmp_path, monkeypatch):
    """DB aislada (baseline+migrations) con el fixture sintetico de
    Apo4501/Apo4700 ya ingerido. Redirige get_conn() (usado internamente por
    consolidate_noi_tri.py / consolidate_ingresos_tri.py) a esta DB, nunca a
    memory/agente_toesca_v2.db."""
    import tools.db.connection as dbconn

    monkeypatch.setattr(dbconn, "DEFAULT_DB_PATH", tmp_db_path)

    fixture_xlsx = _build_fixture_xlsx(str(tmp_path / "fixture_build"))
    result = ingest_er_apoquindo.persist(fixture_xlsx, conn=tmp_db)
    assert result["status"] == "inserted"
    assert result["rows"] == 60

    return tmp_db_path, tmp_db


def _rows_por_entidad(conn, kpi: str, entidad_key: str) -> dict[str, float]:
    cur = conn.execute(
        "SELECT periodo, valor FROM derived_kpi WHERE entidad_tipo='activo' "
        "AND kpi=? AND entidad_key=? ORDER BY periodo",
        (kpi, entidad_key),
    )
    return {r["periodo"]: r["valor"] for r in cur.fetchall()}


def _suma_raw(conn, columna_seccion_filtro: str, activo_keys: list[str]) -> dict[str, float]:
    """Replica manual (independiente del script) de la suma esperada, para
    no depender del propio codigo bajo prueba al calcular el valor esperado."""
    placeholders = ",".join("?" for _ in activo_keys)
    if columna_seccion_filtro == "noi":
        where_extra = "es_operacional=1"
    else:
        where_extra = "seccion='INGRESOS_OPERACION'"
    cur = conn.execute(
        f"SELECT periodo, SUM(COALESCE(monto_uf, monto_clp)) AS v FROM raw_er_activo_line "
        f"WHERE {where_extra} AND superseded_at IS NULL AND activo_key IN ({placeholders}) "
        f"GROUP BY periodo",
        activo_keys,
    )
    return {r["periodo"]: r["v"] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# NOI
# ---------------------------------------------------------------------------

def test_noi_apo4501_individual_vacio_antes_de_consolidar(apoquindo_db):
    _, conn = apoquindo_db
    antes = _rows_por_entidad(conn, "noi_mensual", "Apo4501")
    assert antes == {}


def test_noi_apo4501_individual_tras_consolidar(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_noi_tri = importlib.import_module("scripts.consolidate_noi_tri")
    with pytest.raises(ValueError):
        # La DB de prueba solo tiene datos de Apo4501/Apo4700 -- el resto de
        # los 7 componentes TRI no tiene raw_er_activo_line, por lo que
        # noi_mes(TRI) queda vacio y el print final de main() revienta en
        # min()/max() de un dict vacio. Esto es esperado en este fixture
        # acotado y no afecta lo que este test verifica (la materializacion
        # por activo, que ya se commiteo antes de ese print).
        consolidate_noi_tri.main()

    apo4501 = _rows_por_entidad(conn, "noi_mensual", "Apo4501")
    esperado = _suma_raw(conn, "noi", ["Apo4501"])
    assert apo4501 == esperado
    assert len(apo4501) == 3  # 2024-12, 2025-01, 2025-02


def test_noi_apo4700_individual_tras_consolidar(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_noi_tri = importlib.import_module("scripts.consolidate_noi_tri")
    with pytest.raises(ValueError):
        consolidate_noi_tri.main()

    apo4700 = _rows_por_entidad(conn, "noi_mensual", "Apo4700")
    esperado = _suma_raw(conn, "noi", ["Apo4700"])
    assert apo4700 == esperado
    assert len(apo4700) == 3


def test_noi_apoquindo_agregado_sigue_siendo_suma_exacta(apoquindo_db):
    """No-regresion: 'Apoquindo' debe seguir existiendo y seguir siendo
    exactamente Apo4501 + Apo4700, igual que antes del cambio."""
    db_path, conn = apoquindo_db
    consolidate_noi_tri = importlib.import_module("scripts.consolidate_noi_tri")
    with pytest.raises(ValueError):
        consolidate_noi_tri.main()

    agregado = _rows_por_entidad(conn, "noi_mensual", "Apoquindo")
    apo4501 = _rows_por_entidad(conn, "noi_mensual", "Apo4501")
    apo4700 = _rows_por_entidad(conn, "noi_mensual", "Apo4700")
    assert agregado.keys() == apo4501.keys() == apo4700.keys()
    for periodo in agregado:
        assert agregado[periodo] == pytest.approx(apo4501[periodo] + apo4700[periodo])


def test_noi_unidad_uf_consistente(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_noi_tri = importlib.import_module("scripts.consolidate_noi_tri")
    with pytest.raises(ValueError):
        consolidate_noi_tri.main()

    rows = conn.execute(
        "SELECT DISTINCT unidad, formula FROM derived_kpi WHERE entidad_tipo='activo' "
        "AND kpi='noi_mensual' AND entidad_key IN ('Apo4501','Apo4700','Apoquindo')"
    ).fetchall()
    assert {(r["unidad"], r["formula"]) for r in rows} == {("UF", "raw_er_noi_v1")}


def test_noi_consolidar_dos_veces_no_duplica(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_noi_tri = importlib.import_module("scripts.consolidate_noi_tri")
    with pytest.raises(ValueError):
        consolidate_noi_tri.main()
    n1 = conn.execute(
        "SELECT COUNT(*) FROM derived_kpi WHERE entidad_tipo='activo' AND kpi='noi_mensual' "
        "AND entidad_key IN ('Apo4501','Apo4700')"
    ).fetchone()[0]

    with pytest.raises(ValueError):
        consolidate_noi_tri.main()
    n2 = conn.execute(
        "SELECT COUNT(*) FROM derived_kpi WHERE entidad_tipo='activo' AND kpi='noi_mensual' "
        "AND entidad_key IN ('Apo4501','Apo4700')"
    ).fetchone()[0]

    assert n1 == 6  # 3 periodos x 2 activos
    assert n1 == n2  # re-correr no duplica


def test_noi_mensual_activo_analytics_executor_encuentra_apo4501(apoquindo_db):
    """Cierra el sintoma original de Gap C: la via gobernada
    (noi_mensual_activo) debe dejar de devolver 0 filas para Apo4501."""
    from pathlib import Path

    from tools.analytics.executor import AnalyticsExecutor, AnalyticsQueryRequest

    db_path, conn = apoquindo_db
    consolidate_noi_tri = importlib.import_module("scripts.consolidate_noi_tri")
    with pytest.raises(ValueError):
        consolidate_noi_tri.main()

    executor = AnalyticsExecutor(Path(db_path))
    req = AnalyticsQueryRequest(
        metric="noi_mensual_activo", assets=("Apo4501",), period="2024-12", period_end="2025-02"
    )
    result = executor.execute(req)
    assert len(result.rows) == 3
    valores = {row.period: row.value for row in result.rows}
    esperado = _suma_raw(conn, "noi", ["Apo4501"])
    assert valores == esperado


# ---------------------------------------------------------------------------
# Ingresos (mismo patron)
# ---------------------------------------------------------------------------

def test_ingresos_apo4501_individual_tras_consolidar(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_ingresos_tri = importlib.import_module("scripts.consolidate_ingresos_tri")
    with pytest.raises(ValueError):
        consolidate_ingresos_tri.main()

    apo4501 = _rows_por_entidad(conn, "ingresos_mensual", "Apo4501")
    esperado = _suma_raw(conn, "ingresos", ["Apo4501"])
    assert apo4501 == esperado
    assert len(apo4501) == 3


def test_ingresos_apoquindo_agregado_sigue_siendo_suma_exacta(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_ingresos_tri = importlib.import_module("scripts.consolidate_ingresos_tri")
    with pytest.raises(ValueError):
        consolidate_ingresos_tri.main()

    agregado = _rows_por_entidad(conn, "ingresos_mensual", "Apoquindo")
    apo4501 = _rows_por_entidad(conn, "ingresos_mensual", "Apo4501")
    apo4700 = _rows_por_entidad(conn, "ingresos_mensual", "Apo4700")
    assert agregado.keys() == apo4501.keys() == apo4700.keys()
    for periodo in agregado:
        assert agregado[periodo] == pytest.approx(apo4501[periodo] + apo4700[periodo])


def test_ingresos_consolidar_dos_veces_no_duplica(apoquindo_db):
    db_path, conn = apoquindo_db
    consolidate_ingresos_tri = importlib.import_module("scripts.consolidate_ingresos_tri")
    with pytest.raises(ValueError):
        consolidate_ingresos_tri.main()
    n1 = conn.execute(
        "SELECT COUNT(*) FROM derived_kpi WHERE entidad_tipo='activo' AND kpi='ingresos_mensual' "
        "AND entidad_key IN ('Apo4501','Apo4700')"
    ).fetchone()[0]

    with pytest.raises(ValueError):
        consolidate_ingresos_tri.main()
    n2 = conn.execute(
        "SELECT COUNT(*) FROM derived_kpi WHERE entidad_tipo='activo' AND kpi='ingresos_mensual' "
        "AND entidad_key IN ('Apo4501','Apo4700')"
    ).fetchone()[0]

    assert n1 == 6
    assert n1 == n2
