"""Consolida tasa arriendo ajustada bursátil y cap rate implícito bursátil — Fondo PT.

Réplica de la metodología ya validada para Apo (contable, ver wiki/kpis_noi_cap_rate_apo.md),
pero reemplazando patrimonio_libro por market_cap bursátil (única serie PT no transa en bolsa
Apoquindo, por eso esa variante solo aplica a fondos bursátiles: PT y TRI).

    denom_uf = market_cap_uf + deuda_financiera_neta_uf + caja_minima_uf
             = market_cap_uf + deuda_uf - caja_consolidada_uf + caja_minima_uf
    tasa_arriendo_ajustada_bursatil = ingresos_u12m / denom_uf
    cap_rate_implicito_bursatil     = noi_u12m / denom_uf

Fuentes:
  - market_cap_uf: raw_valor_cuota_bursatil.patrimonio_bursatil_uf (= cuotas × precio_uf),
    último dato <= fin de mes, nemotecnico CFITRIPT-E.
  - deuda_financiera_neta: derived_kpi (ya existente, mensual, no recalculado aquí).
  - caja_minima: derived_kpi kpi='caja_minima' (trimestral, ESF.total_activo × 1%), forward-
    filled al mes (mismo criterio que Apo _mensual_v1: último valor <= mes).
  - ingresos_u12m / noi_u12m: derived_kpi fondo PT (ya consolidados, mensual).

Antes de calcular el KPI final, extiende la cobertura de caja_minima para PT (solo 10/34
trimestres estaban persistidos) leyendo ESF.total_activo desde raw_eeff_line con dedup de
filas duplicadas (corriente + no_corriente + total, a veces con 2 reportes distintos para el
mismo período — se elige la que arma un total consistente con el trimestre anterior).

Uso:
  python scripts/consolidate_kpis_bursatil_pt.py
"""
import calendar
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.db.connection import get_conn
from tools.db import repo_kpi

FONDO = "PT"
NEMO = "CFITRIPT-E"
CAJA_MINIMA_PCT = 0.01  # PT: 1% de activos totales (regla usuario 2026-07-09)

# Períodos con datos de origen inconsistentes (ver docstring / wiki) — se excluyen de
# caja_minima en vez de persistir un valor no confiable.
CAJA_MINIMA_EXCLUIR = {"2019-12"}  # Total activo salta 2x vs trimestres vecinos, luego revierte


def _last_day(periodo: str) -> date:
    y, m = map(int, periodo.split("-"))
    return date(y, m, calendar.monthrange(y, m)[1])


def _dedup_total_activo(conn: sqlite3.Connection, fondo: str) -> dict[str, float]:
    """ESF.total_activo por período, deduplicando filas corriente/no_corriente/total y
    reportes duplicados. Devuelve {periodo: monto_clp} para el total_activo real."""
    cur = conn.execute(
        """SELECT periodo, monto_clp FROM raw_eeff_line
            WHERE fondo_key=? AND superseded_at IS NULL
              AND (cuenta_codigo_canonical='TOTAL_ACTIVO'
                   OR LOWER(cuenta_nombre) LIKE '%total activo%')
            ORDER BY periodo""",
        (fondo,),
    )
    por_periodo: dict[str, set[float]] = defaultdict(set)
    for periodo, monto in cur.fetchall():
        por_periodo[periodo].add(monto)

    resultado: dict[str, float] = {}
    last_total: float | None = None
    for periodo in sorted(por_periodo):
        vals = sorted(por_periodo[periodo])
        n = len(vals)
        candidatos = sorted({
            vals[k]
            for i in range(n) for j in range(i + 1, n) for k in range(n)
            if k not in (i, j) and abs(vals[i] + vals[j] - vals[k]) < 1.0
        })
        if not candidatos:
            elegido = max(vals)
        elif len(candidatos) == 1:
            elegido = candidatos[0]
        else:
            # Reportes duplicados con distinto total: elegir el consistente con el
            # trimestre anterior (mismo criterio usado para validar Apo 2020-12, wiki §5.1).
            elegido = min(candidatos, key=lambda x: abs(x - last_total)) if last_total else max(candidatos)
        resultado[periodo] = elegido
        last_total = elegido
    return resultado


