"""
Herramientas para actualizar las hojas Input AP, Input PT e Input Ren del CDG.

Tareas:
  TRIMESTRAL:
    1. actualizar_balance_input   → escribe balance (C5:J5) + fecha balance (B5)
  MENSUAL:
    2. actualizar_fecha_bursatil_input  → actualiza celda de fecha bursátil
    3. actualizar_fecha_contable_input  → actualiza celda de fecha contable (trimestral)
  CUANDO HAY DIVIDENDO:
    4. agregar_dividendo_input     → agrega la fecha en la tabla de dividendos

Estructura confirmada en el CDG 2603:
  Input AP:  balance fila 5, fechas C9(contable)/D9(bursátil), div tabla fila 63+
  Input PT:  balance fila 5, fechas D11(contable)/C11(bursátil), div tabla fila 82+
  Input Ren: balance fila 5, fechas D10(contable)/C10(bursátil), div tabla fila 130+

Columnas balance (fila 5):
  B=Fecha, C=Caja, D=Activos Circulantes, E=Otros Activos, F=Total(fórmula),
  G=Pasivo Circulante, H=Pasivo Largo Plazo, I=Interés Minoritario, J=Patrimonio
"""
import os
import re
import zipfile
from calendar import monthrange
from datetime import date, timedelta
from config import WORK_DIR

