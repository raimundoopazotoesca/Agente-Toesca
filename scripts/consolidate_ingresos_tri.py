"""
Consolida ingresos mensual e ingresos U12M del fondo TRI, con la misma
metodología usada para NOI (ver consolidate_noi_tri.py):

1. ingresos_mensual por activo (100%) = SUM(monto_uf) de raw_er_activo_line
   WHERE seccion='INGRESOS_OPERACION' (ingreso operacional, excluye
   'INGRESO_FUERA_EXPLOTACION'). Se usa monto_uf si existe (fuentes en CLP,
   ej. Viña/Curicó); si no, monto_clp (fuentes que ya vienen en UF, ej.
   INMOSA/Apo3001/Sucden/Torre A/Boulevard — ver comentarios en los
   ingest_er_*.py).
2. ingresos_mes(TRI) = suma ponderada por participación efectiva de TRI en
   cada activo (misma tabla de participaciones que NOI, incluyendo la
   excepción Apo3001=1.0).
3. ingresos_u12m(TRI) solo para periodos con 12 meses trailing completos.
"""
from tools.db.connection import get_conn

# activo_key en derived_kpi (ingresos_mensual, agregado) -> lista de
# activo_key en raw_er_activo_line que lo componen.
_COMPONENTES_RAW = {
    "Apo3001": ["Apo3001"],
    "Apoquindo": ["Apo4501", "Apo4700"],
    "INMOSA": ["INMOSA"],
    "Mall Curicó": ["Mall Curicó"],
    "PT": ["Torre A", "Boulevard"],
    "Sucden": ["Sucden"],
    "Viña Centro": ["Viña Centro"],
}
# activo_key (ingresos_mensual) -> activo_key en v_activo_fondo_efectivo
_COMPONENTES_PART = {
    "Apo3001": "Apo3001",
    "Apoquindo": "Apo4501",
    "INMOSA": "INMOSA",
    "Mall Curicó": "Mall Curicó",
    "PT": "Torre A",
    "Sucden": "Sucden",
    "Viña Centro": "Viña Centro",
}
_INGRESOS_MENSUAL_FORMULA = "raw_er_ingresos_v1"
_INGRESOS_MES_FORMULA = (
    "SUM(ingresos_mensual(activo) x participacion_efectiva(activo, TRI)) via v_activo_fondo_efectivo, "
    "Apo3001 excepcion: 1.0 (fondo dueño 100% de la sociedad Chañarcillo)"
)
_INGRESOS_U12M_FORMULA = "SUM ingresos Fondo TRI (ponderado) 12 meses trailing"

# Misma excepción que NOI: el ingreso ingestado de Apo3001 ya es la
# contabilidad propia de Chañarcillo (neta del 68.5%), y TRI es dueño del
# 100% de Chañarcillo.
_PARTICIPACION_OVERRIDE = {"Apo3001": 1.0}


def _participaciones_tri(conn) -> dict[str, float]:
    cur = conn.execute(
        "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo WHERE fondo_key='TRI'"
    )
    part = {r["activo_key"]: r["participacion_efectiva"] for r in cur.fetchall()}
    part.update(_PARTICIPACION_OVERRIDE)
    return part


def _ingresos_activo_raw(conn, activo_keys_raw: list[str]) -> dict[str, float]:
    acc: dict[str, float] = {}
    placeholders = ",".join("?" for _ in activo_keys_raw)
    cur = conn.execute(
        f"SELECT periodo, SUM(COALESCE(monto_uf, monto_clp)) AS ingreso FROM raw_er_activo_line "
        f"WHERE seccion='INGRESOS_OPERACION' AND superseded_at IS NULL AND activo_key IN ({placeholders}) "
        f"GROUP BY periodo",
        activo_keys_raw,
    )
    for r in cur.fetchall():
        acc[r["periodo"]] = acc.get(r["periodo"], 0.0) + r["ingreso"]
    return dict(sorted(acc.items()))


