"""Backfill UF diaria desde CMF (si hay CMF_API_KEY) o SII (fallback).

Uso:
  python scripts/backfill_uf.py                          # todos los años faltantes
  python scripts/backfill_uf.py --desde 2017 --hasta 2026
  python scripts/backfill_uf.py --refresh-cuotas         # solo re-derivar precio_uf/uf_dia

Después del fetch, actualiza `uf_dia` y `precio_uf` en:
  - raw_valor_cuota_contable_line
  - raw_valor_cuota_bursatil_line
usando la UF del día correcta (no carry-forward).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from tools.db.connection import get_conn
from tools import uf_tools


def refresh_cuotas(conn) -> None:
    """Rellena uf_dia y precio_uf en tablas de cuota usando raw_uf_diaria.

    Convención: uf_dia = UF del último día calendario del mes de `fecha`
    (aunque el precio sea de un día bursátil anterior).
    """
    for tabla, filtro_extra in [
        ("raw_valor_cuota_contable", "AND superseded_at IS NULL"),
        ("raw_valor_cuota_bursatil", ""),
    ]:
        # uf_dia = UF del último día del mes al que pertenece la fecha
        conn.execute(
            f"""UPDATE {tabla}
                   SET uf_dia = (
                       SELECT valor FROM raw_uf_diaria
                        WHERE fecha <= date({tabla}.fecha, 'start of month',
                                            '+1 month', '-1 day')
                        ORDER BY fecha DESC LIMIT 1
                   )
                 WHERE precio_clp IS NOT NULL
                   {filtro_extra}"""
        )
        # precio_uf = precio_clp / uf_dia (recalcula todo el que tenga ambos)
        conn.execute(
            f"""UPDATE {tabla}
                   SET precio_uf = ROUND(precio_clp / uf_dia, 6)
                 WHERE precio_clp IS NOT NULL
                   AND uf_dia IS NOT NULL
                   AND uf_dia > 0
                   {filtro_extra}"""
        )
        n_uf = conn.execute(
            f"SELECT COUNT(*) FROM {tabla} WHERE uf_dia IS NOT NULL {filtro_extra}"
        ).fetchone()[0]
        n_precio_uf = conn.execute(
            f"SELECT COUNT(*) FROM {tabla} WHERE precio_uf IS NOT NULL {filtro_extra}"
        ).fetchone()[0]
        print(f"  {tabla}: uf_dia poblados = {n_uf} | precio_uf = {n_precio_uf}")
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, help="Año inicio (default: 2017)")
    ap.add_argument("--hasta", type=int, help="Año fin (default: año actual)")
    ap.add_argument("--refresh-cuotas", action="store_true",
                    help="Solo re-derivar uf_dia/precio_uf desde raw_uf_diaria")
    args = ap.parse_args()

    conn = get_conn()
    try:
        if not args.refresh_cuotas:
            desde = args.desde or 2017
            hasta = args.hasta or date.today().year
            years = list(range(desde, hasta + 1))
            print(f"Fetch UF años {desde}..{hasta}")
            uf_tools.ensure_years(conn, years)
        print("Refresh uf_dia/precio_uf en tablas de cuota:")
        refresh_cuotas(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
