"""Consolida tasa arriendo ajustada bursátil y cap rate implícito bursátil — Fondo TRI, por serie.

Misma metodología que PT (ver consolidate_kpis_bursatil_pt.py), pero TRI tiene 3
series bursátiles (A, C, I) con market cap propio cada una, mientras que
ingresos_u12m, noi_u12m, deuda_financiera_neta y caja_minima son a nivel fondo
(las series comparten los mismos activos subyacentes, solo difieren en cuotas).

    market_cap_uf(serie) = cuotas_totales_fondo(mes) x precio_uf_bursatil(serie, mes)
    denom_uf(serie) = market_cap_uf(serie) + deuda_financiera_neta_uf(TRI) + caja_minima_uf(TRI)
    tasa_arriendo_ajustada_bursatil(serie) = ingresos_u12m(TRI) / denom_uf(serie)
    cap_rate_implicito_bursatil(serie)     = noi_u12m(TRI) / denom_uf(serie)

market_cap_uf usa las cuotas TOTALES del fondo (suma de las 3 series), no las
cuotas propias de la serie: valida "cuánto valdría el fondo completo si todas
las cuotas se transaran al precio de esa serie" — necesario porque NOI/deuda/
caja son a nivel fondo, no por serie. Validado 2026-07-20 contra planilla del
usuario (CDG TRI 31-03-2026): market_cap por serie (A/C/I) y denom coinciden
exacto solo con este método; usar patrimonio_bursatil_uf de la serie (cuotas
propias x precio propio) da resultados equivocados (suma a nivel fondo pero
no reproduce las columnas por serie).

Fuentes:
  - precio_uf / cuotas: raw_valor_cuota_bursatil, último dato <= fin de mes,
    por nemotecnico de cada serie (CFITOERI1A/C/I). cuotas_totales_fondo(mes)
    = suma de cuotas de las 3 series en ese mismo corte.
  - deuda_financiera_neta / caja_minima / ingresos_u12m / noi_u12m: derived_kpi
    fondo TRI, ya consolidados (no se recalculan aquí).

Uso:
  python scripts/consolidate_kpis_bursatil_tri.py
"""
import calendar
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.db.connection import get_conn
from tools.db import repo_kpi

FONDO = "TRI"
NEMOS = ["CFITOERI1A", "CFITOERI1C", "CFITOERI1I"]


def _last_day(periodo: str) -> date:
    y, m = map(int, periodo.split("-"))
    return date(y, m, calendar.monthrange(y, m)[1])


def _uf(conn, fecha_iso: str) -> float | None:
    row = conn.execute(
        "SELECT valor FROM fact_uf WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (fecha_iso,),
    ).fetchone()
    return row["valor"] if row else None


def _caja_minima_uf_por_trimestre(conn, fondo: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT periodo, valor FROM derived_kpi WHERE kpi='caja_minima' AND entidad_tipo='fondo' AND entidad_key=? ORDER BY periodo",
        (fondo,),
    ).fetchall()
    out = {}
    for row in rows:
        uf_dia = _uf(conn, _last_day(row["periodo"]).isoformat())
        if uf_dia:
            out[row["periodo"]] = row["valor"] / uf_dia
    return out


def _ffill_mensual(valores_trimestrales: dict[str, float], meses: list[str]) -> dict[str, float]:
    trimestres_ordenados = sorted(valores_trimestrales)
    out = {}
    idx = -1
    for mes in meses:
        while idx + 1 < len(trimestres_ordenados) and trimestres_ordenados[idx + 1] <= mes:
            idx += 1
        if idx >= 0:
            out[mes] = valores_trimestrales[trimestres_ordenados[idx]]
    return out


def _precio_cuotas(conn, nemo: str, mes: str) -> tuple[float, float] | None:
    fin_mes = _last_day(mes).isoformat()
    inicio_mes = f"{mes}-01"
    row = conn.execute(
        """SELECT precio_uf, cuotas FROM raw_valor_cuota_bursatil
            WHERE nemotecnico=? AND fecha>=? AND fecha<=? AND precio_uf IS NOT NULL AND cuotas IS NOT NULL
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, inicio_mes, fin_mes),
    ).fetchone()
    return (row["precio_uf"], row["cuotas"]) if row else None


def _serie_derived(conn, entidad_tipo: str, entidad_key: str, kpi: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT periodo, valor FROM derived_kpi WHERE kpi=? AND entidad_tipo=? AND entidad_key=?",
        (kpi, entidad_tipo, entidad_key),
    ).fetchall()
    return {row["periodo"]: row["valor"] for row in rows}


def main():
    conn = get_conn()

    caja_minima_uf_trim = _caja_minima_uf_por_trimestre(conn, FONDO)
    dfn_uf_mensual = _serie_derived(conn, "fondo", FONDO, "deuda_financiera_neta")
    ingresos_u12m = _serie_derived(conn, "fondo", FONDO, "ingresos_u12m")
    noi_u12m = _serie_derived(conn, "fondo", FONDO, "noi_u12m")

    meses = sorted(ingresos_u12m)
    caja_minima_uf_mensual = _ffill_mensual(caja_minima_uf_trim, meses)

    for nemo in NEMOS:
        n_persistidos = 0
        for mes in meses:
            precio_cuotas_serie = _precio_cuotas(conn, nemo, mes)
            precio_cuotas_otras = [_precio_cuotas(conn, n, mes) for n in NEMOS if n != nemo]
            dfn = dfn_uf_mensual.get(mes)
            caja_min = caja_minima_uf_mensual.get(mes)
            ing = ingresos_u12m.get(mes)
            noi = noi_u12m.get(mes)

            if precio_cuotas_serie is None or any(p is None for p in precio_cuotas_otras) or None in (dfn, caja_min, ing, noi):
                continue

            precio_uf_serie, _ = precio_cuotas_serie
            cuotas_totales_fondo = sum(c for _, c in precio_cuotas_otras) + precio_cuotas_serie[1]
            market_cap = cuotas_totales_fondo * precio_uf_serie

            denom_uf = market_cap + dfn + caja_min
            if denom_uf <= 0:
                continue

            tasa_arriendo = ing / denom_uf
            cap_rate = noi / denom_uf

            repo_kpi.upsert(
                conn, "serie", nemo, mes, "tasa_arriendo_ajustada_bursatil",
                tasa_arriendo, "ratio", "tasa_arriendo_ajustada_bursatil_mensual_v1",
            )
            repo_kpi.upsert(
                conn, "serie", nemo, mes, "cap_rate_implicito_bursatil",
                cap_rate, "ratio", "cap_rate_implicito_bursatil_mensual_v1",
            )
            n_persistidos += 1

        print(f"tasa_arriendo_ajustada_bursatil / cap_rate_implicito_bursatil {nemo}: "
              f"{n_persistidos} meses persistidos")

    conn.close()


if __name__ == "__main__":
    main()
