"""
Limpieza de duplicados en raw_valor_cuota_contable y raw_cuota_en_circulacion.

Los mismos períodos aparecen en múltiples PDFs (el actual + comparativo del siguiente).
Se mantiene la primera fila insertada (min id) por (nemotecnico, fecha, tipo/—) y
se marcan las demás como superseded.
"""
from __future__ import annotations
from pathlib import Path


DB_PATH = str(Path(__file__).resolve().parents[2] / "memory" / "agente_toesca_v2.db")


def dedup_valor_cuota(db_path: str = DB_PATH) -> dict:
    """
    Para cada (nemotecnico, fecha, tipo) con múltiples filas vigentes desde PDFs:
    - Conserva la de menor id (primera insertada desde EEFF)
    - Supersede las demás
    """
    from tools.db.connection import get_conn_for
    conn = get_conn_for(db_path)

    # IDs a superseder: no el mínimo por grupo, y que no sea cdg_extract.xlsx
    conn.execute("""
        UPDATE raw_valor_cuota_contable
        SET superseded_at = CURRENT_TIMESTAMP
        WHERE superseded_at IS NULL
          AND source_file != 'cdg_extract.xlsx'
          AND id NOT IN (
              SELECT MIN(id)
              FROM raw_valor_cuota_contable
              WHERE superseded_at IS NULL
                AND source_file != 'cdg_extract.xlsx'
              GROUP BY nemotecnico, fecha
          )
    """)
    n_vc = conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    conn.close()
    return {"valor_cuota_superseded": n_vc}


def dedup_cuotas_circulacion(db_path: str = DB_PATH) -> dict:
    """
    Para cada (nemotecnico, fecha) con múltiples filas vigentes desde PDFs:
    - Conserva la de menor id (primera insertada desde EEFF)
    - Supersede las demás
    """
    from tools.db.connection import get_conn_for
    conn = get_conn_for(db_path)

    conn.execute("""
        UPDATE raw_cuota_en_circulacion
        SET superseded_at = CURRENT_TIMESTAMP
        WHERE superseded_at IS NULL
          AND source_file != 'cdg_extract.xlsx'
          AND id NOT IN (
              SELECT MIN(id)
              FROM raw_cuota_en_circulacion
              WHERE superseded_at IS NULL
                AND source_file != 'cdg_extract.xlsx'
              GROUP BY nemotecnico, fecha
          )
    """)
    n_c = conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    conn.close()
    return {"cuotas_superseded": n_c}


def run_all(db_path: str = DB_PATH) -> dict:
    r1 = dedup_valor_cuota(db_path)
    r2 = dedup_cuotas_circulacion(db_path)
    return {**r1, **r2}


if __name__ == "__main__":
    result = run_all()
    print(result)