def _extender_caja_minima(conn: sqlite3.Connection, fondo: str, pct: float) -> None:
    existentes = {
        row["periodo"]
        for row in conn.execute(
            "SELECT periodo FROM derived_kpi WHERE kpi='caja_minima' AND entidad_tipo='fondo' AND entidad_key=?",
            (fondo,),
        )
    }
    total_activo = _dedup_total_activo(conn, fondo)

    faltantes = sorted(set(total_activo) - existentes - CAJA_MINIMA_EXCLUIR)
    for periodo in faltantes:
        caja_minima_clp = total_activo[periodo] * pct
        repo_kpi.upsert(
            conn, "fondo", fondo, periodo, "caja_minima",
            caja_minima_clp, "CLP", "caja_minima_v1",
        )
    print(f"caja_minima {fondo}: {len(faltantes)} períodos nuevos persistidos "
          f"(excluidos por datos inconsistentes: {sorted(CAJA_MINIMA_EXCLUIR)})")


def _uf(conn: sqlite3.Connection, fecha_iso: str) -> float | None:
    row = conn.execute(
        "SELECT valor FROM fact_uf WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (fecha_iso,),
    ).fetchone()
    return row["valor"] if row else None


def _caja_minima_uf_por_trimestre(conn: sqlite3.Connection, fondo: str) -> dict[str, float]:
    """caja_minima en UF, usando la UF del propio trimestre en que se calculó."""
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
    """Propaga el último valor trimestral disponible <= mes (mismo criterio que Apo _mensual_v1)."""
    trimestres_ordenados = sorted(valores_trimestrales)
    out = {}
    idx = -1
    for mes in meses:
        while idx + 1 < len(trimestres_ordenados) and trimestres_ordenados[idx + 1] <= mes:
            idx += 1
        if idx >= 0:
            out[mes] = valores_trimestrales[trimestres_ordenados[idx]]
    return out


def _market_cap_uf(conn: sqlite3.Connection, nemo: str, mes: str) -> float | None:
    fin_mes = _last_day(mes).isoformat()
    inicio_mes = f"{mes}-01"
    row = conn.execute(
        """SELECT patrimonio_bursatil_uf FROM raw_valor_cuota_bursatil
            WHERE nemotecnico=? AND fecha>=? AND fecha<=? AND patrimonio_bursatil_uf IS NOT NULL
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, inicio_mes, fin_mes),
    ).fetchone()
    return row["patrimonio_bursatil_uf"] if row else None


def _serie_derived(conn: sqlite3.Connection, entidad_tipo: str, entidad_key: str, kpi: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT periodo, valor FROM derived_kpi WHERE kpi=? AND entidad_tipo=? AND entidad_key=?",
        (kpi, entidad_tipo, entidad_key),
    ).fetchall()
    return {row["periodo"]: row["valor"] for row in rows}


def main():
    conn = get_conn()

    _extender_caja_minima(conn, FONDO, CAJA_MINIMA_PCT)

    caja_minima_uf_trim = _caja_minima_uf_por_trimestre(conn, FONDO)
    dfn_uf_mensual = _serie_derived(conn, "fondo", FONDO, "deuda_financiera_neta")
    ingresos_u12m = _serie_derived(conn, "fondo", FONDO, "ingresos_u12m")
    noi_u12m = _serie_derived(conn, "fondo", FONDO, "noi_u12m")

    meses = sorted(ingresos_u12m)  # ingresos_u12m es el más restrictivo (parte 2018-12)
    caja_minima_uf_mensual = _ffill_mensual(caja_minima_uf_trim, meses)

    n_persistidos = 0
    for mes in meses:
        market_cap = _market_cap_uf(conn, NEMO, mes)
        dfn = dfn_uf_mensual.get(mes)
        caja_min = caja_minima_uf_mensual.get(mes)
        ing = ingresos_u12m.get(mes)
        noi = noi_u12m.get(mes)

        if None in (market_cap, dfn, caja_min, ing, noi):
            continue

        denom_uf = market_cap + dfn + caja_min
        if denom_uf <= 0:
            continue

        tasa_arriendo = ing / denom_uf
        cap_rate = noi / denom_uf

        repo_kpi.upsert(
            conn, "fondo", FONDO, mes, "tasa_arriendo_ajustada_bursatil",
            tasa_arriendo, "ratio", "tasa_arriendo_ajustada_bursatil_mensual_v1",
        )
        repo_kpi.upsert(
            conn, "fondo", FONDO, mes, "cap_rate_implicito_bursatil",
            cap_rate, "ratio", "cap_rate_implicito_bursatil_mensual_v1",
        )
        n_persistidos += 1

    print(f"tasa_arriendo_ajustada_bursatil / cap_rate_implicito_bursatil {FONDO}: "
          f"{n_persistidos} meses persistidos ({meses[0] if meses else '-'} a {meses[-1] if meses else '-'})")

    conn.close()


if __name__ == "__main__":
    main()
