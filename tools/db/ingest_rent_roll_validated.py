"""Valida y persiste un archivo Rent Roll JLL (.xlsx) a raw_rent_roll_line.

Reusa el parser y las 4 validaciones de tools/rentroll_tools.py y agrega:
  - gate duro: no se puede ingestar si el validador (VAL1-VAL4 o lectura)
    reporta cualquier error
  - diff de absorción vs el snapshot vigente del período anterior en DB
    (altas / bajas / renovaciones / movimientos / cambios de renta), con
    detección de casos raros a confirmar por el usuario (posible renombre de
    arrendatario, saltos grandes de m²/renta, movimientos con caída fuerte
    de renta, unidades que aparecen/desaparecen sin evento claro)
  - persistencia idempotente por file_hash = sha256(bytes del archivo)

No expone CLI; lo consume scripts/ingesta_server (Flask).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

from tools.rentroll_tools import (  # noqa: E402
    _cierre_mes,
    _validar_archivo,
    _read_source_data,
    _RR_ACTIVO_KEY,
    _rr_num,
    _rr_date_str,
    build_email_jll,
    MESES_ES,
)
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import repo_audit, repo_rent_roll  # noqa: E402

RENOMBRE_UMBRAL = 0.3          # levenshtein(a,b)/max(len) por debajo de esto -> "posible renombre"
DELTA_M2_WARN = 0.02            # 2% de variación de m2 totales por activo
DELTA_RENTA_WARN = 0.05         # 5% de variación de renta UF total por activo
CAIDA_RENTA_MOVIMIENTO = 0.8    # renta nueva < 80% de la anterior en un movimiento


# ── Utilidades de fecha/periodo ──────────────────────────────────────────────

def _periodo_anterior(periodo: str) -> str:
    y, m = periodo.split("-")
    y, m = int(y), int(m)
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def _cierre_from_periodo(periodo: str):
    y, m = periodo.split("-")
    return _cierre_mes(int(y), int(m))


# ── Similaridad de strings (para detectar renombres de arrendatario) ────────

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _nombre_similar(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b or a == b:
        return False
    dist = _levenshtein(a, b)
    return dist / max(len(a), len(b)) < RENOMBRE_UMBRAL


def _es_vacante(arrendatario) -> bool:
    return not arrendatario or "vacante" in str(arrendatario).lower()


def _monto_mensual_uf(rec: dict) -> float:
    """raw_rent_roll_line.renta_uf es una TASA (UF/m²/mes), no un monto total.
    El monto mensual de una unidad = tasa * m2."""
    m2 = rec.get("m2") or 0.0
    tasa = rec.get("renta_uf") or 0.0
    return m2 * tasa


# ── Snapshots (dict {(activo2, unidad): {...}}) ──────────────────────────────

def _snapshot_from_db(activo_key: str, periodo: str) -> dict:
    conn = get_conn_for(str(DB_PATH))
    try:
        rows = repo_rent_roll.list_by_periodo(conn, activo_key, periodo)
        out = {}
        for r in rows:
            try:
                extra = json.loads(r["extra_json"] or "{}")
            except (TypeError, ValueError):
                extra = {}
            key = (extra.get("activo2") or "", r["unidad"])
            out[key] = {
                "arrendatario": r["arrendatario"],
                "m2": r["m2"],
                "renta_uf": r["renta_uf"],
                "vencimiento": r["vencimiento"],
            }
        return out
    finally:
        conn.close()


def _snapshot_from_source(activo_key: str, source_data: dict) -> dict:
    out = {}
    for (activo2, detalle), rec in source_data.items():
        activo1 = str(rec.get("Activo1") or "").strip()
        if _RR_ACTIVO_KEY.get(activo1) != activo_key:
            continue
        arr = rec.get("Arrendatario")
        out[(activo2, detalle)] = {
            "arrendatario": str(arr).strip() if arr is not None else None,
            "m2": _rr_num(rec.get("Area Arrendable (m2)")),
            "renta_uf": _rr_num(rec.get("Renta Fija (UF/m2 /mes)")),
            "vencimiento": _rr_date_str(rec.get("Término del Contrato")),
        }
    return out


# ── Clasificación de eventos por unidad ──────────────────────────────────────

def _clasificar_evento(antes: dict | None, ahora: dict | None) -> dict:
    """Clasifica el cambio de una unidad (activo2, unidad) entre dos snapshots."""
    vac_antes = antes is None or _es_vacante(antes.get("arrendatario"))
    vac_ahora = ahora is None or _es_vacante(ahora.get("arrendatario"))

    if vac_antes and not vac_ahora:
        return {"evento": "alta"}
    if not vac_antes and vac_ahora:
        return {"evento": "baja"}
    if vac_antes and vac_ahora:
        return {"evento": "sin_cambio"}

    # Ambos ocupados
    arr_antes = (antes.get("arrendatario") or "").strip()
    arr_ahora = (ahora.get("arrendatario") or "").strip()

    if arr_antes == arr_ahora:
        venc_antes, venc_ahora = antes.get("vencimiento"), ahora.get("vencimiento")
        if venc_antes and venc_ahora and venc_ahora > venc_antes:
            return {"evento": "renovacion", "vencimiento_antes": venc_antes, "vencimiento_ahora": venc_ahora}
        if antes.get("renta_uf") != ahora.get("renta_uf"):
            return {
                "evento": "cambio_renta",
                "renta_antes": antes.get("renta_uf"),
                "renta_ahora": ahora.get("renta_uf"),
            }
        return {"evento": "sin_cambio"}

    # Distinto arrendatario en la misma unidad -> movimiento
    evento = {"evento": "movimiento", "arrendatario_antes": arr_antes, "arrendatario_ahora": arr_ahora}
    if _nombre_similar(arr_antes, arr_ahora):
        evento["posible_renombre"] = True
    renta_antes, renta_ahora = antes.get("renta_uf"), ahora.get("renta_uf")
    if renta_antes and renta_ahora and renta_ahora < renta_antes * CAIDA_RENTA_MOVIMIENTO:
        evento["caida_renta_fuerte"] = True
    return evento


def _totales_activo(snapshot: dict) -> dict:
    """Totales por activo. renta_uf_total/vacante son montos mensuales (UF/mes),
    calculados como tasa (UF/m²/mes) * m² por unidad — no una suma de tasas."""
    m2_total = 0.0
    m2_ocupado = 0.0
    m2_vacante = 0.0
    renta_total = 0.0
    renta_vacante = 0.0
    for rec in snapshot.values():
        m2 = rec.get("m2") or 0.0
        monto = _monto_mensual_uf(rec)
        m2_total += m2
        if _es_vacante(rec.get("arrendatario")):
            m2_vacante += m2
            renta_vacante += monto
        else:
            m2_ocupado += m2
            renta_total += monto
    pct_vacancia = (m2_vacante / m2_total * 100) if m2_total else None
    return {
        "m2_total": round(m2_total, 2),
        "m2_ocupado": round(m2_ocupado, 2),
        "m2_vacante": round(m2_vacante, 2),
        "pct_vacancia": round(pct_vacancia, 2) if pct_vacancia is not None else None,
        "renta_uf_total": round(renta_total, 2),
        "renta_uf_vacante": round(renta_vacante, 2),
    }


def diff_absorcion(activo_key: str, periodo: str, source_data: dict) -> dict:
    """Compara el snapshot nuevo (del archivo) vs el vigente en DB para
    (activo_key, periodo_anterior). Devuelve eventos + totales + casos raros.
    """
    periodo_prev = _periodo_anterior(periodo)
    snap_prev = _snapshot_from_db(activo_key, periodo_prev)
    snap_nuevo = _snapshot_from_source(activo_key, source_data)

    todas_keys = set(snap_prev.keys()) | set(snap_nuevo.keys())
    eventos = {"alta": [], "baja": [], "renovacion": [], "movimiento": [], "cambio_renta": []}
    casos_raros = []

    for key in sorted(todas_keys):
        antes = snap_prev.get(key)
        ahora = snap_nuevo.get(key)
        clasif = _clasificar_evento(antes, ahora)
        ev = clasif["evento"]
        if ev == "sin_cambio":
            continue
        activo2, unidad = key
        item = {"activo2": activo2, "unidad": unidad, **clasif}
        if ev in eventos:
            eventos[ev].append(item)

        if clasif.get("posible_renombre"):
            casos_raros.append({
                "tipo": "posible_renombre",
                "activo2": activo2,
                "unidad": unidad,
                "detalle": f"'{clasif['arrendatario_antes']}' -> '{clasif['arrendatario_ahora']}' "
                           "podría ser el mismo arrendatario (nombre similar). Si es así, no es "
                           "un movimiento real de absorción.",
            })
        if clasif.get("caida_renta_fuerte"):
            casos_raros.append({
                "tipo": "caida_renta_fuerte",
                "activo2": activo2,
                "unidad": unidad,
                "detalle": f"Renta bajó de {clasif.get('renta_antes')} a {clasif.get('renta_ahora')} "
                           "UF/m² en el movimiento — verificar que no sea un error de tipeo.",
            })

    unidades_desaparecidas = [
        k for k in snap_prev.keys() - snap_nuevo.keys()
        if not _es_vacante(snap_prev[k].get("arrendatario"))
    ]
    for (activo2, unidad) in unidades_desaparecidas:
        casos_raros.append({
            "tipo": "unidad_desaparecio_del_archivo",
            "activo2": activo2,
            "unidad": unidad,
            "detalle": "Esta unidad estaba ocupada el mes anterior y la fila ya no existe en el "
                       "archivo nuevo (se contabilizó como baja; verificar que no sea fusión, "
                       "subdivisión o cambio de nomenclatura de la unidad).",
        })

    m2_antes = sum((r.get("m2") or 0.0) for r in snap_prev.values())
    m2_ahora = sum((r.get("m2") or 0.0) for r in snap_nuevo.values())
    renta_antes = sum(_monto_mensual_uf(r) for r in snap_prev.values())
    renta_ahora = sum(_monto_mensual_uf(r) for r in snap_nuevo.values())
    if m2_antes and abs(m2_ahora - m2_antes) / m2_antes > DELTA_M2_WARN:
        casos_raros.append({
            "tipo": "delta_m2_total_activo",
            "activo2": None,
            "unidad": None,
            "detalle": f"m² arrendables totales de {activo_key} cambiaron de {m2_antes:.1f} a "
                       f"{m2_ahora:.1f} ({(m2_ahora / m2_antes - 1) * 100:+.1f}%).",
        })
    if renta_antes and abs(renta_ahora - renta_antes) / renta_antes > DELTA_RENTA_WARN:
        casos_raros.append({
            "tipo": "delta_renta_total_activo",
            "activo2": None,
            "unidad": None,
            "detalle": f"Renta UF total de {activo_key} cambió de {renta_antes:.1f} a "
                       f"{renta_ahora:.1f} ({(renta_ahora / renta_antes - 1) * 100:+.1f}%).",
        })

    absorcion_bruta_m2 = sum((snap_nuevo[k]["m2"] or 0.0) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["alta"]
    ] if k in snap_nuevo)
    absorcion_bruta_uf = sum(_monto_mensual_uf(snap_nuevo[k]) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["alta"]
    ] if k in snap_nuevo)
    absorcion_baja_m2 = sum((snap_prev[k]["m2"] or 0.0) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["baja"]
    ] if k in snap_prev)
    absorcion_baja_uf = sum(_monto_mensual_uf(snap_prev[k]) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["baja"]
    ] if k in snap_prev)

    return {
        "activo_key": activo_key,
        "periodo": periodo,
        "periodo_anterior": periodo_prev,
        "tiene_snapshot_anterior": bool(snap_prev),
        "eventos": eventos,
        "casos_raros": casos_raros,
        "totales": {
            "periodo_anterior": _totales_activo(snap_prev),
            "periodo_actual": _totales_activo(snap_nuevo),
        },
        "absorcion": {
            "bruta_m2": round(absorcion_bruta_m2, 2),
            "bruta_uf": round(absorcion_bruta_uf, 2),
            "neta_m2": round(absorcion_bruta_m2 - absorcion_baja_m2, 2),
            "neta_uf": round(absorcion_bruta_uf - absorcion_baja_uf, 2),
        },
    }


# ── Validación (gate duro) ────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.ok = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.data: dict = {}

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.ok = False

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, **self.data}


_ERROR_LABELS = {
    "lectura": "Error de lectura",
    "val1_vacantes": "VAL1 — Coherencia de vacantes",
    "val2_absorcion": "VAL2 — Movimientos sin registro en Absorción",
    "val3_escalonada": "VAL3 — Renta escalonada no coincide",
    "val4_terminos": "VAL4 — Contratos con fecha de término vencida",
}


def _flatten_validator_errors(errores: dict) -> list[str]:
    """Convierte el dict de _validar_archivo en mensajes legibles para el gate duro."""
    out = []
    if "lectura" in errores:
        out.append(f"{_ERROR_LABELS['lectura']}: {errores['lectura']}")
        return out
    for key in ("val1_vacantes", "val2_absorcion", "val3_escalonada", "val4_terminos"):
        rows = errores.get(key)
        if not rows:
            continue
        label = _ERROR_LABELS[key]
        out.append(f"{label}: {len(rows)} caso(s) — no se puede ingestar hasta corregir el archivo fuente.")
    return out


def _file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _write_tmp(file_bytes: bytes, filename: str) -> str:
    suffix = os.path.splitext(filename)[1] or ".xlsx"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return tmp_path


def validate(file_bytes: bytes, filename: str, periodo: str) -> ValidationResult:
    """Dry-run completo: valida VAL1-VAL4, arma diff de absorción por activo,
    detecta casos raros. No toca la DB (salvo lecturas).
    """
    result = ValidationResult()

    try:
        y, m = periodo.split("-")
        int(y), int(m)
    except (ValueError, AttributeError):
        result.add_error(f"periodo {periodo!r} inválido, se espera 'YYYY-MM'")
        return result

    tmp_path = _write_tmp(file_bytes, filename)
    try:
        cierre = _cierre_from_periodo(periodo)
        val = _validar_archivo(tmp_path, cierre)
        errores = val.get("errores", {})
        for msg in _flatten_validator_errors(errores):
            result.add_error(msg)

        if not result.ok:
            result.data = {"periodo": periodo, "filename": val.get("archivo"), "errores_detalle": errores}
            if "lectura" not in errores:
                y, m = (int(x) for x in periodo.split("-"))
                aamm = f"{str(y)[2:]}{m:02d}"
                asunto, cuerpo = build_email_jll(errores, aamm, MESES_ES[m], y)
                result.data["email_proveedor"] = {"para": "Nicole (JLL)", "asunto": asunto, "cuerpo": cuerpo}
            return result

        source_data = _read_source_data(tmp_path)
        if not source_data:
            result.add_error("No se pudieron leer filas de la hoja 'Rent Roll' (¿formato distinto al esperado?)")
            return result

        activos_presentes = sorted({
            _RR_ACTIVO_KEY[str(rec.get("Activo1") or "").strip()]
            for rec in source_data.values()
            if str(rec.get("Activo1") or "").strip() in _RR_ACTIVO_KEY
        })
        if not activos_presentes:
            result.add_error("No se reconoció ningún activo mapeable (Activo1) en el archivo.")
            return result

        diffs = {activo: diff_absorcion(activo, periodo, source_data) for activo in activos_presentes}

        casos_raros_total = sum(len(d["casos_raros"]) for d in diffs.values())
        if casos_raros_total:
            result.warnings.append(
                f"{casos_raros_total} caso(s) fuera de lo común detectados en el diff de absorción — "
                "revisar y confirmar antes de ingestar."
            )
        for activo, d in diffs.items():
            if not d["tiene_snapshot_anterior"]:
                result.warnings.append(
                    f"{activo}: no hay snapshot en DB para {d['periodo_anterior']} — no se puede "
                    "calcular absorción vs mes anterior (se ingesta igual, solo faltará el diff)."
                )

        fh = _file_hash(file_bytes)
        conn = get_conn_for(str(DB_PATH))
        try:
            existing = conn.execute(
                "SELECT COUNT(*) FROM raw_rent_roll_line WHERE file_hash=?", (fh,)
            ).fetchone()[0]
        finally:
            conn.close()
        if existing:
            result.warnings.append("Este mismo archivo ya fue ingestado antes (idéntico byte a byte).")

        result.data = {
            "periodo": periodo,
            "filename": val.get("archivo"),
            "activos": activos_presentes,
            "diffs": diffs,
            "n_filas_fuente": len(source_data),
            "file_hash": fh,
            "ya_ingestado": bool(existing),
        }
        return result
    finally:
        os.remove(tmp_path)


def commit(file_bytes: bytes, filename: str, periodo: str) -> dict:
    """Re-valida (defensa en profundidad) y persiste. Lanza ValueError si no pasa el gate."""
    result = validate(file_bytes, filename, periodo)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    fh = result.data["file_hash"]
    tmp_path = _write_tmp(file_bytes, filename)
    try:
        source_data = _read_source_data(tmp_path)

        conn = get_conn_for(str(DB_PATH))
        try:
            existing = conn.execute(
                "SELECT COUNT(*) FROM raw_rent_roll_line WHERE file_hash=?", (fh,)
            ).fetchone()[0]
            if existing:
                return {"status": "skipped_duplicate", "rows_inserted": 0, "activos": result.data["activos"]}

            run_id = repo_audit.start_ingest_run(
                conn, tool="ingest_rent_roll_validated:jll", source_file=filename, file_hash=fh,
            )

            lines = []
            for i, ((activo2, detalle), rec) in enumerate(source_data.items()):
                activo1 = str(rec.get("Activo1") or "").strip()
                activo_key = _RR_ACTIVO_KEY.get(activo1)
                if activo_key is None:
                    continue
                extra = {
                    "activo1": activo1,
                    "activo2": activo2,
                    "tipo_activo_1": rec.get("Tipo Activo 1"),
                    "tipo_activo_3": rec.get("Tipo Activo 3"),
                    "tipo_arrendatario": rec.get("Tipo Arrendatario"),
                    "rol": rec.get("Rol"),
                    "fecha_inicio": _rr_date_str(rec.get("Fecha Inicio")),
                }
                lines.append({
                    "activo_key": activo_key,
                    "periodo": periodo,
                    "unidad": detalle,
                    "arrendatario": (str(rec.get("Arrendatario")).strip()
                                     if rec.get("Arrendatario") is not None else None),
                    "m2": _rr_num(rec.get("Area Arrendable (m2)")),
                    "renta_uf": _rr_num(rec.get("Renta Fija (UF/m2 /mes)")),
                    "vencimiento": _rr_date_str(rec.get("Término del Contrato")),
                    "extra_json": json.dumps(extra, ensure_ascii=False, default=str),
                    "source_file": filename,
                    "source_sheet": "Rent Roll",
                    "source_row": i,
                    "file_hash": fh,
                })

            n = repo_rent_roll.insert_lines(conn, lines, run_id)
            repo_audit.finish_ingest_run(conn, run_id, rows_in=len(lines), rows_loaded=n, status="ok")
            return {
                "status": "ok",
                "run_id": run_id,
                "rows_inserted": n,
                "activos": result.data["activos"],
            }
        finally:
            conn.close()
    finally:
        os.remove(tmp_path)
