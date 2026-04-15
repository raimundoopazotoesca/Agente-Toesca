"""
Herramientas para leer EEFF (Estados Financieros) de fondos en PDF.
Extrae valor cuota libro y dividendos/aportes para alimentar la planilla.

Estructura esperada en disco:
  FONDOS_DIR/<NombreFondo>/EEFF/<Año>/<FechaTrimestre>/VF/<YYYY EEFF NombreFondo>.pdf
"""
import os
import re
from config import FONDOS_DIR, LOCAL_FILES_DIR, SHAREPOINT_DIR

# Mapeo de clave SHEET_CFG → nombre de carpeta en disco
# Ajustar si los nombres reales difieren
FONDO_CARPETAS = {
    "A&R Apoquindo": "FI Toesca Rentas Apoquindo",
    "A&R PT":        "FI Toesca Rentas PT",
    "A&R Rentas":    "FI Toesca Rentas",
}

# Series por fondo (sincronizado con gestion_renta_tools.SHEET_CFG)
FONDO_SERIES = {
    "A&R Apoquindo": [None],
    "A&R PT":        [None],
    "A&R Rentas":    ["A", "C", "I"],
}


def _resolve_fondos_dir() -> str:
    if FONDOS_DIR:
        return FONDOS_DIR
    base = LOCAL_FILES_DIR or SHAREPOINT_DIR or ""
    return os.path.join(base, "Rentas", "Fondos")


def _parse_cl_number(s: str):
    """
    Convierte número chileno a float.
    "1.234,56" → 1234.56 | "1.234" → 1234.0 | "1234,56" → 1234.56
    """
    s = s.strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _find_trimestre_folder(ruta_año: str, mes: int):
    """
    Busca la carpeta del trimestre que corresponde al mes dado.
    Maneja los formatos reales encontrados en R:/Rentas/Fondos:
      - "1Q", "2Q", "3Q", "4Q"       (trimestre; Q1=mar, Q2=jun, Q3=sep, Q4=dic)
      - "2503", "2506", "2509"        (YYMM)
      - "2303 Marzo", "2306 Junio"    (YYMM + nombre)
      - "Marzo", "Junio", "Diciembre" (solo nombre)
      - "03-2025", "06-2025"          (MM-YYYY)
      - "31-03-2025", "2025-03-31"    (fecha completa)
    """
    if not os.path.isdir(ruta_año):
        return None

    mes_str = f"{mes:02d}"
    meses_es = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
    }
    # Mes → número de trimestre (solo para meses de cierre: 3,6,9,12)
    mes_a_q = {3: "1", 6: "2", 9: "3", 12: "4"}
    q_str = mes_a_q.get(mes, "")
    mes_nombre = meses_es.get(mes, "")

    carpetas = sorted(os.listdir(ruta_año))
    for c in carpetas:
        if not os.path.isdir(os.path.join(ruta_año, c)):
            continue
        c_lower = c.lower().strip()

        # Formato "1Q", "2Q", "3Q", "4Q"
        if q_str and c_lower == f"{q_str}q":
            return os.path.join(ruta_año, c)

        # Formato YYMM: "2503", "2506" — los últimos 2 dígitos son el mes
        if re.fullmatch(r"\d{4}", c) and c[2:] == mes_str:
            return os.path.join(ruta_año, c)

        # Formato "YYMM Nombre": "2303 Marzo", "2506 Junio"
        if re.match(r"\d{4}\s", c) and c[2:4] == mes_str:
            return os.path.join(ruta_año, c)

        # Formato numérico con mes embebido o nombre de mes
        if mes_str in c or mes_nombre in c_lower:
            return os.path.join(ruta_año, c)

    return None


def listar_eeff_disponibles(fondo_key: str, año: int) -> str:
    """
    Lista las carpetas de trimestre disponibles para un fondo y año.
    Útil para descubrir qué EEFF existen antes de leerlos.
    """
    fondos_dir = _resolve_fondos_dir()
    carpeta = FONDO_CARPETAS.get(fondo_key, fondo_key)
    ruta = os.path.join(fondos_dir, carpeta, "EEFF", str(año))

    if not os.path.isdir(fondos_dir):
        return f"Error: FONDOS_DIR no existe o no está configurado: {fondos_dir}"
    if not os.path.isdir(ruta):
        return (
            f"No se encontró la carpeta: {ruta}\n"
            f"Fondos disponibles en {fondos_dir}:\n"
            + "\n".join(f"  - {f}" for f in sorted(os.listdir(fondos_dir))
                        if os.path.isdir(os.path.join(fondos_dir, f)))
        )
    carpetas = sorted(os.listdir(ruta))
    if not carpetas:
        return f"No hay trimestres en {ruta}"
    return (
        f"Trimestres disponibles — {fondo_key} {año}:\n"
        + "\n".join(f"  - {c}" for c in carpetas)
    )


