"""
Consolida ingresos mensual e ingresos U12M del fondo TRI, con la misma
metodología usada para NOI (ver consolidate_noi_tri.py):

1. ingresos_mensual por activo (100%, persistido en derived_kpi) = SUM(monto_uf)
   de raw_er_activo_line WHERE seccion='INGRESOS_OPERACION' (ingreso
   operacional, excluye 'INGRESO_FUERA_EXPLOTACION'), EN BRUTO — todas las
   cuentas de ingreso, sin excluir traspaso/recupero ni parking. Revisado
   activo por activo y a nivel fondo TRI el 2026-07-20 contra las planillas
   fuente de cada activo: el usuario confirmó que el ingreso bruto (sin
   ninguna exclusión) es el criterio correcto tanto por activo como para el
   agregado TRI — se descartó la exclusión de pass-through introducida el
   2026-07-14 (que solo se había validado contra un archivo de referencia
   estático, RAW/NOI tri.xlsx, nunca contra el cálculo en vivo del usuario).
2. ingresos_mes(TRI) = suma ponderada por participación efectiva de TRI en
   cada activo (misma tabla de participaciones que NOI, incluyendo la
   excepción Apo3001=1.0), usando el mismo ingreso bruto de (1).
3. ingresos_u12m(TRI) solo para periodos con 12 meses trailing completos.

Strip Machalí fue vendido sept-2025 (dim_activo.vigente_hasta='2025-08',
migración 050): igual que en NOI, se detectó un hueco sistemático en
ingresos_mes(TRI) de abr-2025 a ago-2025 al validar contra el cálculo del
usuario. La consolidación ya no exige periodos_comunes estrictos entre
todos los componentes: respeta vigente_hasta por activo (ver
_vigencia_tri), así un activo divestido deja de exigirse (y de sumar)
desde el mes siguiente a su venta, sin bloquear el resto de la serie.
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
    "Strip Machalí": ["Strip Machalí"],
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
    "Strip Machalí": "Strip Machalí",
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


def _vigencia_tri(conn) -> dict[str, str | None]:
    """activo_key (dim_activo) -> vigente_hasta (YYYY-MM) o None si sigue vigente."""
    cur = conn.execute("SELECT activo_key, vigente_hasta FROM dim_activo WHERE fondo_key='TRI'")
    return {r["activo_key"]: r["vigente_hasta"] for r in cur.fetchall()}


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


def _ingresos_mes_tri(
    series: dict[str, dict[str, float]],
    participaciones: dict[str, float],
    vigencia: dict[str, str | None],
) -> dict[str, float]:
    """Suma ponderada, exigiendo dato solo de los componentes VIGENTES en cada
    periodo (evita sumas parciales engañosas cuando algún activo aún no
    reporta ese mes, sin bloquear la serie cuando un activo fue divestido —
    ver docstring del módulo sobre Strip Machalí)."""
    todos_los_periodos = set.union(*(set(s) for s in series.values()))
    acc: dict[str, float] = {}
    for periodo in todos_los_periodos:
        vigentes = [
            key for key in series
            if vigencia.get(key) is None or periodo <= vigencia[key]
        ]
        if not all(periodo in series[key] for key in vigentes):
            continue
        total = 0.0
        for key in vigentes:
            part = participaciones[_COMPONENTES_PART[key]]
            total += series[key][periodo] * part
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
        vigencia = _vigencia_tri(conn)

        series = {}
        for key, raw_keys in _COMPONENTES_RAW.items():
            series[key] = _ingresos_activo_raw(conn, raw_keys)
            part = participaciones[_COMPONENTES_PART[key]]
            v = series[key]
            print(f"  {key} (part. {part}): {len(v)} periodos ({min(v) if v else '-'} a {max(v) if v else '-'})")

        # Persistir ingresos_mensual por activo (100%, BRUTO), reemplazando el
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

        ingresos_mes = _ingresos_mes_tri(series, participaciones, vigencia)
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