def _ingresos_mes_tri(series: dict[str, dict[str, float]], participaciones: dict[str, float]) -> dict[str, float]:
    """Suma ponderada, solo para periodos en que TODOS los componentes tienen
    dato (evita sumas parciales engañosas cuando algún activo aún no reporta
    ese mes — ver Sucden/INMOSA con cortes distintos a Apo3001/PT/etc.)."""
    periodos_comunes = set.intersection(*(set(s) for s in series.values()))
    acc: dict[str, float] = {}
    for periodo in periodos_comunes:
        total = 0.0
        for key, comp in series.items():
            part = participaciones[_COMPONENTES_PART[key]]
            total += comp[periodo] * part
        acc[periodo] = total
    return dict(sorted(acc.items()))


def _prev(periodo: str) -> str:
    y, m = int(periodo[:4]), int(periodo[5:7])
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f"{y}-{m:02d}"


def _u12m(serie_mes: dict[str, float]) -> dict[str, float]:
    out = {}
    for periodo in serie_mes:
        meses, ok = [], True
        p = periodo
        for _ in range(12):
            if p not in serie_mes:
                ok = False
                break
            meses.append(serie_mes[p])
            p = _prev(p)
        if ok:
            out[periodo] = sum(meses)
    return out


def main():
    with get_conn() as conn:
        participaciones = _participaciones_tri(conn)

        series = {}
        for key, raw_keys in _COMPONENTES_RAW.items():
            series[key] = _ingresos_activo_raw(conn, raw_keys)
            part = participaciones[_COMPONENTES_PART[key]]
            v = series[key]
            print(f"  {key} (part. {part}): {len(v)} periodos ({min(v) if v else '-'} a {max(v) if v else '-'})")

        # Persistir ingresos_mensual por activo (100%), reemplazando el
        # recipe anterior si existía.
        for key, serie in series.items():
            conn.execute(
                "DELETE FROM derived_kpi WHERE entidad_tipo='activo' AND entidad_key=? AND "
                "kpi='ingresos_mensual' AND formula=?",
                (key, _INGRESOS_MENSUAL_FORMULA),
            )
            for periodo, valor in serie.items():
                conn.execute(
                    "INSERT INTO derived_kpi (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula) "
                    "VALUES ('activo',?,?,'ingresos_mensual',?,'UF',?)",
                    (key, periodo, valor, _INGRESOS_MENSUAL_FORMULA),
                )

        ingresos_mes = _ingresos_mes_tri(series, participaciones)
        ingresos_u12m = _u12m(ingresos_mes)

        conn.execute(
            "DELETE FROM derived_kpi WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND kpi='ingresos_mes'"
        )
        conn.execute(
            "DELETE FROM derived_kpi WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND kpi='ingresos_u12m'"
        )
        for periodo, valor in ingresos_mes.items():
            conn.execute(
                "INSERT INTO derived_kpi (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula) "
                "VALUES ('fondo','TRI',?,'ingresos_mes',?,'UF',?)",
                (periodo, valor, _INGRESOS_MES_FORMULA),
            )
        for periodo, valor in ingresos_u12m.items():
            conn.execute(
                "INSERT INTO derived_kpi (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula) "
                "VALUES ('fondo','TRI',?,'ingresos_u12m',?,'UF',?)",
                (periodo, valor, _INGRESOS_U12M_FORMULA),
            )
        conn.commit()

        print(f"\ningresos_mes TRI: {len(ingresos_mes)} periodos ({min(ingresos_mes)} a {max(ingresos_mes)})")
        print(f"ingresos_u12m TRI: {len(ingresos_u12m)} periodos ({min(ingresos_u12m)} a {max(ingresos_u12m)})")
        ult = max(ingresos_mes)
        print(f"\nÚltimo mes ({ult}): ingresos_mes = {ingresos_mes[ult]:,.1f} UF")
        if ult in ingresos_u12m:
            print(f"U12M a {ult}: {ingresos_u12m[ult]:,.1f} UF")


if __name__ == "__main__":
    main()
