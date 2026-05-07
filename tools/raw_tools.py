"""
Herramientas para organización de SharePoint:
- ordenar_archivos_raw(): clasifica archivos en RAW/ al destino correcto
- reemplazar_en_tool(): find-replace en archivos de código del agente
- reemplazar_en_wiki(): find-replace en archivos del wiki

Herramienta para procesar archivos subidos a la carpeta RAW de SharePoint.

Flujo de uso:
  1. Usuario sube archivos a SharePoint/RAW/
  2. El agente llama a ordenar_archivos_raw() para moverlos al lugar correcto.

Estructura destino (bajo SHAREPOINT_DIR):
  Rent Rolls/JLL/{YYYY}/
  Fondos/Rentas TRI/Activos/Viña Centro/Rent Roll/{YYYY}/
  Fondos/Rentas TRI/Activos/Curicó/Rent Roll/{YYYY}/
  Fondos/Rentas TRI/Activos/Curicó/EEFF/{YYYY}/
  Fondos/Rentas TRI/Activos/Viña Centro/EEFF/{YYYY}/
  Fondos/Rentas TRI/Activos/INMOSA/Flujos/{YYYY}/
  Control de Gestión/CDG Mensual/{YYYY}/
  Control de Gestión/Saldo Caja/{YYYY}/
  Fondos/Rentas Apoquindo/EEFF/{YYYY}/{Qt}/
  Fondos/Rentas PT/EEFF/{YYYY}/{Qt}/
  Fondos/Rentas TRI/EEFF/Fondo/{YYYY}/{Qt}/
  Fondos/Rentas Apoquindo/Fact Sheets/{YYYY}/{Mes}/
  Fondos/Rentas PT/Fact Sheets/{YYYY}/
  Fondos/Rentas TRI/Fact Sheets/{YYYY}/{Mes}/
"""
import os
import re
import shutil
from datetime import date

from config import SHAREPOINT_DIR

_TOOLS_DIR = os.path.join(os.path.dirname(__file__))
_WIKI_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wiki")

RAW_DIR = os.path.join(SHAREPOINT_DIR, "RAW")

_MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

_Q_FROM_MES = {1: "1T", 2: "1T", 3: "1T", 4: "2T", 5: "2T", 6: "2T",
               7: "3T", 8: "3T", 9: "3T", 10: "4T", 11: "4T", 12: "4T"}


def _sp(*parts: str) -> str:
    return os.path.join(SHAREPOINT_DIR, *parts)


def _aamm_to_year_mes(aamm: str):
    """'2603' → (2026, 3)"""
    yy = int(aamm[:2])
    mm = int(aamm[2:])
    return 2000 + yy, mm


def _infer_year_from_name(name: str) -> int:
    """Busca año de 4 dígitos en el nombre; si no, usa el año actual."""
    m = re.search(r"20\d{2}", name)
    if m:
        return int(m.group())
    return date.today().year


