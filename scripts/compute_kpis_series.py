"""Compute and persist financial KPIs for all fund series.

Usage:
  python scripts/compute_kpis_series.py --kpi dy --modo backfill
  python scripts/compute_kpis_series.py --kpi dy
  python scripts/compute_kpis_series.py --kpi dy --desde 2024-01 --hasta 2026-03
"""
import argparse
import calendar
import sqlite3
import sys
from datetime import date
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.db.connection import get_conn
from tools.db import repo_kpi

RECIPE = "dy_v1"
UNIT = "ratio"  # 0.0413 = 4.13%

SERIES_CONFIG = {
    # entidad_key → config; "nemo_db" overrides the nemotecnico used for DB lookups
    # when the DB stores a different identifier than the canonical series key.
    "CFITOERI1A": {"fondo": "TRI", "inicio": "2018-03", "bursatil": True},
    "CFITOERI1C": {"fondo": "TRI", "inicio": "2018-03", "bursatil": True},
    "CFITOERI1I": {"fondo": "TRI", "inicio": "2018-03", "bursatil": True},
    "CFITRIPT-E": {"fondo": "PT",  "inicio": "2018-03", "bursatil": True},
    "APO-UNICA":  {"fondo": "Apo", "inicio": "2019-03", "bursatil": False, "nemo_db": "Apo"},
}


def _last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _subtract_12m(t: date) -> date:
    """Mismo día, un año antes. Clamps al último día del mes si hace falta."""
    y = t.year - 1
    max_d = calendar.monthrange(y, t.month)[1]
    return date(y, t.month, min(t.day, max_d))


def _months_range(desde: str, hasta: str):
    """Yield (periodo 'YYYY-MM', last_day date) for each month in [desde, hasta]."""
    y, m = map(int, desde.split("-"))
    hy, hm = map(int, hasta.split("-"))
    while (y, m) <= (hy, hm):
        yield f"{y:04d}-{m:02d}", _last_day(y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _prev_month() -> str:
    """Último mes completo: ayer-ish."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def _get_divs_clp(conn: sqlite3.Connection, nemo: str, desde: date, hasta: date) -> float:
    """Suma monto_clp_cuota de dividendos en (desde, hasta]. 0.0 si no hay.

    Uses GROUP BY to deduplicate rows with identical (nemotecnico, fecha_pago,
    monto_clp_cuota) that may arise from multiple ingestion runs.
    """
    cur = conn.execute(
        """SELECT COALESCE(SUM(monto_dedup), 0.0)
             FROM (
               SELECT MAX(monto_clp_cuota) AS monto_dedup
                 FROM raw_dividendo_line
                WHERE superseded_at IS NULL
                  AND tipo = 'dividendo'
                  AND nemotecnico = ?
                  AND fecha_pago > ? AND fecha_pago <= ?
                  AND monto_clp_cuota IS NOT NULL
                GROUP BY nemotecnico, fecha_pago, monto_clp_cuota
             )""",
        (nemo, desde.isoformat(), hasta.isoformat()),
    )
    return cur.fetchone()[0]


def _get_precio_contable_clp(conn: sqlite3.Connection, nemo: str, t: date) -> float | None:
    """Último precio contable en CLP con fecha <= t."""
    cur = conn.execute(
        """SELECT precio_clp FROM raw_valor_cuota_line
            WHERE nemotecnico = ? AND tipo = 'contable' AND fecha <= ?
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, t.isoformat()),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _get_precio_bursatil_clp(conn: sqlite3.Connection, nemo: str, t: date) -> float | None:
    """Precio bursátil en CLP con fecha <= t.
    Fuente primaria: raw_precio_cuota_line (LarrainVial).
    Fallback: raw_valor_cuota_line tipo='bursatil'.
    """
    cur = conn.execute(
        """SELECT precio_clp FROM raw_precio_cuota_line
            WHERE nemotecnico = ? AND fecha <= ?
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, t.isoformat()),
    )
    row = cur.fetchone()
    if row and row[0]:
        return row[0]
    # Fallback
    cur = conn.execute(
        """SELECT precio_clp FROM raw_valor_cuota_line
            WHERE nemotecnico = ? AND tipo = 'bursatil' AND fecha <= ?
            ORDER BY fecha DESC LIMIT 1""",
        (nemo, t.isoformat()),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _compute_dy(conn: sqlite3.Connection, nemo: str, t: date, variante: str) -> float | None:
    """DY = sum_divs_clp(t-12m, t] / precio_clp(t). None si falta precio."""
    t_12m = _subtract_12m(t)
    divs = _get_divs_clp(conn, nemo, t_12m, t)
    if variante == "contable":
        precio = _get_precio_contable_clp(conn, nemo, t)
    else:
        precio = _get_precio_bursatil_clp(conn, nemo, t)
    if precio is None or precio == 0:
        return None
    return divs / precio


def run_dy(conn: sqlite3.Connection, desde: str, hasta: str) -> None:
    total = 0
    skipped = 0
    for nemo, cfg in SERIES_CONFIG.items():
        inicio = cfg["inicio"]
        # nemo_db overrides the identifier used for DB lookups (e.g. 'Apo' vs 'APO-UNICA')
        nemo_db = cfg.get("nemo_db", nemo)
        # No calcular antes del inicio del fondo
        desde_efectivo = max(desde, inicio)
        if desde_efectivo > hasta:
            continue
        for periodo, t in _months_range(desde_efectivo, hasta):
            for variante in (["contable", "bursatil"] if cfg["bursatil"] else ["contable"]):
                dy = _compute_dy(conn, nemo_db, t, variante)
                if dy is None:
                    skipped += 1
                    continue
                repo_kpi.upsert(
                    conn,
                    entidad_tipo="serie",
                    entidad_key=nemo,
                    periodo=periodo,
                    kpi="dy",
                    valor=dy,
                    unidad=UNIT,
                    recipe=RECIPE,
                    variante=variante,
                )
                total += 1
    print(f"Persistidos: {total} | Sin precio (skip): {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute KPIs for fund series.")
    parser.add_argument("--kpi", required=True, choices=["dy"], help="KPI a calcular")
    parser.add_argument("--modo", choices=["backfill", "incremental"], default="incremental")
    parser.add_argument("--desde", help="Mes inicio YYYY-MM (override)")
    parser.add_argument("--hasta", help="Mes fin YYYY-MM (override, default=último mes completo)")
    args = parser.parse_args()

    hasta = args.hasta or _prev_month()

    if args.desde:
        desde = args.desde
    elif args.modo == "backfill":
        desde = "2017-01"  # anterior al inicio más antiguo → se filtra por serie
    else:
        desde = hasta  # incremental: solo mes actual

    print(f"KPI={args.kpi}  modo={args.modo}  desde={desde}  hasta={hasta}")
    conn = get_conn()
    try:
        if args.kpi == "dy":
            run_dy(conn, desde, hasta)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
