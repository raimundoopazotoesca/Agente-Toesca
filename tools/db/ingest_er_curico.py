"""Ingesta ER Mall Curicó (activo, fondo TRI) → raw_er_activo_line.

Lee la planilla xlsx 'RAW/NOI Curico.xlsx' (SharePoint), hoja 'Hoja1', y
persiste cada cuenta contable individual en raw_er_activo_line. Idempotente
por file_hash.

Mismo enfoque que ingest_er_vina.py: el código de cuenta se extrae por
regex de la columna C (no diccionario fijo de categorías), y la sección
(INGRESOS_OPERACION / INGRESO_FUERA_EXPLOTACION / GASTOS_OPERACION) se
determina por los headers de sección que preceden a cada cuenta.

Diferencias clave vs. Viña:
  - No hay header de texto "Ingreso de Explotacion" en columna C (columna B
    tiene un residuo de plantilla vieja desalineada, se ignora). La sección
    INGRESOS_OPERACION es la de arranque por defecto, justo después de la
    fila de fechas.
  - La Sección 1 (datos reales) está ARRIBA del archivo y la Sección 2
    (espejo en UF) está ABAJO — orden inverso a Viña. El recorrido corta en
    la PRIMERA ocurrencia de "Total Operacional", no la última.
  - La sección "Resultado No Operacional" (financiero: leasing, intereses,
    variación UF) no se ingesta — no la usa el NOI de referencia (fila 133
    de la fuente).

monto_clp = pesos reales (fiel a la fuente, con signo aplicado). monto_uf =
monto_clp / UF de fin de mes (fact_uf de la DB, no la UF de la propia
planilla).

NOI (confirmado por el usuario 2026-07-14): SUM(monto_uf) WHERE
es_operacional=1, es decir Ingreso Explotación + Gastos de Administración y
Ventas, SIN Ingreso Fuera de Explotación — misma metodología que la fila
133 "Noi" de la fuente, pero recalculada desde las cuentas crudas: la
fuente tiene 3 cuentas huérfanas (3-1-10-115 Mantención Cobro Directo,
3-1-10-116 Mantención Activo, 3-1-10-117 Servicios Administrativos Activo)
que sus propias fórmulas de subtotal de categoría (MANTENCIÓN, SERVICIOS)
no incluyen — impacto real de hasta 5.7% del gasto en algunos meses. Este
parser las incluye igual, porque recorre todas las cuentas por código
dentro de cada sección sin depender de las fórmulas de la fuente.

Validación de integridad (por periodo, en pesos):
  - Ingreso Explotación: ESTRICTA. SUM(cuentas) == "Total Resultado
    Operación" (tolerancia 2000 CLP) — el rango de la fuente es contiguo,
    sin huecos conocidos.
  - Gastos de Administración y Ventas: BLANDA. abs(SUM(cuentas)) >=
    abs("Total Gastos de administración y ventas") - 2000 CLP — no puede
    ser estricta por el gap de cuentas huérfanas ya documentado, pero la
    suma calculada nunca puede ser MENOR en magnitud al subtotal de la
    fuente sin indicar un bug real de parseo.
"""
from __future__ import annotations

import calendar
import hashlib
import re
import sqlite3
from typing import Optional

import openpyxl


_ACTIVO_KEY = "Mall Curicó"

_ACCOUNT_RE = re.compile(r"^(\d(?:-\d{1,3}){3})\s+(.+)$")

_HEADER_FUERA_EXPLOTACION = re.compile(r"^ingreso fuera de explotacion$", re.I)
_HEADER_GASTOS_OPERACION = re.compile(r"^gastos de administraci.n y ventas$", re.I)
_SUBTOTAL_RESULTADO_OPERACION = re.compile(r"^total resultado operaci.n$", re.I)
_SUBTOTAL_GASTOS_ADMIN = re.compile(r"^total gastos de administraci.n y ventas$", re.I)
_TERMINATOR = re.compile(r"^total operacional$", re.I)