def buscar_pdf_eeff(fondo_key: str, año: int, mes: int) -> str:
    """
    Busca el PDF de EEFF para el fondo, año y mes de cierre del trimestre.
    Retorna la ruta absoluta al PDF si existe, o un mensaje de error.
    """
    fondos_dir = _resolve_fondos_dir()
    carpeta = FONDO_CARPETAS.get(fondo_key, fondo_key)
    ruta_año = os.path.join(fondos_dir, carpeta, "EEFF", str(año))

    trim_folder = _find_trimestre_folder(ruta_año, mes)
    if not trim_folder:
        disponibles = listar_eeff_disponibles(fondo_key, año)
        return f"Error: carpeta para mes {mes}/{año} no encontrada.\n{disponibles}"

    # Buscar subcarpeta VF (Version Final)
    vf_folder = None
    for nombre_vf in ["VF", "Vf", "vf", "Version Final", "Versión Final", "version final"]:
        candidate = os.path.join(trim_folder, nombre_vf)
        if os.path.isdir(candidate):
            vf_folder = candidate
            break
    if not vf_folder:
        # Si no hay VF, buscar PDFs directamente en la carpeta del trimestre
        vf_folder = trim_folder

    pdfs = [f for f in os.listdir(vf_folder) if f.lower().endswith(".pdf")]
    if not pdfs:
        return f"Error: no hay PDFs en {vf_folder}"

    # Priorizar PDFs con "EEFF" o "Estados" en el nombre
    eeff_pdfs = [f for f in pdfs if any(
        kw in f.upper() for kw in ["EEFF", "ESTADOS", "FINANCIERO"]
    )]
    target = eeff_pdfs[0] if eeff_pdfs else pdfs[0]
    return os.path.join(vf_folder, target)


def extraer_datos_eeff(pdf_path: str, fondo_key: str) -> dict:
    """
    Extrae del PDF:
      - valor_cuota: {serie_o_None: float}
      - dividendos:  [{serie, monto_por_cuota}]
      - aportes:     [{serie, monto_por_cuota}]
      - texto_relevante: str (páginas con datos clave, para lectura del agente)
      - error: str | None
    """
    result = {
        "valor_cuota": {},
        "dividendos": [],
        "aportes": [],
        "texto_relevante": "",
        "error": None,
    }
    try:
        import pdfplumber
    except ImportError:
        result["error"] = "pdfplumber no instalado. Ejecutar: pip install pdfplumber"
        return result

    series = FONDO_SERIES.get(fondo_key, [None])
    keywords = ["valor cuota", "cuota libro", "dividendo", "distribuci", "aporte",
                "activo neto", "patrimonio", "cuotas en circulaci"]

    try:
        with pdfplumber.open(pdf_path) as pdf:
            paginas_relevantes = []
            texto_completo = ""

            for i, page in enumerate(pdf.pages):
                texto = page.extract_text() or ""
                texto_completo += texto + "\n\n"
                texto_lower = texto.lower()
                if any(kw in texto_lower for kw in keywords):
                    paginas_relevantes.append(f"[Página {i + 1}]\n{texto}")

            result["texto_relevante"] = "\n\n---\n\n".join(paginas_relevantes[:6])

            # ── Extracción automática de valor cuota libro ──────────────────
            if series == [None]:
                # Fondo de serie única
                patrones = [
                    r"[Vv]alor\s+cuota\s+libro[^0-9$]*\$?\s*([\d\.,]+)",
                    r"[Vv]alor\s+de\s+la\s+cuota[^0-9$]*\$?\s*([\d\.,]+)",
                    r"[Vv]alor\s+cuota[^0-9$\n]{0,30}\$?\s*([\d\.,]+)",
                ]
                for pat in patrones:
                    m = re.search(pat, texto_completo)
                    if m:
                        val = _parse_cl_number(m.group(1))
                        if val and val > 100:
                            result["valor_cuota"][None] = val
                            break
            else:
                # Fondo multiserie: buscar por cada serie
                for serie in series:
                    patrones_serie = [
                        rf"[Ss]erie\s+{serie}\b[^0-9$\n]{{0,60}}\$?\s*([\d\.,]{{4,}})",
                        rf"[Cc]uota\s+[Ss]erie\s+{serie}[^0-9$\n]{{0,40}}\$?\s*([\d\.,]{{4,}})",
                        # En tablas: "A ... XXXX" o "Serie A | XXXX"
                        rf"\b{serie}\s*[\|\s]\s*([\d\.,]{{4,}})",
                    ]
                    for pat in patrones_serie:
                        m = re.search(pat, texto_completo)
                        if m:
                            val = _parse_cl_number(m.group(1))
                            if val and val > 100:
                                result["valor_cuota"][serie] = val
                                break

            # ── Extracción de dividendos ────────────────────────────────────
            patrones_div = [
                r"[Dd]ividendo[s]?\s+pagado[s]?[^0-9$\n]{0,40}\$?\s*([\d\.,]+)",
                r"[Dd]ividendo[s]?\s+por\s+cuota[^0-9$\n]{0,20}\$?\s*([\d\.,]+)",
                r"[Dd]istribuci[oó]n[^0-9$\n]{0,40}\$?\s*([\d\.,]+)",
            ]
            for pat in patrones_div:
                m = re.search(pat, texto_completo)
                if m:
                    val = _parse_cl_number(m.group(1))
                    if val:
                        result["dividendos"].append({"serie": None, "monto_por_cuota": val})
                        break

            # ── Extracción de aportes ───────────────────────────────────────
            patron_aporte = r"[Aa]porte[s]?\s+de\s+capital[^0-9$\n]{0,40}\$?\s*([\d\.,]+)"
            m = re.search(patron_aporte, texto_completo)
            if m:
                val = _parse_cl_number(m.group(1))
                if val:
                    result["aportes"].append({"serie": None, "monto_por_cuota": val})

    except Exception as e:
        result["error"] = str(e)

    return result


