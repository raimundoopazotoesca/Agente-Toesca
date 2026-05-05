"""
Herramientas para actualizar el Balance Consolidado Rentas PT.

Entidades: Toesca Rentas PT (holding) + Inmobiliaria Boulevard + Torre A S.A.
Planilla: {MM.YYYY}- Balance Consolidado Rentas PT vF.xlsx
Resultado: {MM.YYYY}- Balance Consolidado Rentas PT vAgente.xlsx

Fuentes por hoja:
  Fondo PT    → EEFF PDF (M$ × 1000)
  Inmob Blvd  → balance EEFF PDF (M$ × 1000) + EERR Análisis xlsx (pesos)
  Torre A     → balance + EERR Análisis xlsx (pesos directos)
"""
import glob as glob_module
import os
import re
import shutil
from calendar import monthrange
from datetime import date, datetime

import openpyxl
from config import SHAREPOINT_DIR, WORK_DIR

# ─── Rutas base ────────────────────────────────────────────────────────────────

BALANCES_DIR = os.path.join(
    SHAREPOINT_DIR, "Controles de Gestión", "Renta Comercial", "Balances Consolidados"
)
TRI_EEFF_DIR = os.path.join(
    SHAREPOINT_DIR, "Fondo Rentas Inmobiliarias TRI", "EEFF"
)
PT_EEFF_DIR = os.path.join(SHAREPOINT_DIR, "Fondo Rentas PT", "EEFF")

HOJAS_INPUT = ["Fondo PT", "Inmob Boulevard", "Torre A"]

# ─── Helpers de rutas ─────────────────────────────────────────────────────────

def _quarter_end(mes: int, año: int) -> date:
    return date(año, mes, monthrange(año, mes)[1])


def _mes_a_q(mes: int) -> int:
    return {3: 1, 6: 2, 9: 3, 12: 4}[mes]


def _find_quarter_folder(parent: str, mes: int) -> str | None:
    q = _mes_a_q(mes)
    if not os.path.isdir(parent):
        return None
    for e in os.listdir(parent):
        full = os.path.join(parent, e)
        if os.path.isdir(full) and e.lower().strip() in (f"{q}t", f"{q}q"):
            return full
    return None


def _find_latest_vf(año: int, mes: int) -> str | None:
    """Encuentra el archivo vF más reciente para el año dado."""
    año_dir = os.path.join(BALANCES_DIR, str(año))
    q_dir = _find_quarter_folder(año_dir, mes)
    if q_dir:
        for f in os.listdir(q_dir):
            if "Balance Consolidado Rentas PT" in f and "vF" in f and f.endswith(".xlsx"):
                return os.path.join(q_dir, f)
    # búsqueda exhaustiva
    pattern = os.path.join(BALANCES_DIR, "**", "*Balance Consolidado Rentas PT*vF*.xlsx")
    matches = glob_module.glob(pattern, recursive=True)
    return max(matches, key=os.path.getmtime) if matches else None


def _find_eeff_fondo_pt(mes: int, año: int) -> str | None:
    año_dir = os.path.join(PT_EEFF_DIR, str(año))
    q_dir = _find_quarter_folder(año_dir, mes)
    if q_dir:
        for f in os.listdir(q_dir):
            if f.lower().endswith(".pdf") and "rentas pt" in f.lower():
                return os.path.join(q_dir, f)
    pattern = os.path.join(PT_EEFF_DIR, "**", f"*{año}{mes:02d}*PT*.pdf")
    matches = glob_module.glob(pattern, recursive=True)
    return matches[0] if matches else None


def _find_boulevard_files(mes: int, año: int) -> tuple[str | None, str | None]:
    bvd_dir = os.path.join(TRI_EEFF_DIR, "Boulevard")
    eeff_pdf = analisis_xlsx = None
    if os.path.isdir(bvd_dir):
        for f in os.listdir(bvd_dir):
            fp = os.path.join(bvd_dir, f)
            if not os.path.isfile(fp):
                continue
            fl = f.lower()
            if fl.endswith(".pdf") and "boulevard" in fl:
                eeff_pdf = fp
            elif fl.endswith(".xlsx") and "boulevard" in fl and "análisis" in fl.lower():
                analisis_xlsx = fp
        # segundo intento sin tilde
        if analisis_xlsx is None:
            for f in os.listdir(bvd_dir):
                fp = os.path.join(bvd_dir, f)
                if f.lower().endswith(".xlsx") and "boulevard" in f.lower():
                    analisis_xlsx = fp
    return eeff_pdf, analisis_xlsx