_ES_OPERACIONAL = {
    "INGRESOS_OPERACION": 1,
    "GASTOS_OPERACION": 1,
    "INGRESO_FUERA_EXPLOTACION": 0,
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
    """Lee la planilla ER Mall Curicó y devuelve filas para raw_er_activo_line.

    Requiere conexión a la DB para resolver la UF de fin de mes (fact_uf) por
    periodo, igual que ingest_er_vina.parse_planilla.
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

        # 1) Fila de fechas: la fila con MÁS celdas tipo fecha de toda la hoja.
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

        # 2) Recorrer filas desde justo después de la fila de fechas. Sin
        #    header de texto para arrancar (a diferencia de Viña): la
        #    sección por defecto es INGRESOS_OPERACION.
        out: list[dict] = []
        current_seccion: str = "INGRESOS_OPERACION"
        suma_ingreso_explotacion: dict[str, float] = {}
        suma_gastos_admin: dict[str, float] = {}
        subtotal_ingreso_explotacion: dict[str, float] = {}
        subtotal_gastos_admin: dict[str, float] = {}
        terminador_encontrado = False

        for i in range(header_row_idx + 1, len(all_rows)):
            row = all_rows[i]
            raw_label = row[2].value if len(row) > 2 else None
            label = _norm(raw_label)
            if not label:
                continue

            if _TERMINATOR.match(label):
                terminador_encontrado = True
                break

            if _HEADER_FUERA_EXPLOTACION.match(label):
                current_seccion = "INGRESO_FUERA_EXPLOTACION"
                continue
            if _HEADER_GASTOS_OPERACION.match(label):
                current_seccion = "GASTOS_OPERACION"
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
                continue  # header de subcategoría (ej. "SEGURIDAD"), sin código de cuenta

            cuenta_codigo, cuenta_nombre = m.group(1), m.group(2).strip()
            es_operacional = _ES_OPERACIONAL[current_seccion]

            for col, periodo in period_by_col.items():
                cell = row[col - 1] if col - 1 < len(row) else None
                monto_clp = float(cell.value) if cell is not None and cell.value is not None else 0.0
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

        # 3) Validación de integridad.
        _TOLERANCIA_CLP = 2000.0
        for periodo, esperado in subtotal_ingreso_explotacion.items():
            real = suma_ingreso_explotacion.get(periodo, 0.0)
            if abs(real - esperado) >= _TOLERANCIA_CLP:
                raise ValueError(
                    f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                    f"suma Ingreso Explotación={real!r} != Total Resultado Operación={esperado!r}"
                )
        # Gastos Admin y Ventas: validación blanda (la fuente subestima por
        # 3 cuentas huérfanas fuera de los rangos SUM() de sus categorías,
        # confirmado por el usuario 2026-07-14). La suma calculada nunca
        # puede ser MENOR (en magnitud) al subtotal de la fuente.
        for periodo, esperado in subtotal_gastos_admin.items():
            real = suma_gastos_admin.get(periodo, 0.0)
            if abs(real) < abs(esperado) - _TOLERANCIA_CLP:
                raise ValueError(
                    f"Validación de integridad falló en {xlsx_path}, periodo {periodo}: "
                    f"suma Gastos Admin y Ventas={real!r} es menor (en magnitud) que "
                    f"Total Gastos de administración y ventas={esperado!r} de la fuente "
                    f"(posible cuenta no capturada por el parser)"
                )

        return out
    finally:
        if owns_conn:
            conn.close()


# ── Persistencia ─────────────────────────────────────────────────────────

def persist(xlsx_path: str,
            conn: "sqlite3.Connection | None" = None) -> dict:
    """Ingesta idempotente de la planilla ER Mall Curicó en raw_er_activo_line.

    Comportamiento idéntico a ingest_er_vina.persist:
    - Si ya existen filas activas (superseded_at IS NULL) con el mismo
      file_hash → no hace nada, retorna status 'skipped_idempotent'.
    - Si existen filas activas de una ingesta anterior (activo_key='Mall
      Curicó', otro file_hash) → las marca superseded e inserta las nuevas
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
            conn, tool="ingest_er_curico",
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
