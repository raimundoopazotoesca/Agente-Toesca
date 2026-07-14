"""Ingesta ER Viña Centro (activo, fondo TRI) → raw_er_activo_line.

Lee la planilla xlsx 'RAW/NOI VIÑA.xlsx' (SharePoint), sección de input
manual (a partir de la fila 124: "Ingreso de Explotacion"), y persiste cada
cuenta contable individual en raw_er_activo_line. Idempotente por file_hash.

Diferencia clave vs. ingest_er_inmosa.py / ingest_er_sucden.py / etc: esos
activos traen la planilla ya agregada por categoría y en UF. Viña Centro
trae ~70 cuentas contables en **pesos crudos**, y la lista de cuentas no es
estable (se agregan cuentas nuevas con el tiempo, ej. "CUOTA INCORPORACIÓN
FONDO PROMOCIÓN" desde 2026-01). Por eso acá NO se usa un diccionario fijo
de categorías: el código de cuenta se extrae por regex de la columna C, y la
sección (INGRESOS_OPERACION / INGRESO_FUERA_EXPLOTACION / GASTOS_OPERACION)
se determina por los headers de sección que preceden a cada cuenta.

monto_clp = pesos reales (fiel a la fuente, con signo aplicado: gastos ya
vienen negativos). monto_uf = monto_clp / UF de fin de mes (fact_uf de la
DB — no la UF que trae la propia planilla, decisión del usuario 2026-07-14).

NOI (confirmado por el usuario 2026-07-14): SUM(monto_uf) WHERE
es_operacional=1, es decir Ingreso Explotación + Gastos de Administración y
Ventas, SIN Ingreso Fuera de Explotación. La propia planilla NO calcula esto
correctamente en ninguna de sus dos filas de NOI:
  - fila 87 "Total Operacional" = Total Gastos Admin y Ventas + Total
    Ingresos (Total Ingresos = Resultado Operación + Fuera de Explotación,
    ver fórmula E207=E205+E152, E152=E150+E142) → CONTAMINADA con ingresos
    fuera de explotación.
  - fila 119 "Noi" (Sección 2) → tiene referencias UF incorrectas entre
    sep-2023 y ene-2025 (bug confirmado por el usuario), resta gastos de
    más.
Por eso este parser recalcula el NOI desde cero a partir de las cuentas
crudas, sin reusar ninguna fórmula de la planilla.

Validación de integridad (por periodo, en pesos):
  - SUM(cuentas Ingreso Explotación) == "Total Resultado Operación" (fila 142)
  - SUM(cuentas Gastos Admin y Ventas) == "Total Gastos de administración y
    ventas" (fila 205)
"""
from __future__ import annotations

import calendar
import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl


_ACTIVO_KEY = "Viña Centro"

_ACCOUNT_RE = re.compile(r"^(\d(?:-\d{1,3}){3})\s+(.+)$")

_SECTION_HEADERS = [
    (re.compile(r"^ingreso de explotacion$", re.I), "INGRESOS_OPERACION"),
    (re.compile(r"^ingreso fuera de explotacion$", re.I), "INGRESO_FUERA_EXPLOTACION"),
    (re.compile(r"^gastos de administraci.n y ventas$", re.I), "GASTOS_OPERACION"),
]
_SUBTOTAL_RESULTADO_OPERACION = re.compile(r"^total resultado operaci.n$", re.I)
_SUBTOTAL_GASTOS_ADMIN = re.compile(r"^total gastos de administraci.n y ventas$", re.I)
_TERMINATOR = re.compile(r"^total operacional$", re.I)

_ES_OPERACIONAL = {
    "INGRESOS_OPERACION": 1,
    "GASTOS_OPERACION": 1,
    "INGRESO_FUERA_EXPLOTACION": 0,
}

# ── Overrides de datos faltantes en la fuente (confirmados por el usuario) ──
# La planilla trae, para ciertas cuentas y periodos puntuales, la fila de
# categoría (header, ej. "SEGURIDAD") con el total correcto pero la cuenta
# hija en blanco (0 tras el parseo). El total del header no se ingesta (no
# tiene código de cuenta), así que sin este override la suma de cuentas hijas
# queda por debajo del total real y la validación de integridad falla.
# Valores confirmados por el usuario 2026-07-14 contra el detalle real.
_OVERRIDES_MONTO_CLP: dict[tuple[str, str], float] = {
    # SEGURIDAD PARKING: fila "3-1-10-120" vino en blanco jul-nov 2025.
    ("3-1-10-120", "2025-07"): -57_551_335.0,
    ("3-1-10-120", "2025-08"): -5_697_924.0,
    ("3-1-10-120", "2025-09"): -5_691_943.0,
    ("3-1-10-120", "2025-10"): -4_837_982.0,
    ("3-1-10-120", "2025-11"): -3_811_045.0,
    # CONTRIBUCIONES: fila "3-1-40-102" vino en blanco abr-may 2026 (valor
    # se mantiene plano respecto a mar-2026, confirmado por el usuario).
    ("3-1-40-102", "2026-04"): -63_779_346.0,
    ("3-1-40-102", "2026-05"): -63_779_346.0,
}


