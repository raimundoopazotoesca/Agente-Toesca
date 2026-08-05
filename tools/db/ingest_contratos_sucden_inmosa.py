"""Ingesta de contratos fijos de Sucden e INMOSA a raw_rent_roll_line.

Fuente: RAW/Contratos Sucden e INMOSA.xlsx (SharePoint) — a diferencia de los
rent rolls mensuales de JLL/Tres Asociados, este archivo no cambia mes a mes
(contratos de largo plazo, prácticamente fijos). Se ingesta una vez por
período TRI relevante para que el perfil de vencimiento de contratos del
fact sheet TRI pueda consolidar Oficinas (PT+Apo+Apo3001) + Comerciales
(Viña+Curicó) + Residencias (INMOSA) + Bodegas (Sucden) en un mismo período.

file_hash se deriva por período (sha256(hash_archivo + periodo)) porque
uq_rent_roll_vivo es UNIQUE(file_hash, source_row): sin esto, ingestar el
mismo archivo para dos períodos distintos chocaría en el segundo.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import openpyxl

from tools.db.connection import get_conn
from tools.db import repo_audit, repo_rent_roll

SRC_PATH = (
    r"C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos"
    r"\RAW\Contratos Sucden e INMOSA.xlsx"
)

# Detalle Activo (col "Activo2" para Sucden) -> activo_key real en dim_activo
_ACTIVO_KEY_MAP = {
    "Sucden": "Sucden",
    "Colombia": "Residencia Colombia",
    "Coventry": "Residencia Coventry",
    "Del Candil": "Residencia Candil",
    "Medina": "Residencia Arturo Medina",
    "Padre Errázuriz": "Residencia Padre Errázuriz",
}


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _date_str(v):
    if v is None:
        return None
    return v.date().isoformat() if hasattr(v, "date") else str(v)[:10]


def _read_rows(src_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(src_path, data_only=True)
    ws = wb["Hoja1"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {name: i for i, name in enumerate(header) if name is not None}

    out = []
    for row in rows[1:]:
        activo2 = row[idx["Activo2"]]
        detalle = row[idx["Detalle Activo"]] or activo2
        activo_key = _ACTIVO_KEY_MAP.get(str(detalle).strip())
        if activo_key is None:
            continue
        # m2 = Area Arrendable PONDERADA (por % participación del fondo en la
        # sociedad, ver dim_sociedad.participacion — Sucden 100%, INMOSA 43%
        # vía SeniorAssist), no el m2 completo del edificio. "Renta Fija
        # (UF/m2/mes)" ya es tasa = Renta Fija Ponderada / Area Ponderada
        # (el % participación se cancela en la razón), así que m2_ponderado *
        # tasa = Renta Fija Ponderada = lo que realmente le corresponde al
        # fondo. Usar el m2 completo aquí sobreestima INMOSA en 1/0.43 = 2.3x
        # (bug encontrado 2026-08-05 comparando contra fuente externa del
        # usuario: daba 7085 UF vs 3047 UF reales en el bucket 2036+).
        out.append({
            "activo_key": activo_key,
            "unidad": str(detalle).strip(),
            "arrendatario": row[idx["Arrendatario"]],
            "m2": row[idx["Area Arrendable Ponderada (m2)"]],
            "renta_uf": row[idx["Renta Fija (UF/m2 /mes)"]],
            "vencimiento": _date_str(row[idx["Término del Contrato"]]),
            "extra": {
                "activo1": row[idx["Activo1"]],
                "activo2": activo2,
                "m2_full": row[idx["Area Arrendable (m2)"]],
                "participacion_fondo": row[idx["Participación Fondo"]],
                "tipo_activo_2": row[idx["Tipo Activo 2 (no va vacante)"]],
                "tipo_activo_3": row[idx["Tipo Activo 3"]],
                "tipo_arrendatario": row[idx["Tipo Arrendatario"]],
                "fecha_inicio": _date_str(row[idx["Fecha Inicio"]]),
                "fuente": "contratos_sucden_inmosa",
            },
        })
    return out


def ingest_contratos_sucden_inmosa(periodo: str, src_path: str = SRC_PATH) -> int:
    """Inserta los contratos de Sucden e INMOSA en raw_rent_roll_line para el
    período dado. Idempotente: re-ingestar el mismo (archivo, período) no
    duplica filas."""
    rows = _read_rows(src_path)
    if not rows:
        return 0

    fh_archivo = _file_hash(src_path)
    fh_periodo = hashlib.sha256(f"{fh_archivo}:{periodo}".encode()).hexdigest()

    conn = get_conn()
    try:
        run_id = repo_audit.start_ingest_run(
            conn,
            tool="ingest_contratos_sucden_inmosa",
            source_file=os.path.basename(src_path),
            file_hash=fh_periodo,
        )
        lines = []
        for i, rec in enumerate(rows):
            lines.append({
                "activo_key": rec["activo_key"],
                "periodo": periodo,
                "unidad": rec["unidad"],
                "arrendatario": (str(rec["arrendatario"]).strip()
                                 if rec["arrendatario"] is not None else None),
                "m2": float(rec["m2"]) if rec["m2"] is not None else None,
                "renta_uf": float(rec["renta_uf"]) if rec["renta_uf"] is not None else None,
                "vencimiento": rec["vencimiento"],
                "extra_json": json.dumps(rec["extra"], ensure_ascii=False, default=str),
                "source_file": os.path.basename(src_path),
                "source_sheet": "Hoja1",
                "source_row": i,
                "file_hash": fh_periodo,
            })
        n = repo_rent_roll.insert_lines(conn, lines, run_id)
        repo_audit.finish_ingest_run(
            conn, run_id, rows_in=len(lines), rows_loaded=n, status="ok"
        )
        return n
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    periodos = sys.argv[1:] or ["2026-05", "2026-06"]
    for p in periodos:
        n = ingest_contratos_sucden_inmosa(p)
        print(f"{p}: {n} filas insertadas")