def _classify(filename: str) -> str | None:
    """Devuelve ruta destino absoluta para el archivo, o None si no se reconoce."""
    n = filename  # nombre tal cual
    nl = n.lower()

    # ── Rent Roll JLL ──────────────────────────────────────────────────────────
    m = re.match(r"(\d{4})\s*Rent Roll y NOI", n, re.IGNORECASE)
    if m:
        año, mes = _aamm_to_year_mes(m.group(1))
        return _sp("Rent Rolls", "JLL", str(año))

    # ── Rent Roll Tres Asociados — Viña ────────────────────────────────────────
    if re.search(r"Excel Tres A Vi", n, re.IGNORECASE):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "Viña Centro", "Rent Roll", str(año))

    # ── Rent Roll Tres Asociados — Curicó ──────────────────────────────────────
    if re.search(r"Excel Tres A Curic", n, re.IGNORECASE):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "Curicó", "Rent Roll", str(año))

    # ── EEFF Curicó ────────────────────────────────────────────────────────────
    if re.search(r"INFORME EEFF POWER CENTER CURIC", n, re.IGNORECASE):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "Curicó", "EEFF", str(año))

    # ── EEFF Viña Centro ───────────────────────────────────────────────────────
    if re.search(r"INFORME EEFF VI", n, re.IGNORECASE):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "Viña Centro", "EEFF", str(año))

    # ── ER-FC INMOSA ───────────────────────────────────────────────────────────
    if re.search(r"ER-FC INMOSA", n, re.IGNORECASE):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "INMOSA", "Flujos", str(año))

    # ── Fuentes contables Rentas TRI (balance consolidado) ───────────────────
    if re.search(r"An[aá]lisis.*Ch.*arcillo", n, re.IGNORECASE) and nl.endswith(".xlsx"):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Sociedades", "Chañarcillo", "Analisis", str(año))

    if re.search(r"An[aá]lisis.*Inmobiliaria.*VC", n, re.IGNORECASE) and nl.endswith(".xlsx"):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Sociedades", "Inmobiliaria VC", "Analisis", str(año))

    if "senior assist" in nl and nl.endswith(".xlsx"):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "INMOSA", "Contabilidad", str(año))

    if nl.endswith(".pdf") and "inmosa" in nl and ("eeff" in nl or "final" in nl):
        año = _infer_year_from_name(n)
        return _sp("Fondos", "Rentas TRI", "Activos", "INMOSA", "EEFF", str(año))

    # ── CDG mensual ────────────────────────────────────────────────────────────
    m = re.match(r"(\d{4})\s*Control De Gesti", n, re.IGNORECASE)
    if m:
        año, mes = _aamm_to_year_mes(m.group(1))
        return _sp("Control de Gestión", "CDG Mensual", str(año))

    # ── Saldo Caja ─────────────────────────────────────────────────────────────
    if re.search(r"Saldo Caja", n, re.IGNORECASE):
        año = _infer_year_from_name(n)
        return _sp("Control de Gestión", "Saldo Caja", str(año))

    # ── EEFF Apoquindo (PDF trimestral) ────────────────────────────────────────
    if nl.endswith(".pdf") and "apoquindo" in nl and "toesca rentas" in nl:
        año = _infer_year_from_name(n)
        m2 = re.search(r"(\d{4})\s+(\d{2})", n)
        mes = int(m2.group(2)) if m2 else date.today().month
        qt = _Q_FROM_MES[mes]
        return _sp("Fondos", "Rentas Apoquindo", "EEFF", str(año), qt)

    # ── EEFF PT (PDF trimestral) ───────────────────────────────────────────────
    if nl.endswith(".pdf") and "rentas pt" in nl and "toesca" in nl:
        año = _infer_year_from_name(n)
        m2 = re.search(r"EEFF\s*(\d{6})", n, re.IGNORECASE)
        if m2:
            mes = int(m2.group(1)[4:])
        else:
            mes = date.today().month
        qt = _Q_FROM_MES[mes]
        return _sp("Fondos", "Rentas PT", "EEFF", str(año), qt)

    # ── EEFF TRI (PDF trimestral) ──────────────────────────────────────────────
    if nl.endswith(".pdf") and "toesca rentas inmobiliarias" in nl and "apoquindo" not in nl and "pt" not in nl:
        año = _infer_year_from_name(n)
        m2 = re.search(r"(\d{4})", n)
        mes = date.today().month
        qt = _Q_FROM_MES[mes]
        return _sp("Fondos", "Rentas TRI", "EEFF", "Fondo", str(año), qt)

    # ── Fact Sheet Apoquindo ───────────────────────────────────────────────────
    if re.search(r"Fact Sheet.*Apoquindo", n, re.IGNORECASE) and nl.endswith(".pptx"):
        m2 = re.match(r"(\d{4})", n)
        if m2:
            año, mes = _aamm_to_year_mes(m2.group(1))
            return _sp("Fondos", "Rentas Apoquindo", "Fact Sheets", str(año), _MESES_ES[mes])
        return _sp("Fondos", "Rentas Apoquindo", "Fact Sheets")

    # ── Fact Sheet PT ──────────────────────────────────────────────────────────
    if re.search(r"Fact Sheet.*PT", n, re.IGNORECASE) and nl.endswith(".pptx"):
        m2 = re.match(r"(\d{4})", n)
        if m2:
            año, _ = _aamm_to_year_mes(m2.group(1))
            return _sp("Fondos", "Rentas PT", "Fact Sheets", str(año))
        return _sp("Fondos", "Rentas PT", "Fact Sheets")

    # ── Fact Sheet TRI ─────────────────────────────────────────────────────────
    if re.search(r"Fact Sheet.*Toesca Rentas Inmobiliarias", n, re.IGNORECASE) and nl.endswith(".pptx"):
        m2 = re.match(r"(\d{4})", n)
        if m2:
            año, mes = _aamm_to_year_mes(m2.group(1))
            return _sp("Fondos", "Rentas TRI", "Fact Sheets", str(año), _MESES_ES[mes])
        return _sp("Fondos", "Rentas TRI", "Fact Sheets")

    return None


