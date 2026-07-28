"""Ingesta de dólar observado desde dolarapi.com (Chile).

Solo expone la cotización del día (sin serie histórica) — ver
https://cl.dolarapi.com/v1/cotizaciones/usd. Cada corrida agrega UN punto a
`fact_dolar` con la fecha de hoy. `repo_fact.get_dolar` busca la fecha <=
la solicitada más reciente, así que esto alcanza para convertir saldos USD de
meses actuales/cercanos, pero NO resuelve el histórico (2018-2026) que ya
está cargado en raw_caja sin convertir — para eso se necesita una fuente de
serie histórica de dólar observado, que esta API no tiene.

Usa 'compra' (lo que se recibe al vender los USD) como tipo de cambio: es el
valor relevante para convertir un saldo bancario en USD a su equivalente CLP.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime
from typing import Optional

API_URL = "https://cl.dolarapi.com/v1/cotizaciones/usd"


def fetch_dolar_hoy() -> tuple[str, float]:
    """(fecha ISO de hoy, valor CLP por USD='compra'). Lanza en caso de error de red."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    valor = float(data["compra"])
    return date.today().isoformat(), valor


def backfill_dolar_hoy(conn: "object | None" = None, verbose: bool = True) -> dict:
    """Trae la cotización de hoy y la upsertea en fact_dolar (raw_dolar_diaria)."""
    from tools.db import repo_fact

    owns_conn = conn is None
    if owns_conn:
        from tools.db.connection import get_conn

        conn = get_conn()

    try:
        try:
            fecha, valor = fetch_dolar_hoy()
        except Exception as e:
            return {"archivos": 0, "filas": 0, "sin_datos": [f"dolarapi.com no respondió: {e}"]}

        repo_fact.upsert_dolar(conn, fecha, valor, fuente="dolarapi_compra")
        if verbose:
            print(f"  [dolar] {fecha} = {valor} CLP/USD (dolarapi.com, compra)")
        return {"archivos": 1, "filas": 1, "sin_datos": []}
    finally:
        if owns_conn:
            conn.close()


if __name__ == "__main__":
    resultado = backfill_dolar_hoy()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