def _find_torre_a_file(mes: int, año: int) -> str | None:
    ta_dir = os.path.join(TRI_EEFF_DIR, "Torre A")
    if os.path.isdir(ta_dir):
        for f in os.listdir(ta_dir):
            fp = os.path.join(ta_dir, f)
            if f.lower().endswith(".xlsx") and "torre a" in f.lower():
                return fp
    return None

# ─── PDF parsing ──────────────────────────────────────────────────────────────

def _collect_page_values(page_text: str) -> list:
    """Extrae tokens de valor de una página EEFF (en M$).
    Retorna lista de enteros o None (para '-').
    """
    values = []
    for line in page_text.split("\n"):
        s = line.strip()
        if s == "-":
            values.append(None)
        elif re.fullmatch(r"\(\d{1,3}(\.\d{3})*\)", s):
            values.append(-int(s[1:-1].replace(".", "")))
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            values.append(int(s.replace(".", "")))
    return values


def _parse_eeff_fondo_pt_pdf(pdf_path: str) -> dict:
    """
    Parsea EEFF Fondo PT PDF. Retorna dict de cuenta → valor en PESOS (M$ × 1000).
    Claves: "efectivo", "cxc_op", "af_costo_nc", "cxc_op_nc", "inv_met_part",
            "prop_inv", "cxp_op_pc", "remu_soc_admin", "cxp_er_pc", "prest_nc",
            "cxp_er_nc", "otros_pasivos_nc", "res_acum", "res_ej",
            "aportes", "div_provisorios",
            "intereses", "res_inv_met_part", "remu_cv", "comision_adm",
            "honor_custodia", "otros_gastos", "costos_finan", "impuesto_ext",
    más claves de validación: "total_activo", "total_pc", "total_pnc", "total_pat"
    """
    from markitdown import MarkItDown
    md = MarkItDown()
    text = md.convert(pdf_path).text_content
    pages = text.split("\x0c")

    result = {}

    # ── Página 5: ACTIVOS (19 items) ─────────────────────────────────────────
    p5 = _collect_page_values(pages[5])
    # Posiciones 0-indexed para período 2025:
    # 0=Efectivo, 5=CxC_op_cc, 11=AF_costo_nc, 12=CxC_op_nc, 14=Inv_met_part,
    # 15=Prop_inv, 17=Total_ANC, 18=Total_activo
    if len(p5) >= 19:
        def _m(v):
            return v * 1000 if v is not None else 0
        result["efectivo"]     = _m(p5[0])
        result["cxc_op"]       = _m(p5[5])
        result["af_costo_nc"]  = _m(p5[11])
        result["cxc_op_nc"]    = _m(p5[12])
        result["inv_met_part"] = _m(p5[14])
        result["prop_inv"]     = _m(p5[15])
        result["total_activo"] = _m(p5[18])

    # ── Página 6: PASIVOS + PATRIMONIO (23 items) ─────────────────────────────
    p6 = _collect_page_values(pages[6])
    # PC(9): PF_VR, Prest, Otros_PF, CxP_op, Remu, OtrosDoc_CxP, Ing_ant, Otros, Total
    # PNC(7): Prest, OtrosPF, CxP_op, OtrosDoc_CxP, Ing_ant, OtrosPasivos, Total
    # PAT+total(7): Aportes, Otras_res, Res_acum, Res_ej, Div_prov, Total_pat, Total_P+P
    if len(p6) >= 23:
        def _m(v):
            return v * 1000 if v is not None else 0
        result["cxp_op_pc"]        = _m(p6[3])
        result["remu_soc_admin"]   = _m(p6[4])
        result["cxp_er_pc"]        = _m(p6[5])
        result["total_pc"]         = _m(p6[8])
        result["prest_nc"]         = _m(p6[9])
        result["cxp_er_nc"]        = _m(p6[12])
        result["otros_pasivos_nc"] = _m(p6[14])
        result["total_pnc"]        = _m(p6[15])
        # Aportes y Div: NO usar valores de p6 — usar página 8 (Estado Cambios)
        res_acum_raw               = p6[18]
        result["res_acum"]         = _m(res_acum_raw)
        result["res_ej"]           = _m(p6[19])
        result["total_pat"]        = _m(p6[21])

    # ── Página 7: EERR (interleaved: pos[0]=Intereses2025, pos[1]=Intereses2024) ──
    p7 = _collect_page_values(pages[7])
    # Intereses está en pos[0]; el resto de 2025 empieza en pos[2]
    # Posición mapeada (0-indexed relativo a items EERR, excluyendo interleaved):
    # EERR 2025: Intereses=pos0, luego items2-30 en pos2..30
    # Mapa: item_pos → planilla_key
    EERR_MAP = {
        0:  "intereses",          # Intereses y reajustes (pos 0 = especial)
        # pos 1 = Intereses 2024, skip
        10: "res_inv_met_part",   # Resultado inversiones método participación
        14: "remu_cv",            # Remuneración Comité Vigilancia
        15: "comision_adm",       # Comisión de administración
        16: "honor_custodia",     # Honorarios custodia
        18: "otros_gastos",       # Otros gastos de operación
        21: "costos_finan",       # Costos financieros
        23: "impuesto_ext",       # Impuesto ganancias exterior
    }
    for pos, key in EERR_MAP.items():
        if len(p7) > pos:
            v = p7[pos]
            result[key] = (v * 1000 if v is not None else 0)

    # ── Página 8: ESTADO DE CAMBIOS EN PATRIMONIO ─────────────────────────────
    # Valores de la columna Aportes: [saldo_inicio, -, subtotal, -, repartos, ...]
    p8 = _collect_page_values(pages[8])
    # Primer valor positivo = saldo inicio Aportes → row 62
    # Primer valor negativo = Repartos de patrimonio → row 66
    aportes_val = next((v for v in p8 if v is not None and v > 0), None)
    repartos_val = next((v for v in p8 if v is not None and v < 0), None)
    if aportes_val is not None:
        result["aportes"] = aportes_val * 1000
    if repartos_val is not None:
        result["div_provisorios"] = repartos_val * 1000

    return result


