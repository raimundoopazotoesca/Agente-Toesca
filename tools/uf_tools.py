"""UF diaria: fetch desde CMF (api.cmfchile.cl) o SII (scraping) y persistencia.

Prioridad:
  1. CMF si CMF_API_KEY está en el entorno. Registro gratuito en
     https://api.cmfchile.cl/RegistroUsuario/RegistroUsuario.aspx
  2. Fallback: scraping SII (sii.cl/valores_y_fechas/uf/ufYYYY.htm).

Persistencia: tabla `raw_uf_diaria` (migration 043).
"""
from __future__ import annotations

import os
import re
import sqlite3
from calendar import monthrange
from datetime import date, timedelta
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from tools.db.connection import get_conn

_HEADERS = {"User-Agent": "Mozilla/5.0 (automation_agent)"}
_CMF_BASE = "https://api.cmfchile.cl/api-sbifv3/recursos_api/uf"


def _clp_str_to_float(s: str) -> float | None:
    """'40.823,03' → 40823.03. Devuelve None si no parsea."""
    s = s.strip()
    if not s:
        return None
    m = re.fullmatch(r"([\d\.]+),(\d+)", s)
    if not m:
        return None
    entero = m.group(1).replace(".", "")
    return float(f"{entero}.{m.group(2)}")


# --------------------------------------------------------------------------- #
# CMF fetch
# --------------------------------------------------------------------------- #

def _cmf_fetch_periodo(y1: int, m1: int, y2: int, m2: int, apikey: str) -> dict[str, float]:
    """Rango mes-a-mes cerrado. Devuelve {fecha_iso: valor}."""
    url = f"{_CMF_BASE}/periodo/{y1}/{m1:02d}/{y2}/{m2:02d}?apikey={apikey}&formato=json"
    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    out: dict[str, float] = {}
    for item in data.get("UFs", []):
        v = _clp_str_to_float(item["Valor"])
        if v is not None:
            out[item["Fecha"]] = v
    return out


def _cmf_fetch_year(year: int, apikey: str) -> dict[str, float]:
    url = f"{_CMF_BASE}/{year}?apikey={apikey}&formato=json"
    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return {item["Fecha"]: v for item in data.get("UFs", [])
            if (v := _clp_str_to_float(item["Valor"])) is not None}


# --------------------------------------------------------------------------- #
# SII fetch (fallback)
# --------------------------------------------------------------------------- #

_MES_COL = {"Ene":1, "Feb":2, "Mar":3, "Abr":4, "May":5, "Jun":6,
            "Jul":7, "Ago":8, "Sep":9, "Oct":10, "Nov":11, "Dic":12}


def _sii_fetch_year(year: int) -> dict[str, float]:
    """Scrapea sii.cl/valores_y_fechas/uf/ufYYYY.htm.

    Estructura HTML: la última tabla (índice -1) tiene:
      - fila 0: cabecera 'Día', 'Ene', 'Feb', ...
      - filas 1..N: [día, val_ene, val_feb, ..., val_dic]
    """
    url = f"https://www.sii.cl/valores_y_fechas/uf/uf{year}.htm"
    r = requests.get(url, headers=_HEADERS, timeout=20)
    r.encoding = "utf-8"
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return {}
    table = tables[-1]  # tabla principal día×mes
    rows = table.find_all("tr")
    if len(rows) < 2:
        return {}
    header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    # Map columna → mes
    col_to_month: dict[int, int] = {}
    for idx, h in enumerate(header):
        # Header puede venir con acentos raros; usar prefijo
        for label, m in _MES_COL.items():
            if h.startswith(label[:3]):
                col_to_month[idx] = m
                break

    out: dict[str, float] = {}
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue
        try:
            dia = int(cells[0])
        except ValueError:
            continue
        for idx, month in col_to_month.items():
            if idx >= len(cells):
                continue
            v = _clp_str_to_float(cells[idx])
            if v is None:
                continue
            # Validar fecha (skip 31 de meses con 30 días, etc.)
            try:
                d = date(year, month, dia)
            except ValueError:
                continue
            out[d.isoformat()] = v
    return out


# --------------------------------------------------------------------------- #
# API pública del módulo
# --------------------------------------------------------------------------- #

def fetch_uf_year(year: int) -> tuple[dict[str, float], str]:
    """Baja la UF de un año completo. Devuelve (data, fuente)."""
    apikey = os.environ.get("CMF_API_KEY")
    if apikey:
        try:
            return _cmf_fetch_year(year, apikey), "CMF"
        except Exception as e:
            # HTTPError incluye la URL completa; la CMF usa la API key en query
            # string, por lo que nunca debemos imprimir el mensaje de excepción.
            print(f"[uf] CMF falló ({type(e).__name__}); usando SII")
    return _sii_fetch_year(year), "SII"


def upsert_uf(conn: sqlite3.Connection, rows: Iterable[tuple[str, float, str]]) -> int:
    """Inserta o reemplaza {(fecha, valor, fuente)}. Devuelve # filas escritas."""
    n = 0
    for fecha, valor, fuente in rows:
        conn.execute(
            """INSERT INTO raw_uf_diaria(fecha, valor, fuente)
                 VALUES(?, ?, ?)
                 ON CONFLICT(fecha) DO UPDATE SET
                     valor = excluded.valor,
                     fuente = excluded.fuente,
                     loaded_at = datetime('now')""",
            (fecha, valor, fuente),
        )
        n += 1
    conn.commit()
    return n


def get_uf(conn: sqlite3.Connection, fecha_iso: str) -> float | None:
    """Devuelve UF de la fecha exacta o la última anterior disponible."""
    cur = conn.execute(
        "SELECT valor FROM raw_uf_diaria WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
        (fecha_iso,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def ensure_years(conn: sqlite3.Connection, years: Iterable[int]) -> dict[int, int]:
    """Asegura que UF de cada año esté en DB. Devuelve {year: filas_nuevas}."""
    result: dict[int, int] = {}
    for y in years:
        data, fuente = fetch_uf_year(y)
        n = upsert_uf(conn, [(f, v, fuente) for f, v in data.items()])
        result[y] = n
        print(f"  [{fuente}] {y}: {n} valores UF")
    return result
