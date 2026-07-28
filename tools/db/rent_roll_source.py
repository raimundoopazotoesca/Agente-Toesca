"""Fuente única para dashboards/gráficos de rent roll, agnóstica de origen.

Problema que resuelve: no hay rent roll JLL verificado en DB todavía, solo un
archivo "borrador" con errores conocidos (no se puede ingestar vía
ingest_rent_roll_validated hasta que el proveedor lo corrija). Los dashboards
necesitan poder mostrar vacancia/superficie/arriendo/tenants/vencimientos YA,
sin esperar, y sin contaminar raw_rent_roll_line con datos no confiables.

Solución: get_rent_roll_rows() devuelve siempre una lista de dicts con la
misma forma que una fila de raw_rent_roll_line (activo_key, periodo, unidad,
arrendatario, m2, renta_uf, vencimiento, extra_json, fuente). Prioridad:

1. Si (activo_key, periodo) ya existe en DB (vigente) -> se usa DB. Fuente
   verificada, ingestada por el pipeline normal.
2. Si no existe en DB y se registró un borrador en work/rentroll_borrador/
   para ese (activo_key, periodo) -> se parsea el Excel directo (sin tocar
   la DB) y se marca extra_json.fuente = "excel_borrador".
3. Si no hay ninguna de las dos -> lista vacía.

Cuando se ingeste el rent roll bueno (tools/db/ingest_rent_roll_validated.py),
el caso (1) empieza a aplicar automáticamente para ese período — no hay que
tocar los dashboards ni borrar el borrador (aunque conviene borrarlo para no
confundir a futuro).

El Excel borrador se guarda en WORK_DIR, nunca en memory/ — así no se
puede confundir con datos de producción ni un `git status` lo muestra como
cambio a la DB.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"
BORRADOR_DIR = Path(os.environ.get("WORK_DIR", str(ROOT / "work"))) / "rentroll_borrador"

from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import repo_rent_roll  # noqa: E402
from tools.rentroll_tools import (  # noqa: E402
    _read_source_data,
    _RR_ACTIVO_KEY,
    _rr_num,
    _rr_date_str,
)


def registrar_borrador(activo_key: str, periodo: str, excel_path: str) -> Path:
    """Copia un rent roll no verificado a BORRADOR_DIR para que
    get_rent_roll_rows() lo use como fallback mientras no exista ese
    (activo_key, periodo) en DB. No valida ni toca raw_rent_roll_line."""
    import shutil

    BORRADOR_DIR.mkdir(parents=True, exist_ok=True)
    dest = BORRADOR_DIR / f"{activo_key}_{periodo}.xlsx"
    shutil.copy2(excel_path, dest)
    return dest


def _rows_from_db(activo_key: str, periodo: str) -> list[dict]:
    conn = get_conn_for(str(DB_PATH))
    try:
        rows = repo_rent_roll.list_by_periodo(conn, activo_key, periodo)
        return [dict(r) | {"fuente": "db"} for r in rows]
    finally:
        conn.close()


def _rows_from_borrador(activo_key: str, periodo: str, excel_path: str) -> list[dict]:
    source_data = _read_source_data(excel_path)
    rows = []
    for i, ((activo2, detalle), rec) in enumerate(source_data.items()):
        activo1 = str(rec.get("Activo1") or "").strip()
        if _RR_ACTIVO_KEY.get(activo1) != activo_key:
            continue
        extra = {
            "activo1": activo1,
            "activo2": activo2,
            "tipo_activo_3": rec.get("Tipo Activo 3"),
            "tipo_activo_2": rec.get("Tipo Activo 2 (no va vacante)"),
            "tipo_arrendatario": rec.get("Tipo Arrendatario"),
        }
        rows.append({
            "activo_key": activo_key,
            "periodo": periodo,
            "unidad": detalle,
            "arrendatario": (str(rec.get("Arrendatario")).strip()
                             if rec.get("Arrendatario") is not None else None),
            "m2": _rr_num(rec.get("Area Arrendable (m2)")),
            "renta_uf": _rr_num(rec.get("Renta Fija (UF/m2 /mes)")),
            "vencimiento": _rr_date_str(rec.get("Término del Contrato")),
            "extra_json": json.dumps(extra, ensure_ascii=False, default=str),
            "fuente": "excel_borrador",
        })
    return rows


def get_rent_roll_rows(activo_key: str, periodo: str) -> list[dict]:
    """Fuente única para dashboards. DB si existe el período; si no, borrador
    Excel en BORRADOR_DIR si fue registrado; si no, []."""
    rows = _rows_from_db(activo_key, periodo)
    if rows:
        return rows

    borrador = BORRADOR_DIR / f"{activo_key}_{periodo}.xlsx"
    if borrador.exists():
        return _rows_from_borrador(activo_key, periodo, str(borrador))

    return []


def is_borrador(rows: list[dict]) -> bool:
    """True si las filas vienen del Excel no verificado (mostrar advertencia en UI)."""
    return bool(rows) and rows[0].get("fuente") == "excel_borrador"


def periodos_disponibles(activo_key: str) -> list[str]:
    """Períodos con datos para este activo, sea en DB o en borrador."""
    conn = get_conn_for(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT DISTINCT periodo FROM raw_rent_roll_line "
            "WHERE activo_key=? AND superseded_at IS NULL ORDER BY periodo",
            (activo_key,),
        ).fetchall()
        periodos = {r[0] for r in rows}
    finally:
        conn.close()

    if BORRADOR_DIR.exists():
        prefix = f"{activo_key}_"
        for f in BORRADOR_DIR.glob(f"{prefix}*.xlsx"):
            periodos.add(f.stem[len(prefix):])

    return sorted(periodos)