def _parse_eeff_boulevard_pdf(pdf_path: str) -> dict:
    """
    Parsea EEFF Boulevard PDF. Retorna dict de cuenta → valor en PESOS (M$ × 1000).
    """
    from markitdown import MarkItDown
    md = MarkItDown()
    text = md.convert(pdf_path).text_content
    pages = text.split("\x0c")

    result = {}

    # ── Página 5: ACTIVOS (9 items) ───────────────────────────────────────────
    # 0=Efectivo, 1=Deudores_CxC, 2=CxC_er_corr, 3=TotalAC,
    # 4=Otras_CxC_NC, 5=Prop_inv, 6=Act_imp_dif, 7=TotalANC, 8=TotalActivos
    p5 = _collect_page_values(pages[5])
    if len(p5) >= 9:
        def _m(v):
            return v * 1000 if v is not None else 0
        result["efectivo"]      = _m(p5[0])
        result["cxc_op"]        = _m(p5[1])
        result["cxc_er_pc"]     = _m(p5[2])
        result["otras_cxc_nc"]  = _m(p5[4])
        result["prop_inv"]      = _m(p5[5])
        result["act_imp_dif"]   = _m(p5[6])
        result["total_activo"]  = _m(p5[8])

    # ── Página 6: PASIVOS + PATRIMONIO (14 items) ────────────────────────────
    # PC(5): OtrosPF_corr, CxP_comercial, CxP_er_corr, Otras_prov, TotalPC
    # PNC(4): OtrosPF_nc, CxP_er_nc, TotalPNC, TotalPasivos
    # PAT(5): Capital, ResAcum, ResultEj, TotalPat, TotalP+P
    p6 = _collect_page_values(pages[6])
    if len(p6) >= 14:
        def _m(v):
            return v * 1000 if v is not None else 0
        result["prest_corr"]    = _m(p6[0])
        result["cxp_op_pc"]     = _m(p6[1])
        result["cxp_er_pc"]     = _m(p6[2])
        result["otras_prov_corr"] = _m(p6[3])
        result["total_pc"]      = _m(p6[4])
        result["prest_nc"]      = _m(p6[5])
        result["cxp_er_nc"]     = _m(p6[6])
        result["total_pnc"]     = _m(p6[7])
        result["capital"]       = _m(p6[9])
        result["res_acum"]      = _m(p6[10])
        result["res_ej"]        = _m(p6[11])
        result["total_pat"]     = _m(p6[12])
        result["total_pasivo_y_pat"] = _m(p6[13])

    return result

