"""Read-only reconciliation of the vacancy component breakdown against the
real DB, pinned as regression evidence for the QA repro in the "vacancy
decomposition" stage (Apo4501/Apo4700 inversion, TRI 10/11 coverage)."""
from pathlib import Path
import sqlite3

DB = Path("memory/agente_toesca_v2.db")


def _connect():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def test_apo_components_june_2026_reconcile_against_the_qa_repro():
    con = _connect()
    rows = {r[0]: r for r in con.execute(
        "SELECT activo_key, m2_gla, m2_vacantes, vacancia_pct FROM v_vacancia_activo "
        "WHERE activo_key IN ('Apo4501','Apo4700') AND periodo='2026-06'"
    ).fetchall()}
    apo4501, apo4700 = rows["Apo4501"], rows["Apo4700"]
    assert apo4501[2] == 1765.13492 and round(apo4501[3] * 100, 2) == 7.84
    assert apo4700[2] == 1647.2 and round(apo4700[3] * 100, 2) == 22.91
    # The QA repro's contradiction: 22.91% (Apo4700) is greater than 7.84%
    # (Apo4501), the opposite of what the flawed answer asserted.
    assert apo4700[3] > apo4501[3]


def test_apo_component_identities_are_resolvable_to_real_display_names():
    con = _connect()
    names = dict(con.execute("SELECT activo_key, nombre FROM dim_activo WHERE activo_key IN ('Apo4501','Apo4700')").fetchall())
    assert names["Apo4501"] == "Apoquindo 4501"
    assert names["Apo4700"] == "Apoquindo 4700"


def test_tri_components_june_2026_reconcile_against_the_qa_repro():
    con = _connect()
    rows = {r[0]: r for r in con.execute(
        "SELECT v.activo_key, v.m2_gla, v.m2_vacantes, v.vacancia_pct FROM v_vacancia_activo v "
        "JOIN dim_activo a ON a.activo_key=v.activo_key WHERE a.fondo_key='TRI' AND v.periodo='2026-06'"
    ).fetchall()}
    assert round(rows["Mall Curicó"][3] * 100, 2) == 22.75 and rows["Mall Curicó"][2] == 2476.0
    assert round(rows["Apo3001"][3] * 100, 2) == 36.20 and round(rows["Apo3001"][2], 1) == 1632.6
    assert round(rows["Viña Centro"][3] * 100, 2) == 0.78 and round(rows["Viña Centro"][2], 2) == 199.83


def test_tri_zero_vacancy_components_are_observed_zero_not_missing():
    con = _connect()
    rows = {r[0]: r for r in con.execute(
        "SELECT v.activo_key, v.m2_gla, v.m2_vacantes FROM v_vacancia_activo v "
        "JOIN dim_activo a ON a.activo_key=v.activo_key WHERE a.fondo_key='TRI' AND v.periodo='2026-06'"
    ).fetchall()}
    zero_vacancy = {"Residencia Arturo Medina", "Residencia Candil", "Residencia Colombia",
                     "Residencia Coventry", "Residencia Padre Errázuriz", "Sucden", "INMOSA"}
    for key in zero_vacancy:
        assert rows[key][1] is not None  # GLA observed -> a real row exists
        assert rows[key][2] == 0  # observed zero, not absent


def test_tri_component_coverage_is_ten_of_eleven_vigente_assets():
    con = _connect()
    vigente = {row[0] for row in con.execute(
        "SELECT activo_key FROM dim_activo WHERE fondo_key='TRI' AND vigente_hasta IS NULL"
    ).fetchall()}
    assert len(vigente) == 11  # Strip Machalí excluded: divested (vigente_hasta='2025-08')

    observed = {row[0] for row in con.execute(
        "SELECT v.activo_key FROM v_vacancia_activo v JOIN dim_activo a ON a.activo_key=v.activo_key "
        "WHERE a.fondo_key='TRI' AND v.periodo='2026-06'"
    ).fetchall()}
    missing = vigente - observed
    assert missing == {"Residencia Domingo Calderón"}
    assert len(observed & vigente) == 10  # 10 of 11 -> PARTIAL, not COMPLETE