def leer_eeff(fondo_key: str, año: int, mes: int) -> str:
    """
    Función principal: busca el PDF, extrae valor cuota libro y dividendos/aportes.
    Retorna un resumen con los valores encontrados + texto relevante de las páginas
    clave del PDF para que el agente pueda leerlo y extraer valores si la
    extracción automática falla.
    """
    if fondo_key not in FONDO_CARPETAS:
        disponibles = ", ".join(FONDO_CARPETAS.keys())
        return f"Error: fondo '{fondo_key}' no reconocido. Disponibles: {disponibles}"

    pdf_path = buscar_pdf_eeff(fondo_key, año, mes)
    if not os.path.isfile(pdf_path):
        return pdf_path  # mensaje de error

    datos = extraer_datos_eeff(pdf_path, fondo_key)

    lines = [
        f"EEFF {fondo_key} — trimestre {mes}/{año}",
        f"Archivo: {os.path.basename(pdf_path)}",
        "",
    ]

    if datos["error"]:
        lines.append(f"[!] Error al leer PDF: {datos['error']}")

    # Valor cuota libro
    if datos["valor_cuota"]:
        lines.append("Valor cuota libro (extracción automática):")
        for serie, val in datos["valor_cuota"].items():
            label = f"Serie {serie}" if serie else "Único"
            lines.append(f"  {label}: ${val:,.2f}")
    else:
        lines.append("Valor cuota libro: no encontrado automáticamente.")
        lines.append("  → Revisar texto de páginas relevantes más abajo.")

    # Dividendos
    if datos["dividendos"]:
        lines.append("\nDividendos por cuota:")
        for d in datos["dividendos"]:
            label = f"Serie {d['serie']}" if d["serie"] else "Fondo"
            lines.append(f"  {label}: ${d['monto_por_cuota']:,.2f}")
    else:
        lines.append("Dividendos: ninguno detectado automáticamente.")

    # Aportes
    if datos["aportes"]:
        lines.append("\nAportes de capital:")
        for a in datos["aportes"]:
            label = f"Serie {a['serie']}" if a["serie"] else "Fondo"
            lines.append(f"  {label}: ${a['monto_por_cuota']:,.2f}")

    # Texto relevante para lectura del agente
    if datos["texto_relevante"]:
        lines.append("\n" + "─" * 50)
        lines.append("Páginas relevantes del PDF:")
        lines.append("─" * 50)
        lines.append(datos["texto_relevante"][:4000])

    return "\n".join(lines)