# ─── Análisis xlsx: Boulevard EERR ────────────────────────────────────────────

def _read_analisis_eerr(xlsx_path: str, sheet_name: str = "EERR") -> dict:
    """
    Lee la hoja EERR de un Análisis xlsx.
    Retorna dict: label_normalizado → valor (pesos directo).
    El label es col C (o col D según hoja), el valor es la columna D (col 4).
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return {}
    ws = wb[sheet_name]
    result = {}
    for row in ws.iter_rows(values_only=True):
        # Label está en col C (índice 2), valor en col D (índice 3)
        label = row[2] if len(row) > 2 else None
        val   = row[3] if len(row) > 3 else None
        if label and isinstance(label, str) and label.strip() and val is not None:
            key = _norm_label(label)
            result[key] = val
    wb.close()
    return result


def _read_torre_a_balance(xlsx_path: str) -> dict:
    """
    Lee Estado de Situacion de Torre A (cols B=label, C=valor, I=pasivo_label, J=pasivo_val).
    Retorna dict: label_normalizado → valor (pesos).
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Estado de Situacion"]
    result = {}
    for row in ws.iter_rows(values_only=True):
        # Activos: col B (1), val col C (2)
        if len(row) > 2:
            label_a = row[1]
            val_a   = row[2]
            if label_a and isinstance(label_a, str) and label_a.strip() and val_a is not None:
                result[_norm_label(label_a)] = val_a
        # Pasivos: col I (8), val col J (9)
        if len(row) > 9:
            label_p = row[8]
            val_p   = row[9]
            if label_p and isinstance(label_p, str) and label_p.strip() and val_p is not None:
                result[_norm_label(label_p)] = val_p
    wb.close()
    return result


def _norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

# ─── Column shift ─────────────────────────────────────────────────────────────

def _shift_input_sheets(wb_vals, wb_forms):
    """
    En cada hoja de input (Fondo PT, Inmob Boulevard, Torre A):
    copia valores D→E, E→F, ..., J→K. Limpia celdas valor en D.
    Las fórmulas en D se mantienen (recalculan con nuevos datos).
    wb_vals: workbook data_only=True (valores cacheados)
    wb_forms: workbook data_only=False (modificable)
    """
    D_COL, K_COL = 4, 11

    for sheet_name in HOJAS_INPUT:
        ws_v = wb_vals[sheet_name]
        ws_f = wb_forms[sheet_name]

        # Determinar máxima fila con datos
        max_row = max(
            (cell.row for row in ws_v.iter_rows() for cell in row if cell.value is not None),
            default=120
        )
        max_row = max(max_row, 120)

        for r in range(2, max_row + 1):
            # Leer fila completa de vals y formulas (cols D=4..K=11)
            vals = [ws_v.cell(row=r, column=c).value for c in range(D_COL, K_COL + 1)]
            forms = [ws_f.cell(row=r, column=c).value for c in range(D_COL, K_COL + 1)]

            # Detectar celdas con fórmulas en col D
            d_is_formula = isinstance(forms[0], str) and forms[0].startswith("=")

            # Shift right: para col K..E (descendiendo), copiar valor del anterior
            for dst in range(K_COL, D_COL, -1):  # 11 → 5
                src_idx = (dst - 1) - D_COL  # índice relativo al array (0-based)
                src_val = vals[src_idx]
                ws_f.cell(row=r, column=dst).value = src_val

            # Col D: si era fórmula → dejar (recalcula), si era valor → limpiar
            if not d_is_formula:
                ws_f.cell(row=r, column=D_COL).value = None

