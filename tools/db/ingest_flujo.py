"""
Persistencia de flujos de activo (INMOSA y similares) en raw_flujo_line.

Función pública: persist_flujo_lines(activo_key, src_path, src_sheet, periodo, data, tool, hash_extra="")

Dual-write best-effort a la DB. Si la DB falla, el flujo de Excel sigue sin error.
"""

import hashlib
import os
from sqlite3 import Connection

from tools.db.connection import get_conn as _db_get_conn
from tools.db import repo_audit, repo_flujo


def _file_hash(path: str) -> str:
    """Calcula SHA256 del archivo."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def persist_flujo_lines(
    activo_key: str,
    src_path: str,
    src_sheet: str,
    periodo: str,
    data: dict,
    tool: str,
    hash_extra: str = "",
) -> int:
    """Dual-write best-effort de líneas de flujo (label→monto CLP) a raw_flujo_line.

    Args:
        activo_key: Clave del activo (ej. "INMOSA", "Viña Centro")
        src_path: Ruta al archivo fuente (xlsx)
        src_sheet: Nombre de la hoja en el archivo fuente
        periodo: Período en formato "YYYY-MM" (ej. "2026-03")
        data: Dict {label: monto_clp}
        tool: Nombre de la herramienta que invoca (ej. "actualizar_noi_immosa")
        hash_extra: Sufijo para el file_hash. Necesario cuando un mismo archivo
                    contiene varios períodos (ej. backfill INMOSA), para que
                    (file_hash, source_row) no colisione entre períodos.

    Returns:
        Cantidad de filas insertadas. Nunca propaga errores: si la DB falla,
        retorna 0 sin detener el flujo de Excel.
    """
    if not data:
        return 0
    try:
        fh = _file_hash(src_path)
        if hash_extra:
            fh = f"{fh}:{hash_extra}"
        conn = _db_get_conn()
        try:
            run_id = repo_audit.start_ingest_run(
                conn, tool=tool, source_file=os.path.basename(src_path), file_hash=fh
            )
            lines = [
                {
                    "activo_key": activo_key,
                    "periodo": periodo,
                    "cuenta_codigo": None,
                    "cuenta_nombre": label,
                    "monto_clp": monto,
                    "monto_uf": None,
                    "source_file": os.path.basename(src_path),
                    "source_sheet": src_sheet,
                    "source_row": i,
                    "file_hash": fh,
                }
                for i, (label, monto) in enumerate(data.items())
            ]
            n = repo_flujo.insert_lines(conn, lines, run_id)
            repo_audit.finish_ingest_run(
                conn, run_id, rows_in=len(lines), rows_loaded=n, status="ok"
            )
            return n
        finally:
            conn.close()
    except Exception as e:
        print(f"[ingest_flujo] no se pudo persistir flujo {activo_key} en DB: {e}")
        return 0
