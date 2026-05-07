"""
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
  Fondos/Apoquindo/EEFF/{YYYY}/{Qt}/
  Fondos/Parque Titanium/EEFF/{YYYY}/{Qt}/
  Fondos/Rentas TRI/EEFF/Fondo/{YYYY}/{Qt}/
  Fondos/Apoquindo/Fact Sheets/{YYYY}/{Mes}/
  Fondos/Parque Titanium/Fact Sheets/{YYYY}/
  Fondos/Rentas TRI/Fact Sheets/{YYYY}/{Mes}/
"""
import os
import re
import shutil
from datetime import date

from config import SHAREPOINT_DIR

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
        return _sp("Fondos", "Apoquindo", "EEFF", str(año), qt)

    # ── EEFF PT (PDF trimestral) ───────────────────────────────────────────────
    if nl.endswith(".pdf") and "rentas pt" in nl and "toesca" in nl:
        año = _infer_year_from_name(n)
        m2 = re.search(r"EEFF\s*(\d{6})", n, re.IGNORECASE)
        if m2:
            mes = int(m2.group(1)[4:])
        else:
            mes = date.today().month
        qt = _Q_FROM_MES[mes]
        return _sp("Fondos", "Parque Titanium", "EEFF", str(año), qt)

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
            return _sp("Fondos", "Apoquindo", "Fact Sheets", str(año), _MESES_ES[mes])
        return _sp("Fondos", "Apoquindo", "Fact Sheets")

    # ── Fact Sheet PT ──────────────────────────────────────────────────────────
    if re.search(r"Fact Sheet.*PT", n, re.IGNORECASE) and nl.endswith(".pptx"):
        m2 = re.match(r"(\d{4})", n)
        if m2:
            año, _ = _aamm_to_year_mes(m2.group(1))
            return _sp("Fondos", "Parque Titanium", "Fact Sheets", str(año))
        return _sp("Fondos", "Parque Titanium", "Fact Sheets")

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
        movidos.append(f"  ✓ {nombre} → {rel}")

    lines = []
    if movidos:
        lines.append(f"Archivos movidos ({len(movidos)}):")
        lines.extend(movidos)
    if no_reconocidos:
        lines.append(f"\nArchivos no reconocidos ({len(no_reconocidos)}) — quedan en RAW:")
        for f in no_reconocidos:
            lines.append(f"  ? {f}")
    if not movidos and not no_reconocidos:
        lines.append("Sin cambios.")

    return "\n".join(lines)