# ─── Fill functions ───────────────────────────────────────────────────────────

def _fill_fondo_pt(ws, d: dict):
    """Escribe valores de la hoja Fondo PT en col D según mapeo de wiki."""
    COL = 4  # D

    def _w(row, val):
        if val is not None and val != 0:
            ws.cell(row=row, column=COL).value = val
        else:
            ws.cell(row=row, column=COL).value = None

    # Balance
    _w(7,  d.get("efectivo"))
    _w(12, d.get("cxc_op"))
    _w(22, d.get("af_costo_nc"))
    _w(24, d.get("cxc_op_nc"))
    _w(25, d.get("inv_met_part"))
    _w(27, d.get("prop_inv"))
    _w(42, d.get("cxp_op_pc"))
    _w(43, d.get("remu_soc_admin"))
    _w(44, d.get("cxp_er_pc"))
    _w(52, d.get("prest_nc"))
    _w(55, d.get("cxp_er_nc"))
    _w(57, d.get("otros_pasivos_nc"))
    _w(62, d.get("aportes"))
    _w(64, d.get("res_acum"))
    _w(65, d.get("res_ej"))
    _w(66, d.get("div_provisorios"))

    # EERR
    _w(76, d.get("intereses"))
    _w(85, d.get("res_inv_met_part"))
    _w(91, d.get("remu_cv"))
    _w(92, d.get("comision_adm"))
    _w(93, d.get("honor_custodia"))
    _w(95, d.get("otros_gastos"))
    _w(99, d.get("costos_finan"))
    _w(101, d.get("impuesto_ext"))


def _fill_boulevard(ws, balance_d: dict, eerr_d: dict, planilla_eerr_map: dict):
    """Escribe Inmob Boulevard col D: balance desde EEFF PDF, EERR desde Análisis."""
    COL = 4

    def _w(row, val):
        ws.cell(row=row, column=COL).value = val if val else None

    # Balance (en pesos = M$ × 1000)
    _w(7,  balance_d.get("efectivo"))
    _w(12, balance_d.get("cxc_op"))
    _w(13, balance_d.get("cxc_er_pc"))
    _w(23, balance_d.get("otras_cxc_nc"))
    _w(27, balance_d.get("prop_inv"))
    _w(31, balance_d.get("act_imp_dif"))
    _w(40, balance_d.get("prest_corr"))
    _w(42, balance_d.get("cxp_op_pc"))
    _w(44, balance_d.get("cxp_er_pc"))
    _w(46, balance_d.get("otras_prov_corr"))
    _w(52, balance_d.get("prest_nc"))
    _w(55, balance_d.get("cxp_er_nc"))
    _w(62, balance_d.get("capital"))
    _w(64, balance_d.get("res_acum"))
    _w(65, balance_d.get("res_ej"))

    # EERR: buscar por código de cuenta en planilla_eerr_map
    for row_num, label_raw in planilla_eerr_map.items():
        key = _norm_label(label_raw)
        val = eerr_d.get(key)
        if val is not None:
            ws.cell(row=row_num, column=COL).value = val


