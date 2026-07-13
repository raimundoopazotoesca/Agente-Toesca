"""Refresh mensual de datos de mercado: UF diaria + precios bursátiles + KPIs.

Uso:
  python scripts/refresh_market_data.py                   # mes anterior + año actual
  python scripts/refresh_market_data.py --year 2026 --month 6
"""
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from tools.db.connection import get_conn
from tools import uf_tools, web_bursatil_tools


def refresh_uf(current_year: int) -> None:
    """Asegura UF del año actual (para captar valores nuevos)."""
    print(f"[1/3] Refrescando UF {current_year}...")
    conn = get_conn()
    try:
        uf_tools.ensure_years(conn, [current_year])
    finally:
        conn.close()
    # Re-derivar uf_dia y precio_uf en tablas de cuota
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backfill_uf.py"), "--refresh-cuotas"],
        check=True,
    )


def refresh_bursatil(year: int, month: int) -> None:
    print(f"[2/3] Bajando precios bursátiles {year}-{month:02d}...")
    print(web_bursatil_tools.obtener_precios_mes(year, month))


def refresh_kpis() -> None:
    print("[3/3] Recomputando KPIs (DY)...")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "compute_kpis_series.py"),
         "--kpi", "dy", "--modo", "backfill"],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    today = date.today()
    ap.add_argument("--year", type=int, default=today.year)
    ap.add_argument("--month", type=int,
                    default=(today.month - 1) if today.month > 1 else 12)
    args = ap.parse_args()

    refresh_uf(args.year)
    refresh_bursatil(args.year, args.month)
    refresh_kpis()
    print("\nOK — datos de mercado refrescados.")


if __name__ == "__main__":
    main()
