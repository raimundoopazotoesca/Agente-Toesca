"""
Consolida NOI mensual y NOI U12M del fondo TRI, ponderando el NOI de cada
activo por la participación efectiva de TRI en ese activo (directa o vía
subfondos PT/Apo, según v_activo_fondo_efectivo). Misma metodología que
ingresos (ver consolidate_ingresos_tri.py) — fuente única: raw_er_activo_line
(nunca el CDG, ver [[feedback_no_usar_cdg]]).

1. noi_mensual por activo (100%) = SUM(COALESCE(monto_uf, monto_clp)) de
   raw_er_activo_line WHERE es_operacional=1 (ingresos + gastos operacionales,
   gastos ya vienen con signo negativo; excluye partidas fuera de explotación).
2. noi_mes(TRI) = suma ponderada por participación efectiva de TRI en cada
   activo, solo para periodos donde los 7 componentes tienen dato.
3. noi_u12m(TRI) solo para periodos con 12 meses trailing completos.

Propiedades bajo TRI y su participación efectiva:
  Apo3001 1.0 (excepción, ver [[feedback_participacion_sociedad_vs_activo]]),
  Apoquindo(=Apo4501/4700) 0.3, INMOSA 0.43, Mall Curicó 0.8,
  PT(=Torre A/Boulevard) 0.333, Sucden 1.0, Viña Centro 1.0.
"""
from tools.db.connection import get_conn

# activo_key en derived_kpi (noi_mensual, agregado) -> lista de activo_key
# en raw_er_activo_line que lo componen.
_COMPONENTES_RAW = {
    "Apo3001": ["Apo3001"],
    "Apoquindo": ["Apo4501", "Apo4700"],
    "INMOSA": ["INMOSA"],
    "Mall Curicó": ["Mall Curicó"],
    "PT": ["Torre A", "Boulevard"],
    "Sucden": ["Sucden"],
    "Viña Centro": ["Viña Centro"],
}
# activo_key (noi_mensual) -> activo_key en v_activo_fondo_efectivo
_COMPONENTES_PART = {
    "Apo3001": "Apo3001",
    "Apoquindo": "Apo4501",
    "INMOSA": "INMOSA",
    "Mall Curicó": "Mall Curicó",
    "PT": "Torre A",
    "Sucden": "Sucden",
    "Viña Centro": "Viña Centro",
}
_NOI_MENSUAL_FORMULA = "raw_er_noi_v1"
_NOI_MES_FORMULA = (
    "SUM(noi_mensual(activo) x participacion_efectiva(activo, TRI)) via v_activo_fondo_efectivo, "
    "Apo3001 excepcion: 1.0 (fondo dueño 100% de la sociedad Chañarcillo)"
)
_NOI_U12M_FORMULA = "SUM NOI Fondo TRI (ponderado) 12 meses trailing"

# El NOI ingestado de Apo3001 ya es la contabilidad propia de la sociedad
# Chañarcillo (neta del 68.5% que Chañarcillo posee del activo físico), y
# TRI es dueño del 100% de Chañarcillo.
_PARTICIPACION_OVERRIDE = {"Apo3001": 1.0}


def _participaciones_tri(conn) -> dict[str, float]:
    cur = conn.execute(
        "SELECT activo_key, participacion_efectiva FROM v_activo_fondo_efectivo WHERE fondo_key='TRI'"
    )
    part = {r["activo_key"]: r["participacion_efectiva"] for r in cur.fetchall()}
    part.update(_PARTICIPACION_OVERRIDE)
    return part


def _noi_activo_raw(conn, activo_keys_raw: list[str]) -> dict[str, float]:
    acc: dict[str, float] = {}
    placeholders = ",".join("?" for _ in activo_keys_raw)
    cur = conn.execute(
        f"SELECT periodo, SUM(COALESCE(monto_uf, monto_clp)) AS noi FROM raw_er_activo_line "
        f"WHERE es_operacional=1 AND superseded_at IS NULL AND activo_key IN ({placeholders}) "
        f"GROUP BY periodo",
        activo_keys_raw,
    )
    for r in cur.fetchall():
        acc[r["periodo"]] = acc.get(r["periodo"], 0.0) + r["noi"]
    return dict(sorted(acc.items()))


def _noi_mes_tri(series: dict[str, dict[str, float]], participaciones: dict[str, float]) -> dict[str, float]:
    """Suma ponderada, solo para periodos en que TODOS los componentes tienen
    dato (evita sumas parciales engañosas si los cortes de cada activo se
    desalinean)."""
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
            series[key] = _noi_activo_raw(conn, raw_keys)
            part = participaciones[_COMPONENTES_PART[key]]
            v = series[key]
            print(f"  {key} (part. {part}): {len(v)} periodos ({min(v) if v else '-'} a {max(v) if v else '-'})")

        # Persistir noi_mensual por activo (100%), reemplazando cualquier
        # versión anterior (incluye la basada en CDG — ver [[feedback_no_usar_cdg]]).
        for key, serie in series.items():
            conn.execute(
                "DELETE FROM derived_kpi WHERE entidad_tipo='activo' AND entidad_key=? AND kpi='noi_mensual'",
                (key,),
            )
            for periodo, valor in serie.items():
                conn.execute(
                    "INSERT INTO derived_kpi (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula) "
                    "VALUES ('activo',?,?,'noi_mensual',?,'UF',?)",
                    (key, periodo, valor, _NOI_MENSUAL_FORMULA),
                )

        noi_mes = _noi_mes_tri(series, participaciones)
        noi_u12m = _u12m(noi_mes)

        conn.execute(
            "DELETE FROM derived_kpi WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND kpi='noi_mes'"
        )
        conn.execute(
            "DELETE FROM derived_kpi WHERE entidad_tipo='fondo' AND entidad_key='TRI' AND kpi='noi_u12m'"
        )
        for periodo, valor in noi_mes.items():
            conn.execute(
                "INSERT INTO derived_kpi (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula) "
                "VALUES ('fondo','TRI',?,'noi_mes',?,'UF',?)",
                (periodo, valor, _NOI_MES_FORMULA),
            )
        for periodo, valor in noi_u12m.items():
            conn.execute(
                "INSERT INTO derived_kpi (entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula) "
                "VALUES ('fondo','TRI',?,'noi_u12m',?,'UF',?)",
                (periodo, valor, _NOI_U12M_FORMULA),
            )
        conn.commit()

        print(f"\nnoi_mes TRI: {len(noi_mes)} periodos ({min(noi_mes)} a {max(noi_mes)})")
        print(f"noi_u12m TRI: {len(noi_u12m)} periodos ({min(noi_u12m)} a {max(noi_u12m)})")
        ult = max(noi_mes)
        print(f"\nÚltimo mes ({ult}): noi_mes = {noi_mes[ult]:,.1f} UF")
        if ult in noi_u12m:
            print(f"U12M a {ult}: {noi_u12m[ult]:,.1f} UF")


if __name__ == "__main__":
    main()
