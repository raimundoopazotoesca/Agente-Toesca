"""Corrección manual: Sobretasa Sucden fija en 140 UF desde 2026-01.

La planilla fuente (RAW/NOI Sucden.xlsx) trae la Sobretasa recalculada
mes a mes en base a una fórmula UF que ya no aplica desde enero 2026 —
el usuario confirmó que a partir de ese período el monto es fijo:
-140 UF (gasto). Esto NO viene del archivo fuente, es un override de
regla de negocio, documentado en wiki/log.md.

Supersede solo las filas SUCDEN_SOBRETASA con periodo >= 2026-01 e
inserta las corregidas bajo un ingest_run propio (tool='correction_er_
sucden_sobretasa'), preservando trazabilidad. Idempotente: si ya existen
filas activas con file_hash='correction:sucden_sobretasa_2026' para todos
los periodos objetivo, no hace nada.
"""
from __future__ import annotations

import sqlite3

_ACTIVO_KEY = "Sucden"
_CUENTA_CODIGO = "SUCDEN_SOBRETASA"
_CUENTA_NOMBRE = "(-) Sobretasa"
_MONTO_FIJO = -140.0
_DESDE_PERIODO = "2026-01"
_FILE_HASH = "correction:sucden_sobretasa_2026"


def periodos_a_corregir(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT periodo FROM raw_er_activo_line
            WHERE activo_key = ? AND cuenta_codigo = ?
              AND periodo >= ? AND superseded_at IS NULL""",
        (_ACTIVO_KEY, _CUENTA_CODIGO, _DESDE_PERIODO),
    ).fetchall()
    return sorted(r[0] for r in rows)


def apply(conn: "sqlite3.Connection | None" = None) -> dict:
    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        ya_corregidas = conn.execute(
            """SELECT 1 FROM raw_er_activo_line
                WHERE file_hash = ? AND superseded_at IS NULL LIMIT 1""",
            (_FILE_HASH,),
        ).fetchone()
        if ya_corregidas is not None:
            return {"status": "skipped_idempotent", "rows": 0, "ingest_run_id": None}

        periodos = periodos_a_corregir(conn)
        if not periodos:
            return {"status": "nothing_to_correct", "rows": 0, "ingest_run_id": None}

        old_rows = conn.execute(
            """SELECT id FROM raw_er_activo_line
                WHERE activo_key = ? AND cuenta_codigo = ?
                  AND periodo >= ? AND superseded_at IS NULL""",
            (_ACTIVO_KEY, _CUENTA_CODIGO, _DESDE_PERIODO),
        ).fetchall()
        conn.execute(
            """UPDATE raw_er_activo_line SET superseded_at = datetime('now')
                WHERE id IN ({})""".format(",".join("?" * len(old_rows))),
            [r[0] for r in old_rows],
        )

        run_id = repo_audit.start_ingest_run(
            conn, tool="correction_er_sucden_sobretasa",
            source_file="manual:user-instruction-2026-07-14", file_hash=_FILE_HASH,
        )

        lines = [{
            "activo_key": _ACTIVO_KEY,
            "periodo": p,
            "cuenta_codigo": _CUENTA_CODIGO,
            "cuenta_nombre": _CUENTA_NOMBRE,
            "monto_clp": _MONTO_FIJO,
            "monto_uf": None,
            "seccion": "GASTOS_OPERACION",
            "es_operacional": 1,
            "source_file": "manual:user-instruction-2026-07-14",
            "source_sheet": None,
            "source_row": None,
            "file_hash": _FILE_HASH,
        } for p in periodos]

        inserted = repo_er_activo.insert_lines(conn, lines, run_id)
        repo_audit.finish_ingest_run(
            conn, run_id, rows_in=len(lines), rows_loaded=inserted, status="ok",
        )

        return {"status": "corrected", "rows": inserted,
                "periodos": periodos, "ingest_run_id": run_id}
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    print(apply())