def _fill_torre_a(ws, balance_d: dict, eerr_d: dict, planilla_eerr_map: dict):
    """Escribe Torre A col D: balance y EERR desde Análisis xlsx (pesos directos)."""
    COL = 4

    def _lookup(norm_keys):
        for k in norm_keys:
            v = balance_d.get(_norm_label(k))
            if v is not None:
                return v
        return None

    def _w(row, val):
        ws.cell(row=row, column=COL).value = val if val else None

    # Balance (pesos directos)
    _w(7,  _lookup(["EFECTIVO Y EQUIVALENTE AL EFECTIVO"]))
    # CxC operaciones = CLIENTE - PROVISION
    cliente   = balance_d.get(_norm_label("1-1-02-07  CLIENTE"), 0) or 0
    provision = balance_d.get(_norm_label("1-1-02-14  PROVISION POR INCOBRABLES"), 0) or 0
    cxc_net = (cliente + provision)
    _w(12, cxc_net if cxc_net else None)
    _w(13, _lookup(["1-1-02-15  PRESTAMO POR COBRAR INMOB. BOULEVARD PT"]))
    _w(24, _lookup(["CUENTAS POR COBRAR EMPRESAS RELACIONADAS"]))
    _w(27, _lookup(["PROPIEDADES DE INVERSION"]))
    _w(31, _lookup(["ACTIVO POR IMPUESTO DIFERIDO"]))
    # Pasivos corrientes
    _w(42, _lookup(["CUENTAS POR PAGAR COMERCIALES Y OTRAS CUENTAS POR PAGAR"]))
    _w(46, _lookup(["OTRAS PROVISIONES A CORTO PLAZO"]))
    _w(48, _lookup(["PASIVO POR IMPUESTOS CORRIENTES"]))
    # Préstamos NC: col K (índice 10) de Estado Situacion row 42
    _w(52, _lookup(["2-1-03-02  PRESTAMOS BANCARIOS TRAMO A"]))  # ver nota
    _w(56, _lookup(["PASIVO POR IMPUESTO DIFERIDO"]))
    # Patrimonio
    _w(62, _lookup(["3-1-01-01  CAPITAL EMITIDO"]))
    _w(64, _lookup(["3-1-03-01  RESULTADOS ACUMULADOS EJERCICIOS ANTERIORES"]))
    _w(65, _lookup(["RESULTADO DEL PERIODO"]))

    # EERR por código de cuenta
    for row_num, label_raw in planilla_eerr_map.items():
        key = _norm_label(label_raw)
        val = eerr_d.get(key)
        if val is not None:
            ws.cell(row=row_num, column=COL).value = val

# ─── Leer mapa de EERR desde planilla (filas no-fórmula) ─────────────────────

def _get_eerr_row_map(wb_forms, sheet_name: str) -> dict:
    """
    Retorna {row_num: label} para filas de EERR (col D no tiene fórmula ni es header).
    """
    ws = wb_forms[sheet_name]
    result = {}
    for r in range(73, 125):
        cell_b = ws.cell(row=r, column=2).value
        cell_d = ws.cell(row=r, column=4).value
        # Incluir si hay label en B, y D no es fórmula
        if cell_b and isinstance(cell_b, str):
            is_formula_d = isinstance(cell_d, str) and cell_d.startswith("=")
            is_section_header = cell_d is None and not re.search(r"\d", cell_b)
            if not is_formula_d and not is_section_header and re.search(r"\d", cell_b):
                result[r] = cell_b.strip()
    return result

# ─── Validación ───────────────────────────────────────────────────────────────

def _validate_sheet(ws_vals, sheet_name: str) -> list[str]:
    """
    Verifica cuadre: Total Activos == Pasivos + Patrimonio.
    Retorna lista de mensajes.
    """
    COL = 4

    def _v(row):
        return ws_vals.cell(row=row, column=COL).value or 0

    msgs = []
    if sheet_name == "Fondo PT":
        total_a  = _v(35)
        total_pp = _v(70)
        res_ej_balance = _v(65)
        res_ej_eerr    = _v(103)
        if total_a and abs(total_a - total_pp) > 1000:
            msgs.append(f"  ⚠ Activos ({total_a:,.0f}) ≠ Pasivos+Pat ({total_pp:,.0f})")
        if res_ej_balance and res_ej_eerr and abs(res_ej_balance - res_ej_eerr) > 1000:
            msgs.append(f"  ⚠ Resultado balance ({res_ej_balance:,.0f}) ≠ EERR ({res_ej_eerr:,.0f})")
    elif sheet_name == "Inmob Boulevard":
        total_a  = _v(35)
        total_pp = _v(70)
        if total_a and abs(total_a - total_pp) > 1000:
            msgs.append(f"  ⚠ Activos ({total_a:,.0f}) ≠ Pasivos+Pat ({total_pp:,.0f})")
    elif sheet_name == "Torre A":
        total_a  = _v(35)
        total_pp = _v(70)
        if total_a and abs(total_a - total_pp) > 1000:
            msgs.append(f"  ⚠ Activos ({total_a:,.0f}) ≠ Pasivos+Pat ({total_pp:,.0f})")
    return msgs

# ─── Función principal ────────────────────────────────────────────────────────

