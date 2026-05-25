"""Tests de los cálculos de NOI (puros, sobre series sintéticas)."""
import tools.noi_query as nq
from tools.db import repo_kpi
from tools.db.connection import apply_migrations, get_conn_for


def test_anual():
    serie = {"2025-01": 10.0, "2025-02": 20.0, "2024-12": 5.0}
    assert nq.anual(serie, 2025) == 30.0
    assert nq.anual(serie, 2024) == 5.0


def test_anualizado_con_meses_faltantes():
    # 2024 completo (cada mes = 10) → histórico mensual = 10.
    serie = {f"2024-{m:02d}": 10.0 for m in range(1, 13)}
    # 2025 solo ene, feb reales = 30 y 30.
    serie["2025-01"] = 30.0
    serie["2025-02"] = 30.0
    # anualizado 2025 = 30+30 (reales) + 10*10 (promedio histórico de mar..dic)
    assert nq.anualizado(serie, 2025) == 30.0 + 30.0 + 10 * 10.0


def test_u12m():
    serie = {f"2025-{m:02d}": float(m) for m in range(1, 13)}  # ene..dic = 1..12
    assert nq.u12m(serie, "2025-12") == sum(range(1, 13))
    # hasta junio: jul24..jun25, pero solo hay 2025 → ene..jun = 1..6
    assert nq.u12m(serie, "2025-06") == sum(range(1, 7))


def test_variacion_mom():
    serie = {"2025-01": 100.0, "2025-02": 110.0}
    assert abs(nq.variacion_mom(serie, "2025-02") - 0.1) < 1e-9


def test_variacion_yoy():
    serie = {"2024-03": 100.0, "2025-03": 150.0}
    assert abs(nq.variacion_yoy(serie, "2025-03") - 0.5) < 1e-9


def test_serie_mensual_ponderado(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    # Apoquindo participa 0.3 (de la migración 007)
    repo_kpi.upsert(conn, "activo", "Apoquindo", "2025-01", "noi_mensual", 1000.0, "UF", "cdg_noi_real_v1")
    # 100%
    s100 = nq.serie_mensual(conn, "activo", "Apoquindo", ponderado=False)
    assert s100["2025-01"] == 1000.0
    # ponderado por 0.3
    sp = nq.serie_mensual(conn, "activo", "Apoquindo", ponderado=True)
    assert abs(sp["2025-01"] - 300.0) < 1e-9
    conn.close()


def test_serie_mensual_fondo_suma_activos(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    # A&R Apoquindo tiene Apoquindo (0.3) y Apo3001 (1.0)
    repo_kpi.upsert(conn, "activo", "Apoquindo", "2025-01", "noi_mensual", 1000.0, "UF", "cdg_noi_real_v1")
    repo_kpi.upsert(conn, "activo", "Apo3001", "2025-01", "noi_mensual", 500.0, "UF", "cdg_noi_real_v1")
    s100 = nq.serie_mensual(conn, "fondo", "A&R Apoquindo", ponderado=False)
    assert s100["2025-01"] == 1500.0
    sp = nq.serie_mensual(conn, "fondo", "A&R Apoquindo", ponderado=True)
    assert abs(sp["2025-01"] - (1000*0.3 + 500*1.0)) < 1e-9
    conn.close()


def test_serie_mensual_categoria(tmp_db_path):
    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    # Centros Comerciales = Viña Centro + Mall Curicó
    repo_kpi.upsert(conn, "activo", "Viña Centro", "2025-01", "noi_mensual", 200.0, "UF", "cdg_noi_real_v1")
    repo_kpi.upsert(conn, "activo", "Mall Curicó", "2025-01", "noi_mensual", 100.0, "UF", "cdg_noi_real_v1")
    s = nq.serie_mensual(conn, "categoria", "Centros Comerciales", ponderado=False)
    assert s["2025-01"] == 300.0
    conn.close()