def ordenar_archivos_raw() -> str:
    """
    Revisa la carpeta RAW de SharePoint y mueve cada archivo a su carpeta correcta.
    Retorna un resumen con lo movido y los archivos no reconocidos (que quedan en RAW).
    """
    if not SHAREPOINT_DIR:
        return "Error: SHAREPOINT_DIR no configurado."
    if not os.path.isdir(RAW_DIR):
        return f"Error: carpeta RAW no encontrada en {RAW_DIR}"

    archivos = [f for f in os.listdir(RAW_DIR)
                if os.path.isfile(os.path.join(RAW_DIR, f)) and not f.startswith(".")]

    if not archivos:
        return "Carpeta RAW vacía — no hay archivos para ordenar."

    movidos = []
    no_reconocidos = []

    for nombre in archivos:
        src = os.path.join(RAW_DIR, nombre)
        destino_dir = _classify(nombre)

        if destino_dir is None:
            no_reconocidos.append(nombre)
            continue

        os.makedirs(destino_dir, exist_ok=True)
        dst = os.path.join(destino_dir, nombre)

        if os.path.exists(dst):
            no_reconocidos.append(f"{nombre} (ya existe en destino)")
            continue

        shutil.move(src, dst)
        rel = dst.replace(SHAREPOINT_DIR, "").lstrip(os.sep)
        movidos.append((nombre, rel))

    lines = []
    lines.append("## 📁 RAW procesado")
    lines.append("")
    if movidos:
        lines.append(f"### ✅ Archivos movidos `{len(movidos)}`")
        for nombre, rel in movidos:
            lines.append(f"- **{nombre}**")
            lines.append(f"  → `{rel}`")
        lines.append("")
    if no_reconocidos:
        lines.append(f"### ⚠️ Archivos no reconocidos `{len(no_reconocidos)}`")
        lines.append("_Quedan en RAW para revisión manual._")
        for f in no_reconocidos:
            lines.append(f"- `{f}`")
        lines.append("")
    if not movidos and not no_reconocidos:
        lines.append("✅ **Sin cambios.**")

    return "\n".join(lines)


def reemplazar_en_tool(nombre_archivo: str, texto_viejo: str, texto_nuevo: str) -> str:
    """
    Busca y reemplaza texto en un archivo de herramienta del agente (tools/*.py)
    o en cualquier archivo Python del proyecto.

    nombre_archivo: nombre del archivo con extensión (ej: "noi_tools.py") o ruta relativa
    texto_viejo: cadena exacta a buscar (sensible a mayúsculas)
    texto_nuevo: cadena de reemplazo

    Retorna cuántas ocurrencias se reemplazaron.
    """
    # Resolver ruta
    if os.path.isabs(nombre_archivo) and os.path.isfile(nombre_archivo):
        ruta = nombre_archivo
    else:
        ruta = os.path.join(_TOOLS_DIR, nombre_archivo)
        if not os.path.isfile(ruta):
            # Intentar en raíz del proyecto
            ruta = os.path.join(os.path.dirname(_TOOLS_DIR), nombre_archivo)

    if not os.path.isfile(ruta):
        return f"Archivo no encontrado: {nombre_archivo}"

    with open(ruta, "r", encoding="utf-8") as f:
        contenido = f.read()

    count = contenido.count(texto_viejo)
    if count == 0:
        return f"Texto no encontrado en {nombre_archivo}: {repr(texto_viejo)}"

    nuevo_contenido = contenido.replace(texto_viejo, texto_nuevo)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(nuevo_contenido)

    return f"{count} reemplazo(s) en {nombre_archivo}: {repr(texto_viejo)} → {repr(texto_nuevo)}"


def reemplazar_en_wiki(nombre_archivo: str, texto_viejo: str, texto_nuevo: str) -> str:
    """
    Busca y reemplaza texto en un archivo del wiki del agente (wiki/**/*.md).

    nombre_archivo: ruta relativa al directorio wiki/ (ej: "sharepoint/index.md") o nombre del .md
    texto_viejo: cadena exacta a buscar
    texto_nuevo: cadena de reemplazo
    """
    # Intentar ruta relativa dentro del wiki
    candidatos = [
        os.path.join(_WIKI_DIR, nombre_archivo),
        os.path.join(_WIKI_DIR, nombre_archivo.replace("/", os.sep)),
    ]
    # Buscar recursivamente si no coincide directo
    ruta = None
    for c in candidatos:
        if os.path.isfile(c):
            ruta = c
            break
    if ruta is None:
        for root, _, files in os.walk(_WIKI_DIR):
            for fn in files:
                if fn == nombre_archivo or fn == os.path.basename(nombre_archivo):
                    ruta = os.path.join(root, fn)
                    break
            if ruta:
                break

    if ruta is None:
        return f"Archivo wiki no encontrado: {nombre_archivo}"

    with open(ruta, "r", encoding="utf-8") as f:
        contenido = f.read()

    count = contenido.count(texto_viejo)
    if count == 0:
        return f"Texto no encontrado en {nombre_archivo}: {repr(texto_viejo)}"

    nuevo_contenido = contenido.replace(texto_viejo, texto_nuevo)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(nuevo_contenido)

    return f"{count} reemplazo(s) en {nombre_archivo}: {repr(texto_viejo)} → {repr(texto_nuevo)}"