def actualizar_balance_consolidado_pt(mes: int, año: int) -> str:
    """
    Actualiza el Balance Consolidado Rentas PT para el período dado.

    Pasos:
      1. Busca el último archivo vF y crea copia vAgente
      2. Desplaza columnas D-K (shift right) en las 3 hojas input
      3. Escribe la fecha del período en row 2 col D
      4. Rellena Fondo PT desde EEFF PDF
      5. Rellena Inmob Boulevard desde EEFF PDF (balance) + Análisis xlsx (EERR)
      6. Rellena Torre A desde Análisis xlsx
      7. Valida cuadres y retorna informe
    """
    if mes not in (3, 6, 9, 12):
        return f"Error: mes={mes} no es fin de trimestre (usar 3, 6, 9 o 12)"

    lines = [f"=== Balance Consolidado PT {mes:02d}.{año} ===", ""]

    # 1. Encontrar vF más reciente
    vf_path = _find_latest_vf(año, mes)
    if not vf_path:
        # Buscar en cualquier año disponible
        for y in sorted(os.listdir(BALANCES_DIR), reverse=True):
            ydir = os.path.join(BALANCES_DIR, y)
            if os.path.isdir(ydir):
                vf_path = _find_latest_vf(int(y) if y.isdigit() else año, mes)
                if vf_path:
                    break
    if not vf_path:
        return "Error: no se encontró ningún archivo vF de Balance Consolidado Rentas PT"

    lines.append(f"Fuente vF: {os.path.basename(vf_path)}")

    # 2. Crear archivo vAgente
    mm_yyyy = f"{mes:02d}.{año}"
    dest_name = f"{mm_yyyy}- Balance Consolidado Rentas PT vAgente.xlsx"
    dest_dir = os.path.dirname(vf_path)
    dest_path = os.path.join(dest_dir, dest_name)
    shutil.copy2(vf_path, dest_path)
    lines.append(f"Archivo destino: {dest_name}")
    lines.append("")

    # 3. Cargar workbooks (data_only=True para valores, data_only=False para fórmulas)
    wb_vals  = openpyxl.load_workbook(dest_path, data_only=True)
    wb_forms = openpyxl.load_workbook(dest_path, data_only=False)

    # 4. Shift D-K en hojas input
    _shift_input_sheets(wb_vals, wb_forms)

    # 5. Fecha del período (último día del trimestre)
    fecha_periodo = _quarter_end(mes, año)
    fecha_dt = datetime(fecha_periodo.year, fecha_periodo.month, fecha_periodo.day)
    for hn in HOJAS_INPUT:
        wb_forms[hn].cell(row=2, column=4).value = fecha_dt
    lines.append(f"Fecha período: {fecha_periodo}")
    lines.append("")

    # ── EEFF Fondo PT ─────────────────────────────────────────────────────────
    pdf_pt = _find_eeff_fondo_pt(mes, año)
    if pdf_pt:
        lines.append(f"EEFF Fondo PT: {os.path.basename(pdf_pt)}")
        try:
            fondo_pt_d = _parse_eeff_fondo_pt_pdf(pdf_pt)
            _fill_fondo_pt(wb_forms["Fondo PT"], fondo_pt_d)
            lines.append(f"  Efectivo: {fondo_pt_d.get('efectivo', 0):,.0f}")
            lines.append(f"  Inv. método participación: {fondo_pt_d.get('inv_met_part', 0):,.0f}")
            lines.append(f"  Total Activo: {fondo_pt_d.get('total_activo', 0):,.0f}")
            lines.append(f"  Aportes (bruto): {fondo_pt_d.get('aportes', 0):,.0f}")
            lines.append(f"  Resultado ejercicio: {fondo_pt_d.get('res_ej', 0):,.0f}")
        except Exception as e:
            lines.append(f"  ⚠ Error parseo PDF PT: {e}")
    else:
        lines.append("⚠ No se encontró EEFF PDF Fondo PT — hoja Fondo PT no actualizada")
    lines.append("")

    # ── Boulevard EEFF PDF (balance) + Análisis xlsx (EERR) ───────────────────
    eeff_bvd, analisis_bvd = _find_boulevard_files(mes, año)
    eerr_bvd_map = _get_eerr_row_map(wb_forms, "Inmob Boulevard")

    if eeff_bvd:
        lines.append(f"EEFF Boulevard: {os.path.basename(eeff_bvd)}")
        try:
            bvd_balance = _parse_eeff_boulevard_pdf(eeff_bvd)
            lines.append(f"  Efectivo: {bvd_balance.get('efectivo', 0):,.0f}")
            lines.append(f"  Prop. Inversión: {bvd_balance.get('prop_inv', 0):,.0f}")
            lines.append(f"  Total Activo: {bvd_balance.get('total_activo', 0):,.0f}")
        except Exception as e:
            bvd_balance = {}
            lines.append(f"  ⚠ Error parseo PDF Boulevard: {e}")
    else:
        bvd_balance = {}
        lines.append("⚠ No se encontró EEFF PDF Boulevard — balance no actualizado")

    if analisis_bvd:
        lines.append(f"Análisis Boulevard: {os.path.basename(analisis_bvd)}")
        try:
            eerr_bvd = _read_analisis_eerr(analisis_bvd, "EERR")
            lines.append(f"  Cuentas EERR leídas: {len(eerr_bvd)}")
        except Exception as e:
            eerr_bvd = {}
            lines.append(f"  ⚠ Error Análisis Boulevard: {e}")
    else:
        eerr_bvd = {}
        lines.append("⚠ No se encontró Análisis Boulevard — EERR no actualizado")

    if bvd_balance or eerr_bvd:
        _fill_boulevard(wb_forms["Inmob Boulevard"], bvd_balance, eerr_bvd, eerr_bvd_map)
    lines.append("")

    # ── Torre A: Análisis xlsx ─────────────────────────────────────────────────
    analisis_ta = _find_torre_a_file(mes, año)
    eerr_ta_map = _get_eerr_row_map(wb_forms, "Torre A")

    if analisis_ta:
        lines.append(f"Análisis Torre A: {os.path.basename(analisis_ta)}")
        try:
            ta_balance = _read_torre_a_balance(analisis_ta)
            eerr_ta = _read_analisis_eerr(analisis_ta, "EERR")
            _fill_torre_a(wb_forms["Torre A"], ta_balance, eerr_ta, eerr_ta_map)
            # Buscar valores claves para verificar
            efectivo_ta = ta_balance.get(_norm_label("EFECTIVO Y EQUIVALENTE AL EFECTIVO"))
            lines.append(f"  Efectivo: {efectivo_ta:,.0f}" if efectivo_ta else "  Efectivo: no encontrado")
            prop_ta = ta_balance.get(_norm_label("PROPIEDADES DE INVERSION"))
            lines.append(f"  Prop. Inversión: {prop_ta:,.0f}" if prop_ta else "  Prop. Inversión: no encontrado")
        except Exception as e:
            lines.append(f"  ⚠ Error Análisis Torre A: {e}")
    else:
        lines.append("⚠ No se encontró Análisis Torre A — hoja no actualizada")
    lines.append("")

    # ── Validar en memoria (antes de guardar) ─────────────────────────────────
    lines.append("=== Validaciones (en memoria) ===")
    # Para validar, leer los valores escritos directo de wb_forms (formulas no calculadas)
    # Solo verificar que hay valores en celdas clave
    for hn in HOJAS_INPUT:
        ws_f = wb_forms[hn]
        fecha = ws_f.cell(row=2, column=4).value
        val_key = ws_f.cell(row=7, column=4).value  # Efectivo
        if fecha and val_key is not None:
            lines.append(f"  {hn}: fecha={fecha.strftime('%d/%m/%Y') if hasattr(fecha, 'strftime') else fecha}, efectivo={val_key:,.0f}")
        else:
            lines.append(f"  {hn}: {'' if fecha else 'sin fecha'}{'' if val_key is not None else ', sin efectivo'}")

    # ── Guardar ────────────────────────────────────────────────────────────────
    wb_forms.save(dest_path)
    wb_forms.close()
    wb_vals.close()
    lines.append("")
    lines.append(f"Archivo guardado en: {dest_path}")
    lines.append("Abrir en Excel y verificar que las formulas recalculen correctamente.")

    return "\n".join(lines)