def _norm(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip())


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _uf_fin_mes(conn: sqlite3.Connection, periodo: str) -> float:
    from tools.db import repo_fact

    year, month = (int(x) for x in periodo.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    fecha = f"{year:04d}-{month:02d}-{last_day:02d}"
    return repo_fact.get_uf(conn, fecha)


def parse_planilla(xlsx_path: str, conn: "sqlite3.Connection | None" = None) -> list[dict]:
    """Lee la planilla ER Viña Centro y devuelve filas para raw_er_activo_line.

    Requiere conexión a la DB para resolver la UF de fin de mes (fact_uf) por
    periodo — a diferencia de los demás parsers de er_activo, acá SÍ se hace
    la conversión CLP→UF en el parser (la fuente trae pesos crudos).
    """
    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.worksheets[0]
        sheet_name = ws.title
        all_rows = list(ws.iter_rows(values_only=False))
        wb.close()

        # 1) Fila de fechas: la fila con MÁS celdas tipo fecha de toda la
        #    hoja (sin umbral fijo — futuras entregas pueden traer menos
        #    meses que el histórico completo, el usuario confirmó 2026-07-14
        #    que el formato de filas 126+ se mantiene pero no necesariamente
        #    el resto del archivo).
        header_row_idx = None
        period_by_col: dict[int, str] = {}
        best_count = 0
        for i, row in enumerate(all_rows):
            candidatos = {}
            for cell in row:
                v = cell.value
                if hasattr(v, "year") and hasattr(v, "month"):
                    candidatos[cell.column] = f"{v.year:04d}-{v.month:02d}"
            if len(candidatos) > best_count:
                best_count = len(candidatos)
                header_row_idx = i
                period_by_col = candidatos
        if header_row_idx is None or best_count == 0:
            raise ValueError(f"No se encontró fila de fechas en {xlsx_path}")

        # 2) Ancla del bloque de input manual: "Ingreso de Explotacion" en
        #    columna C. Se toma la ÚLTIMA ocurrencia en la hoja: si el
        #    archivo trae también la Sección 1 (mirror en UF, más arriba),
        #    esa aparece primero; el bloque de input real es el que está más
        #    abajo. Si el archivo viene recortado (solo el bloque de input),
        #    hay una sola ocurrencia y esa se usa igual.
        ancla_idx = None
        for i in range(len(all_rows)):
            val = _norm(all_rows[i][2].value if len(all_rows[i]) > 2 else None)
            if _SECTION_HEADERS[0][0].match(val):
                ancla_idx = i
        if ancla_idx is None:
            raise ValueError(
                f"No se encontró la fila ancla 'Ingreso de Explotacion' (input manual) en {xlsx_path}"
            )

        # 3) Recorrer filas del bloque de input, clasificando por sección.
        out: list[dict] = []
        current_seccion: Optional[str] = None
        suma_ingreso_explotacion: dict[str, float] = {}
        suma_gastos_admin: dict[str, float] = {}
        subtotal_ingreso_explotacion: dict[str, float] = {}
        subtotal_gastos_admin: dict[str, float] = {}
        terminador_encontrado = False

        for i in range(ancla_idx, len(all_rows)):
            row = all_rows[i]
            raw_label = row[2].value if len(row) > 2 else None
            label = _norm(raw_label)
            if not label:
                continue

            if _TERMINATOR.match(label):
                terminador_encontrado = True
                break

            header_match = False
            for pattern, seccion in _SECTION_HEADERS:
                if pattern.match(label):
                    current_seccion = seccion
                    header_match = True
                    break
            if header_match:
                continue

            if _SUBTOTAL_RESULTADO_OPERACION.match(label):
                for col, periodo in period_by_col.items():
                    cell = row[col - 1] if col - 1 < len(row) else None
                    if cell is not None and cell.value is not None:
                        subtotal_ingreso_explotacion[periodo] = float(cell.value)
                continue

            if _SUBTOTAL_GASTOS_ADMIN.match(label):
                for col, periodo in period_by_col.items():
                    cell = row[col - 1] if col - 1 < len(row) else None
                    if cell is not None and cell.value is not None:
                        subtotal_gastos_admin[periodo] = float(cell.value)
                continue

            m = _ACCOUNT_RE.match(label)
            if not m:
                continue  # header de categoría (ej. "SEGURIDAD"), sin código de cuenta

            if current_seccion is None:
                raise ValueError(
                    f"Cuenta {label!r} en fila {i + 1} sin sección definida (antes del primer header)"
                )

            cuenta_codigo, cuenta_nombre = m.group(1), m.group(2).strip()
            es_operacional = _ES_OPERACIONAL[current_seccion]

            for col, periodo in period_by_col.items():
                cell = row[col - 1] if col - 1 < len(row) else None
                monto_clp = float(cell.value) if cell is not None and cell.value is not None else 0.0
                monto_clp = _OVERRIDES_MONTO_CLP.get((cuenta_codigo, periodo), monto_clp)
                monto_uf = monto_clp / _uf_fin_mes(conn, periodo)

                if current_seccion == "INGRESOS_OPERACION":
                    suma_ingreso_explotacion[periodo] = suma_ingreso_explotacion.get(periodo, 0.0) + monto_clp
                elif current_seccion == "GASTOS_OPERACION":
                    suma_gastos_admin[periodo] = suma_gastos_admin.get(periodo, 0.0) + monto_clp

                out.append({
                    "activo_key":     _ACTIVO_KEY,
                    "periodo":        periodo,
                    "cuenta_codigo":  cuenta_codigo,
                    "cuenta_nombre":  cuenta_nombre,
                    "monto_clp":      monto_clp,
                    "monto_uf":       monto_uf,
                    "seccion":        current_seccion,
                    "es_operacional": es_operacional,
                    "source_file":    xlsx_path,
                    "source_sheet":   sheet_name,
                    "source_row":     i + 1,
                })

        if not terminador_encontrado:
            raise ValueError(f"No se encontró la fila 'Total Operacional' en {xlsx_path}")

        # 4) Validación de integridad: suma de cuentas == subtotal de la fuente.
        #    Tolerancia de 2000 CLP: hay un residuo de redondeo (~600 CLP) en
        #    oct/nov-2025 tras aplicar el override de SEGURIDAD PARKING, sin
        #    relevancia frente a subtotales de decenas de millones.
        _TOLERANCIA_CLP = 2000.0
        for periodo, esperado in subtotal_ingreso_explotacion.items():
            real = suma_ingreso_explotacion.get(periodo, 0.0)
            if abs(real - esperado) >= _TOLERANCIA_CLP:
                raise ValueError(
                    f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                    f"suma Ingreso Explotación={real!r} != Total Resultado Operación={esperado!r}"
                )
        for periodo, esperado in subtotal_gastos_admin.items():
            real = suma_gastos_admin.get(periodo, 0.0)
            if abs(real - esperado) >= _TOLERANCIA_CLP:
                raise ValueError(
                    f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                    f"suma Gastos Admin y Ventas={real!r} != Total Gastos de administración y ventas={esperado!r}"
                )

        return out
    finally:
        if owns_conn:
            conn.close()


# ── Persistencia ─────────────────────────────────────────────────────────

def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER Viña Centro en raw_er_activo_line.

    Comportamiento (idéntico a ingest_er_inmosa.persist):
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior (activo_key='Viña
      Centro', otro file_hash) → las marca superseded e inserta las nuevas
      ('superseded_and_reinserted').
    - Si no hay filas previas → inserta directo ('inserted').
    """
    from tools.db import repo_audit, repo_er_activo

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn
        conn = get_conn()

    try:
        file_hash = _file_hash(xlsx_path)

        prev = conn.execute(
            """SELECT 1 FROM raw_er_activo_line
                WHERE file_hash = ? AND superseded_at IS NULL
                LIMIT 1""",
            (file_hash,),
        ).fetchone()
        if prev is not None:
            return {"status": "skipped_idempotent", "rows": 0,
                    "file_hash": file_hash, "ingest_run_id": None}

        lines = parse_planilla(xlsx_path, conn=conn)
        for line in lines:
            line["file_hash"] = file_hash

        prev_hashes = conn.execute(
            """SELECT DISTINCT file_hash FROM raw_er_activo_line
                WHERE activo_key = ?
                  AND file_hash != ?
                  AND superseded_at IS NULL""",
            (_ACTIVO_KEY, file_hash),
        ).fetchall()

        if prev_hashes:
            for row in prev_hashes:
                repo_er_activo.mark_superseded(conn, file_hash=row[0])
            status = "superseded_and_reinserted"
        else:
            status = "inserted"

        run_id = repo_audit.start_ingest_run(
            conn, tool="ingest_er_vina",
            source_file=xlsx_path, file_hash=file_hash,
        )
        inserted = repo_er_activo.insert_lines(conn, lines, run_id)
        repo_audit.finish_ingest_run(
            conn, run_id, rows_in=len(lines), rows_loaded=inserted, status="ok",
        )

        return {"status": status, "rows": inserted,
                "file_hash": file_hash, "ingest_run_id": run_id}
    finally:
        if owns_conn:
            conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xlsx", help="Path a la planilla xlsx")
    ap.add_argument("--dry-run", action="store_true",
                     help="Parsea e imprime resumen, no escribe DB")
    args = ap.parse_args(argv)

    if args.dry_run:
        rows = parse_planilla(args.xlsx)
        print(f"Parsed {len(rows)} filas de {args.xlsx}")
        periodos = sorted({r["periodo"] for r in rows})
        print(f"  periodos: {periodos[0]}..{periodos[-1]} ({len(periodos)} meses)")
        from collections import defaultdict
        noi = defaultdict(float)
        for r in rows:
            if r["es_operacional"]:
                noi[r["periodo"]] += r["monto_uf"]
        print("  NOI (UF) por periodo (primeros y últimos 3):")
        for p in periodos[:3] + periodos[-3:]:
            print(f"    {p}: {noi[p]:>15,.2f}")
        return 0

    res = persist(args.xlsx)
    print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
