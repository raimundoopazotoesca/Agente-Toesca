"""Valida y persiste el JSON de EEFF pegado por el usuario (extraído vía ChatGPT).

Reusa la lógica de normalización de scripts/ingest_from_json.py (misma
validación estructural que la vía CLI) y agrega:
  - chequeo de "prompt_version" conocida (evita prompt-drift silencioso)
  - recálculo server-side de la suma de gastos de operación (no confía en el
    campo "cuadra" que devuelva el LLM)
  - resolución de cuenta_codigo_canonical vía eeff_cuenta_mapper
  - un preview humano-legible (valor cuota, dividendos, tabla de gastos)
  - persistencia idempotente por file_hash = sha256(texto pegado)

No expone CLI; lo consume tools/db/ingesta_server (Flask).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

sys.path.insert(0, str(ROOT / "scripts"))
from ingest_from_json import (  # noqa: E402
    _validate_eeff_payload,
    _normalize_dividendo,
    _normalize_valor_cuota,
)

from tools.db.connection import get_conn_for  # noqa: E402
from tools.db.eeff_cuenta_mapper import get_canonical_code  # noqa: E402

PROMPT_VERSIONS_CONOCIDAS = {"eeff-v1"}
FONDOS_VALIDOS = {"TRI", "PT", "APO"}

COMPONENTES_GASTOS = (
    "ER.depreciaciones",
    "ER.remun_comite",
    "ER.comision_admin",
    "ER.honorarios_custodia",
    "ER.costos_transaccion",
    "ER.otros_gastos",
)
TOTAL_GASTOS = "ER.total_gastos_operacion"
TOLERANCIA_CLP = 2000


def _parse_json(raw_text: str) -> dict:
    text = raw_text.strip()
    # Tolerar que el usuario pegue el bloque envuelto en ```json ... ```
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"El texto pegado no es JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("El JSON raíz debe ser un objeto")
    return data


def _validate_top_level(data: dict, fondo_expected: str) -> list[str]:
    errors = []
    fondo = data.get("fondo")
    if fondo != fondo_expected:
        errors.append(
            f"Campo 'fondo' es {fondo!r}, se esperaba {fondo_expected!r} "
            f"(¿pegaste la respuesta del fondo equivocado?)"
        )
    prompt_version = data.get("prompt_version")
    if prompt_version not in PROMPT_VERSIONS_CONOCIDAS:
        errors.append(
            f"prompt_version {prompt_version!r} desconocida "
            f"(esperada una de {sorted(PROMPT_VERSIONS_CONOCIDAS)}). "
            f"Usa el prompt actual de prompts/eeff_{fondo_expected.lower()}.md."
        )
    return errors


def _check_gastos_sum(lineas: list[dict], en_miles: bool) -> dict:
    """Recalcula, por periodo, si suma(componentes) == total_gastos_operacion."""
    factor = 1000 if en_miles else 1
    por_periodo: dict[str, dict] = {}
    for linea in lineas:
        codigo = linea.get("cuenta_codigo")
        if codigo not in COMPONENTES_GASTOS and codigo != TOTAL_GASTOS:
            continue
        periodo = linea["periodo"]
        monto = (linea.get("monto_clp") or 0) * factor
        por_periodo.setdefault(periodo, {})[codigo] = monto

    resultado = {}
    for periodo, cuentas in por_periodo.items():
        if TOTAL_GASTOS not in cuentas:
            continue  # sin total reportado en este periodo, no hay nada que verificar
        total = cuentas[TOTAL_GASTOS]
        suma = sum(cuentas.get(c, 0) for c in COMPONENTES_GASTOS)
        cuadra = abs(suma - total) <= TOLERANCIA_CLP
        resultado[periodo] = {
            "filas": [
                {"cuenta_codigo": c, "monto_clp": cuentas.get(c, 0)}
                for c in COMPONENTES_GASTOS
                if c in cuentas
            ],
            "suma_componentes": suma,
            "total_reportado": total,
            "cuadra": cuadra,
        }
    return resultado


def _resolve_canonical(lineas: list[dict]) -> tuple[list[dict], int, int]:
    mapeadas = 0
    no_mapeadas = 0
    out = []
    for linea in lineas:
        codigo = linea.get("cuenta_codigo")
        if not codigo:
            codigo = get_canonical_code(linea["cuenta_nombre"], linea["section"])
        if codigo:
            mapeadas += 1
        else:
            no_mapeadas += 1
        out.append({**linea, "cuenta_codigo_canonical": codigo})
    return out, mapeadas, no_mapeadas


def _periodos_existentes(fondo: str, periodos: list[str]) -> dict[str, int]:
    con = get_conn_for(str(DB_PATH))
    try:
        out = {}
        for periodo in periodos:
            n = con.execute(
                "SELECT COUNT(*) FROM raw_eeff_line "
                "WHERE fondo_key=? AND periodo=? AND superseded_at IS NULL",
                (fondo, periodo),
            ).fetchone()[0]
            if n:
                out[periodo] = n
        return out
    finally:
        con.close()


def _valor_cuota_deltas(fondo: str, vc_norm: list[dict]) -> list[dict]:
    con = get_conn_for(str(DB_PATH))
    try:
        out = []
        for vc in vc_norm:
            prev = con.execute(
                "SELECT precio_clp, precio_uf FROM raw_valor_cuota_contable "
                "WHERE fondo_key=? AND nemotecnico=? AND fecha < ? "
                "ORDER BY fecha DESC LIMIT 1",
                (fondo, vc["nemotecnico"], vc["fecha"]),
            ).fetchone()
            delta_pct = None
            if prev and prev[0] and vc.get("precio_clp"):
                delta_pct = round((vc["precio_clp"] / prev[0] - 1) * 100, 2)
            out.append({**vc, "precio_clp_anterior": prev[0] if prev else None, "delta_pct": delta_pct})
        return out
    finally:
        con.close()


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


def validate(
    raw_text: str,
    fondo_expected: str,
    periodo_declarado: str | None = None,
    fecha_publicacion: str | None = None,
) -> ValidationResult:
    """Dry-run completo: parsea, valida, arma preview. No toca la DB (salvo lecturas)."""
    result = ValidationResult()

    if fondo_expected not in FONDOS_VALIDOS:
        result.add_error(f"Fondo {fondo_expected!r} inválido")
        return result

    if not periodo_declarado:
        result.add_error("Falta declarar el período (YYYY-MM) del EEFF que estás ingestando.")
        return result
    if not fecha_publicacion:
        result.add_error("Falta la fecha de publicación del EEFF.")
        return result

    try:
        data = _parse_json(raw_text)
    except ValueError as exc:
        result.add_error(str(exc))
        return result

    for msg in _validate_top_level(data, fondo_expected):
        result.add_error(msg)
    if not result.ok:
        return result

    try:
        periodos, lineas, duplicates_removed, periodos_added = _validate_eeff_payload(data)
    except ValueError as exc:
        result.add_error(f"Estructura de 'lineas'/'periodos_reportados' inválida: {exc}")
        return result

    if duplicates_removed:
        result.warnings.append(f"{duplicates_removed} línea(s) duplicada(s) fueron ignoradas.")

    if periodo_declarado not in periodos:
        result.add_error(
            f"Declaraste el período {periodo_declarado!r} pero el JSON reporta "
            f"periodos_reportados={periodos} (no incluye {periodo_declarado!r}). "
            f"¿Es el EEFF correcto?"
        )

    en_miles = bool(data.get("en_miles_pesos", False))
    gastos_check = _check_gastos_sum(lineas, en_miles)
    periodos_sin_cuadre = [p for p, chk in gastos_check.items() if not chk["cuadra"]]
    for p in periodos_sin_cuadre:
        chk = gastos_check[p]
        result.add_error(
            f"Periodo {p}: suma de gastos ({chk['suma_componentes']:,.0f}) "
            f"≠ total reportado ({chk['total_reportado']:,.0f}), "
            f"diferencia {chk['suma_componentes'] - chk['total_reportado']:,.0f} CLP."
        )

    lineas_canonical, mapeadas, no_mapeadas = _resolve_canonical(lineas)
    if no_mapeadas:
        result.warnings.append(
            f"{no_mapeadas} de {len(lineas)} cuenta(s) no se pudieron mapear a un código "
            f"canónico (quedan solo con el nombre tal cual del PDF; no bloquea la ingesta)."
        )

    # --- valor_cuota (opcional) ---
    vc_norm: list[dict] = []
    vc_raw = data.get("valor_cuota", [])
    if vc_raw:
        if not isinstance(vc_raw, list):
            result.add_error("'valor_cuota' debe ser una lista")
        else:
            try:
                for idx, vc in enumerate(vc_raw):
                    vc_norm.append(_normalize_valor_cuota(vc, idx))
            except ValueError as exc:
                result.add_error(f"'valor_cuota' inválido: {exc}")

    # --- dividendos (opcional) ---
    div_norm: list[dict] = []
    div_raw = data.get("dividendos", [])
    if div_raw:
        if not isinstance(div_raw, list):
            result.add_error("'dividendos' debe ser una lista")
        else:
            try:
                for idx, div in enumerate(div_raw):
                    div_norm.append(_normalize_dividendo(div, idx))
            except ValueError as exc:
                result.add_error(f"'dividendos' inválido: {exc}")

    if not result.ok:
        return result

    periodos_existentes = _periodos_existentes(fondo_expected, periodos)
    if periodos_existentes:
        detalle = ", ".join(f"{p} ({n} filas)" for p, n in periodos_existentes.items())
        result.warnings.append(
            f"Ya existen filas en la DB para: {detalle}. Si confirmas, se agregan "
            f"como una nueva versión (no se sobrescriben las existentes)."
        )

    vc_con_delta = _valor_cuota_deltas(fondo_expected, vc_norm)

    fhash = hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()
    existing_hash = 0
    con = get_conn_for(str(DB_PATH))
    try:
        existing_hash = con.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
    finally:
        con.close()
    if existing_hash:
        result.warnings.append(
            "Este mismo texto ya fue ingestado antes (idéntico al carácter) — "
            "confirmar no creará filas duplicadas."
        )

    result.data = {
        "fondo": fondo_expected,
        "periodo_declarado": periodo_declarado,
        "fecha_publicacion": fecha_publicacion,
        "periodos": periodos,
        "n_lineas": len(lineas),
        "gastos_por_periodo": gastos_check,
        "cuentas_mapeadas": {"total": len(lineas), "mapeadas": mapeadas, "no_mapeadas": no_mapeadas},
        "valor_cuota": vc_con_delta,
        "dividendos": div_norm,
        "periodos_existentes": periodos_existentes,
        "file_hash": fhash,
        "ya_ingestado": bool(existing_hash),
    }
    return result


def commit(
    raw_text: str,
    fondo_expected: str,
    periodo_declarado: str | None = None,
    fecha_publicacion: str | None = None,
) -> dict:
    """Re-valida (defensa en profundidad) y persiste. Lanza ValueError si no pasa validación."""
    result = validate(raw_text, fondo_expected, periodo_declarado, fecha_publicacion)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    data = _parse_json(raw_text)
    periodos, lineas, _, _ = _validate_eeff_payload(data)
    lineas_canonical, _, _ = _resolve_canonical(lineas)

    vc_norm = [_normalize_valor_cuota(vc, i) for i, vc in enumerate(data.get("valor_cuota", []) or [])]
    div_norm = [_normalize_dividendo(d, i) for i, d in enumerate(data.get("dividendos", []) or [])]

    en_miles = bool(data.get("en_miles_pesos", False))
    factor = 1000 if en_miles else 1

    fhash = result.data["file_hash"]
    source_file = f"chatgpt_manual_{fondo_expected}"

    con = get_conn_for(str(DB_PATH))
    try:
        existing = con.execute(
            "SELECT COUNT(*) FROM raw_eeff_line WHERE file_hash=?", (fhash,)
        ).fetchone()[0]
        if existing:
            return {"status": "skipped_duplicate", "rows_eeff": 0, "rows_valor_cuota": 0, "rows_dividendos": 0}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            """INSERT INTO ingest_run
               (tool, source_file, file_hash, started_at, status, periodo_declarado, fecha_publicacion)
               VALUES (?,?,?,?,?,?,?)""",
            ("ingest_eeff_validated", source_file, fhash, now, "running", periodo_declarado, fecha_publicacion),
        )
        run_id = cur.lastrowid

        rows_eeff = [
            (
                fondo_expected, L["periodo"], L["cuenta_codigo"], L["cuenta_nombre"],
                (L["monto_clp"] * factor) if L["monto_clp"] is not None else None,
                L["monto_uf"], source_file, L["section"], None, fhash, run_id,
                L["cuenta_codigo_canonical"],
            )
            for L in lineas_canonical
        ]
        con.executemany(
            """INSERT INTO raw_eeff_line
               (fondo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
                source_file, source_sheet, source_row, file_hash, ingest_run_id,
                cuenta_codigo_canonical)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows_eeff,
        )

        rows_vc = 0
        for vc in vc_norm:
            con.execute(
                """INSERT OR IGNORE INTO raw_valor_cuota_contable
                   (fondo_key, nemotecnico, fecha, precio_clp, precio_uf,
                    uf_dia, cuotas, periodo, source_file, file_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (fondo_expected, vc["nemotecnico"], vc["fecha"], vc["precio_clp"], vc["precio_uf"],
                 vc["uf_dia"], vc["cuotas"], vc["periodo"], source_file, fhash),
            )
            rows_vc += con.execute("SELECT changes()").fetchone()[0]

        rows_div = 0
        for div in div_norm:
            con.execute(
                """INSERT INTO raw_dividendo
                   (fondo_key, nemotecnico, fecha_pago, monto_uf_cuota, monto_clp_cuota,
                    periodo, source_file, file_hash, tipo)
                   SELECT ?,?,?,?,?,?,?,?,'dividendo'
                   WHERE NOT EXISTS (
                       SELECT 1 FROM raw_dividendo
                       WHERE fondo_key=? AND nemotecnico=? AND fecha_pago=? AND tipo='dividendo'
                         AND source_file=? AND file_hash=? AND superseded_at IS NULL
                   )""",
                (fondo_expected, div["nemotecnico"], div["fecha_pago"], div["monto_uf_cuota"],
                 div["monto_clp_cuota"], div["periodo"], source_file, fhash,
                 fondo_expected, div["nemotecnico"], div["fecha_pago"], source_file, fhash),
            )
            rows_div += con.execute("SELECT changes()").fetchone()[0]

        con.execute(
            "UPDATE ingest_run SET status=?, ended_at=?, rows_in=?, rows_loaded=? WHERE id=?",
            ("ok", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(lineas), len(rows_eeff), run_id),
        )
        con.commit()
        return {
            "status": "ok",
            "run_id": run_id,
            "rows_eeff": len(rows_eeff),
            "rows_valor_cuota": rows_vc,
            "rows_dividendos": rows_div,
        }
    finally:
        con.close()