# ─── Configuración por fondo ───────────────────────────────────────────────────
INPUT_CFG = {
    "A&R Apoquindo": {
        "sheet":           "Input AP",
        "fecha_contable":  "C9",
        "fecha_bursatil":  "D9",
        "balance_row":     5,
        "div_start_row":   63,   # primera fila de datos en tabla dividendos
        "div_date_col":    "B",
    },
    "A&R PT": {
        "sheet":           "Input PT",
        "fecha_contable":  "D11",
        "fecha_bursatil":  "C11",
        "balance_row":     5,
        "div_start_row":   82,
        "div_date_col":    "B",
    },
    "A&R Rentas": {
        "sheet":           "Input Ren",
        "fecha_contable":  "D10",
        "fecha_bursatil":  "C10",
        "balance_row":     5,
        "div_start_row":   130,
        "div_date_col":    "B",
    },
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_path(nombre_archivo: str) -> str:
    if os.path.isabs(nombre_archivo):
        return nombre_archivo
    return os.path.join(WORK_DIR, nombre_archivo)


def _excel_date(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def _last_day(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _col_num(letter: str) -> int:
    n = 0
    for c in letter.upper():
        n = n * 26 + ord(c) - ord("A") + 1
    return n


def _find_cell_bounds(xml: str, ref: str) -> tuple:
    tag = f'<c r="{ref}"'
    start = xml.find(tag)
    if start == -1:
        return -1, -1
    i = start + len(tag)
    while i < len(xml):
        if xml[i:i+2] == '/>':
            return start, i + 2
        if xml[i] == '>':
            end = xml.find('</c>', i)
            return start, (end + 4) if end != -1 else i + 1
        i += 1
    return start, len(xml)


def _get_cell_attr(xml: str, ref: str, attr: str, default: str) -> str:
    tag = f'<c r="{ref}"'
    start = xml.find(tag)
    if start == -1:
        return default
    m = re.search(rf'\b{attr}="([^"]+)"', xml[start: start + 300])
    return m.group(1) if m else default


def _read_cell_numeric(xml: str, ref: str) -> float | None:
    start, end = _find_cell_bounds(xml, ref)
    if start == -1:
        return None
    cell_xml = xml[start:end]
    if 't="s"' in cell_xml or 't="b"' in cell_xml:
        return None
    v = re.search(r'<v>([^<]+)</v>', cell_xml)
    if not v:
        return None
    try:
        return float(v.group(1))
    except ValueError:
        return None


def _replace_or_insert_cell(row_xml: str, ref: str, new_cell: str) -> str:
    start, end = _find_cell_bounds(row_xml, ref)
    if start != -1:
        return row_xml[:start] + new_cell + row_xml[end:]
    col = re.sub(r"\d", "", ref)
    col_n = _col_num(col)
    for m in re.finditer(r'<c r="([A-Z]+)\d+"', row_xml):
        if _col_num(m.group(1)) > col_n:
            return row_xml[:m.start()] + new_cell + row_xml[m.start():]
    return row_xml + new_cell


def _write_numeric_cell(sheet_xml: str, cell_ref: str, value: float) -> str:
    """Escribe un valor numérico en una celda, preservando el estilo."""
    row_num = int(re.sub(r"[A-Z]", "", cell_ref))
    row_pat = rf'(<row\b[^>]*\br="{row_num}"[^>]*>)(.*?)(</row>)'
    row_m = re.search(row_pat, sheet_xml, re.DOTALL)

    if row_m:
        row_open = row_m.group(1)
        row_content = row_m.group(2)
    else:
        row_open = f'<row r="{row_num}" spans="1:20">'
        row_content = ""

    style = _get_cell_attr(row_content, cell_ref, "s", "0")
    new_cell = f'<c r="{cell_ref}" s="{style}"><v>{value}</v></c>'
    row_content = _replace_or_insert_cell(row_content, cell_ref, new_cell)
    new_row = row_open + row_content + "</row>"

    if row_m:
        return sheet_xml[:row_m.start()] + new_row + sheet_xml[row_m.end():]
    # Insertar en orden
    next_row_m = re.search(
        rf'<row\b[^>]*\br="({row_num + 1}|{row_num + 2}|{row_num + 3})"', sheet_xml
    )
    if next_row_m:
        return sheet_xml[:next_row_m.start()] + new_row + sheet_xml[next_row_m.start():]
    return sheet_xml.replace("</sheetData>", new_row + "</sheetData>")


def _apply_to_xlsx(filepath: str, modifications: dict) -> None:
    tmp = filepath + ".tmp"
    with zipfile.ZipFile(filepath, "r") as zin:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = modifications.get(item.filename)
                if data is not None:
                    zout.writestr(item, data if isinstance(data, bytes) else data.encode("utf-8"))
                else:
                    zout.writestr(item, zin.read(item.filename))
    os.replace(tmp, filepath)


def _find_sheet_xml_path(xlsx_path: str, sheet_name: str) -> str | None:
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
        m = re.search(
            r'<sheet\b[^>]*\bname="' + re.escape(sheet_name) + r'"[^>]*\br:id="([^"]+)"',
            wb_xml,
        )
        if not m:
            return None
        rid = m.group(1)
        rels_xml = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        m2 = re.search(
            r'<Relationship\b[^>]*\bId="' + re.escape(rid) + r'"[^>]*\bTarget="([^"]+)"',
            rels_xml,
        )
        if not m2:
            return None
        t = m2.group(1)
        return t if t.startswith("xl/") else f"xl/{t}"


def _find_first_zero_row(sheet_xml: str, date_col: str, start_row: int) -> int:
    """
    Busca la primera fila desde start_row donde la celda de fecha tiene valor 0
    (o no existe = fila vacía). Retorna el número de fila o -1 si no encuentra.
    """
    for r in range(start_row, start_row + 300):
        ref = f"{date_col}{r}"
        val = _read_cell_numeric(sheet_xml, ref)
        if val is None or val == 0.0:
            return r
    return -1


# ─── Herramientas públicas ────────────────────────────────────────────────────

def actualizar_balance_input(
    nombre_archivo: str,
    fondo_key: str,
    año: int,
    mes: int,
    caja: float,
    activos_circ: float,
    otros_activos: float,
    pasivo_circ: float,
    pasivo_lp: float,
    interes_min: float,
    patrimonio: float,
) -> str:
    """
    Actualiza el balance trimestral en la hoja Input del fondo.
    Escribe en la fila 5: B5=fecha, C5=Caja, D5=Activos Circulantes,
    E5=Otros Activos, G5=Pasivo Circulante, H5=Pasivo LP,
    I5=Interés Minoritario, J5=Patrimonio.
    F5 contiene el Total Activos (fórmula, no se toca).

    Los valores deben estar en la misma moneda/unidad que usa la planilla (CLP).
    La fecha se calcula como el último día del mes indicado.
    """
    if fondo_key not in INPUT_CFG:
        return f"Error: fondo '{fondo_key}' no reconocido. Disponibles: {list(INPUT_CFG)}"

    filepath = _resolve_path(nombre_archivo)
    if not os.path.exists(filepath):
        return f"Error: no se encontró '{filepath}'."

    cfg = INPUT_CFG[fondo_key]
    sheet_path = _find_sheet_xml_path(filepath, cfg["sheet"])
    if not sheet_path:
        return f"Error: no se encontró la hoja '{cfg['sheet']}'."

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            sheet_xml = zf.read(sheet_path).decode("utf-8")

        row = cfg["balance_row"]
        fecha_serial = _excel_date(_last_day(año, mes))
        fecha_str = _last_day(año, mes).strftime("%d/%m/%Y")

        # B5=fecha, C5=Caja, D5=Act.Circ, E5=Otros, G5=Pas.Circ, H5=Pas.LP, I5=IM, J5=Pat
        cells = {
            f"B{row}": fecha_serial,
            f"C{row}": float(caja),
            f"D{row}": float(activos_circ),
            f"E{row}": float(otros_activos),
            f"G{row}": float(pasivo_circ),
            f"H{row}": float(pasivo_lp),
            f"I{row}": float(interes_min),
            f"J{row}": float(patrimonio),
        }
        for ref, val in cells.items():
            sheet_xml = _write_numeric_cell(sheet_xml, ref, val)

        _apply_to_xlsx(filepath, {sheet_path: sheet_xml})

        lines = [
            f"OK: balance actualizado en '{cfg['sheet']}' (fila {row}).",
            f"  B{row} = {fecha_str} (serial {fecha_serial})",
            f"  C{row} = {caja:,.0f}  (Caja)",
            f"  D{row} = {activos_circ:,.0f}  (Activos Circulantes)",
            f"  E{row} = {otros_activos:,.0f}  (Otros Activos)",
            f"  G{row} = {pasivo_circ:,.0f}  (Pasivo Circulante)",
            f"  H{row} = {pasivo_lp:,.0f}  (Pasivo LP)",
            f"  I{row} = {interes_min:,.0f}  (Interés Minoritario)",
            f"  J{row} = {patrimonio:,.0f}  (Patrimonio)",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error al actualizar balance: {e}"


def actualizar_fecha_bursatil_input(
    nombre_archivo: str,
    fondo_key: str,
    fecha_serial: int,
) -> str:
    """
    Actualiza la fecha bursátil en la hoja Input del fondo.
    Debe ser el último día del mes del CDG (el mes de la planilla, no el mes actual).
    Ej: CDG 2604 → 30/04/2026. CDG 2603 → 31/03/2026.

    Celdas: Input AP → D9 | Input PT → C11 | Input Ren → C10
    """
    return _actualizar_fecha_input(nombre_archivo, fondo_key, "bursatil", fecha_serial)


def actualizar_fecha_contable_input(
    nombre_archivo: str,
    fondo_key: str,
    fecha_serial: int,
) -> str:
    """
    Actualiza la fecha contable en la hoja Input del fondo.
    Se actualiza trimestralmente con el último día del trimestre del EEFF.

    Celdas: Input AP → C9 | Input PT → D11 | Input Ren → D10
    """
    return _actualizar_fecha_input(nombre_archivo, fondo_key, "contable", fecha_serial)


def _actualizar_fecha_input(
    nombre_archivo: str,
    fondo_key: str,
    tipo: str,
    fecha_serial: int,
) -> str:
    if fondo_key not in INPUT_CFG:
        return f"Error: fondo '{fondo_key}' no reconocido."

    filepath = _resolve_path(nombre_archivo)
    if not os.path.exists(filepath):
        return f"Error: no se encontró '{filepath}'."

    cfg = INPUT_CFG[fondo_key]
    cell_ref = cfg[f"fecha_{tipo}"]
    sheet_path = _find_sheet_xml_path(filepath, cfg["sheet"])
    if not sheet_path:
        return f"Error: no se encontró la hoja '{cfg['sheet']}'."

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            sheet_xml = zf.read(sheet_path).decode("utf-8")

        sheet_xml = _write_numeric_cell(sheet_xml, cell_ref, fecha_serial)
        _apply_to_xlsx(filepath, {sheet_path: sheet_xml})

        d = date(1899, 12, 30) + timedelta(days=fecha_serial)
        return (
            f"OK: fecha {tipo} actualizada en '{cfg['sheet']}'.\n"
            f"  {cell_ref} = {d.strftime('%d/%m/%Y')} (serial {fecha_serial})"
        )
    except Exception as e:
        return f"Error al actualizar fecha {tipo}: {e}"


def agregar_dividendo_input(
    nombre_archivo: str,
    fondo_key: str,
    año: int,
    mes: int,
    dia: int | None = None,
) -> str:
    """
    Agrega una nueva fecha en la tabla de dividendos de la hoja Input.
    Los montos se calculan automáticamente por las fórmulas de la planilla.

    Si 'dia' no se especifica, se usa el último día del mes.
    La tabla tiene filas pre-asignadas con fecha=0; se escribe en la primera vacía.

    Para que el cálculo de dividend yield sea correcto, la fecha debe ser
    la fecha exacta del pago del dividendo.
    """
    if fondo_key not in INPUT_CFG:
        return f"Error: fondo '{fondo_key}' no reconocido."

    filepath = _resolve_path(nombre_archivo)
    if not os.path.exists(filepath):
        return f"Error: no se encontró '{filepath}'."

    cfg = INPUT_CFG[fondo_key]
    sheet_path = _find_sheet_xml_path(filepath, cfg["sheet"])
    if not sheet_path:
        return f"Error: no se encontró la hoja '{cfg['sheet']}'."

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            sheet_xml = zf.read(sheet_path).decode("utf-8")

        # Calcular fecha
        if dia:
            fecha = date(año, mes, dia)
        else:
            fecha = _last_day(año, mes)
        fecha_serial = _excel_date(fecha)

        # Verificar que no exista ya esa fecha en la tabla
        start_row = cfg["div_start_row"]
        date_col = cfg["div_date_col"]
        for r in range(start_row, start_row + 300):
            val = _read_cell_numeric(sheet_xml, f"{date_col}{r}")
            if val is not None and abs(val - fecha_serial) < 1:
                return (
                    f"Aviso: la fecha {fecha.strftime('%d/%m/%Y')} ya existe en "
                    f"la tabla de dividendos (fila {r}). No se agregó duplicado."
                )

        # Encontrar primera fila vacía (fecha = 0 o ausente)
        target_row = _find_first_zero_row(sheet_xml, date_col, start_row)
        if target_row == -1:
            return (
                f"Error: no se encontró fila vacía en la tabla de dividendos "
                f"de '{cfg['sheet']}'. La tabla puede estar llena."
            )

        sheet_xml = _write_numeric_cell(sheet_xml, f"{date_col}{target_row}", fecha_serial)
        _apply_to_xlsx(filepath, {sheet_path: sheet_xml})

        return (
            f"OK: fecha dividendo agregada en '{cfg['sheet']}' fila {target_row}.\n"
            f"  {date_col}{target_row} = {fecha.strftime('%d/%m/%Y')} (serial {fecha_serial})\n"
            f"  Los montos se calcularán automáticamente al abrir en Excel."
        )
    except Exception as e:
        return f"Error al agregar dividendo: {e}"


def inspeccionar_dividendos_input(nombre_archivo: str, fondo_key: str) -> str:
    """
    Muestra las últimas 10 entradas y las primeras 5 filas vacías de la tabla
    de dividendos en la hoja Input del fondo.
    Útil para verificar qué dividendos hay registrados.
    """
    if fondo_key not in INPUT_CFG:
        return f"Error: fondo '{fondo_key}' no reconocido."

    filepath = _resolve_path(nombre_archivo)
    if not os.path.exists(filepath):
        return f"Error: no se encontró '{filepath}'."

    cfg = INPUT_CFG[fondo_key]
    sheet_path = _find_sheet_xml_path(filepath, cfg["sheet"])
    if not sheet_path:
        return f"Error: no se encontró la hoja '{cfg['sheet']}'."

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            sheet_xml = zf.read(sheet_path).decode("utf-8")

        start_row = cfg["div_start_row"]
        date_col = cfg["div_date_col"]

        lines = [f"Tabla dividendos '{cfg['sheet']}' (columna {date_col}, desde fila {start_row}):"]

        # Recopilar todas las entradas con fecha real
        entradas = []
        first_empty = None
        for r in range(start_row, start_row + 300):
            val = _read_cell_numeric(sheet_xml, f"{date_col}{r}")
            if val is not None and val > 0:
                d = date(1899, 12, 30) + timedelta(days=int(val))
                entradas.append((r, d))
            elif first_empty is None:
                first_empty = r

        if entradas:
            lines.append(f"  Total entradas con fecha: {len(entradas)}")
            lines.append("  Últimas 10:")
            for r, d in entradas[-10:]:
                lines.append(f"    Fila {r}: {d.strftime('%d/%m/%Y')}")
        else:
            lines.append("  No hay entradas con fecha.")

        if first_empty:
            lines.append(f"  Primera fila vacía disponible: {first_empty}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error al inspeccionar dividendos: {e}"
