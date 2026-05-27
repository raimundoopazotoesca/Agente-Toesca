"""
Actualización de UF diaria desde mindicador.cl → fact_uf.

API: https://mindicador.cl/api/uf/YYYY  → JSON con serie diaria del año.
"""
import json
import urllib.request
import urllib.error
from datetime import date, timedelta

from tools.db.connection import get_conn
from tools.db import repo_fact

_API_URL = "https://mindicador.cl/api/uf/{year}"
_HEADERS = {"User-Agent": "automation-agent/1.0"}


def _fetch_year(year: int) -> list[tuple[str, float]]:
    """Retorna lista de (fecha ISO, valor_clp) para el año dado."""
    url = _API_URL.format(year=year)
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    pares = []
    for item in data.get("serie", []):
        # fecha viene como "2026-03-09T00:00:00.000Z"
        fecha_str = item["fecha"][:10]
        valor = float(item["valor"])
        pares.append((fecha_str, valor))
    return pares


def actualizar_uf_desde_web(verbose: bool = True) -> dict:
    """
    Descarga valores de UF diarios desde mindicador.cl e inserta/actualiza
    fact_uf para todos los días que falten hasta hoy.

    Retorna dict con claves: filas_nuevas, desde, hasta, error.
    """
    result: dict = {"filas_nuevas": 0, "desde": None, "hasta": None, "error": None}

    try:
        with get_conn() as conn:
            cur = conn.execute("SELECT MAX(fecha) FROM fact_uf")
            row = cur.fetchone()
            ultima = row[0] if row and row[0] else "2012-12-31"

        ultima_date = date.fromisoformat(ultima)
        hoy = date.today()

        if ultima_date >= hoy:
            result["desde"] = ultima
            result["hasta"] = ultima
            if verbose:
                print(f"  [uf] ya actualizado hasta {ultima}")
            return result

        # Años a cubrir: desde el año de la última fecha hasta hoy
        years = range(ultima_date.year, hoy.year + 1)

        pares_nuevos: list[tuple[str, float]] = []
        for year in years:
            pares = _fetch_year(year)
            for fecha, valor in pares:
                if fecha > ultima:
                    pares_nuevos.append((fecha, valor))

        if pares_nuevos:
            pares_nuevos.sort()
            with get_conn() as conn:
                for fecha, valor in pares_nuevos:
                    repo_fact.upsert_uf(conn, fecha, valor)
            result["filas_nuevas"] = len(pares_nuevos)
            result["desde"] = pares_nuevos[0][0]
            result["hasta"] = pares_nuevos[-1][0]
            if verbose:
                print(f"  [uf] {len(pares_nuevos)} dias nuevos: "
                      f"{pares_nuevos[0][0]} a {pares_nuevos[-1][0]}")
        else:
            result["desde"] = ultima
            result["hasta"] = ultima
            if verbose:
                print("  [uf] sin datos nuevos")

    except Exception as e:
        result["error"] = str(e)
        if verbose:
            print(f"  [uf] ERROR: {e}")

    return result
