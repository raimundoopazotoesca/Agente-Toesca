"""
Herramientas para obtener precios de cuotas de fondos de inversión chilenos.
Fuente primaria: CMF Chile (API pública, sin autenticación).
Fuente alternativa: Larraín Vial (scraping simple).
"""
import json
import re
import urllib.request
import urllib.error
from datetime import date, timedelta


# Nemotécnicos disponibles en el proyecto
NEMOTECNICOS = {
    "CFITRIPT-E":   "A&R PT",
    "CFITOERI1A":   "A&R Rentas Serie A",
    "CFITOERI1C":   "A&R Rentas Serie C",
    "CFITOERI1I":   "A&R Rentas Serie I",
}


def _last_day_of_month(year: int, month: int) -> date:
    from calendar import monthrange
    return date(year, month, monthrange(year, month)[1])


def _fetch_url(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def obtener_precio_cuota_cmf(nemotecnico: str, año: int, mes: int) -> str:
    """
    Obtiene el valor cuota del último día del mes indicado desde la API de la CMF.
    Endpoint: https://api.cmfchile.cl/api-sbifv3/recursos_api/fondosinversion/...
    Retorna el precio como string o un mensaje de error.
    """
    fecha_fin = _last_day_of_month(año, mes)
    fecha_str = fecha_fin.strftime("%Y-%m-%d")

    # La CMF expone valores cuota de fondos de inversión.
    # Endpoint para cuotas de fondos por nemotécnico y período:
    url = (
        f"https://api.cmfchile.cl/api-sbifv3/recursos_api/fondosinversion/"
        f"cuotas/{nemotecnico}?fecha={fecha_str}&formato=json"
    )
    try:
        raw = _fetch_url(url)
        data = json.loads(raw)
        # Estructura típica: {"cuotas": [{"fecha": "...", "valor": "..."}]}
        cuotas = data.get("cuotas") or data.get("Cuotas") or []
        if cuotas:
            # Tomar la más reciente <= fecha_fin
            for entry in reversed(cuotas):
                valor_str = entry.get("valor") or entry.get("Valor") or ""
                if valor_str:
                    valor = float(valor_str.replace(",", ".").replace("$", "").strip())
                    fecha_entry = entry.get("fecha") or entry.get("Fecha") or ""
                    return (f"Precio cuota {nemotecnico} al {fecha_entry}: "
                            f"{valor:,.4f} (fuente: CMF)")
        return f"CMF no retornó datos para {nemotecnico} en {fecha_str}. Respuesta: {raw[:200]}"
    except urllib.error.HTTPError as e:
        return f"Error HTTP {e.code} al consultar CMF para {nemotecnico}."
    except Exception as e:
        return f"Error al consultar CMF para {nemotecnico}: {e}"


def obtener_precio_cuota_larrainvial(nemotecnico: str, año: int, mes: int) -> str:
    """
    Intenta obtener el precio del nemotécnico desde la API interna de Larraín Vial.
    Mercado: https://mercados.larrainvial.com/www/v2/index.html?mercado=chile
    """
    fecha_fin = _last_day_of_month(año, mes)
    # La API interna de Larraín Vial para búsqueda de instrumentos
    # (endpoint descubierto inspeccionando las peticiones del sitio)
    search_url = (
        f"https://mercados.larrainvial.com/api/instruments/search"
        f"?query={nemotecnico}&market=chile"
    )
    try:
        raw = _fetch_url(search_url)
        data = json.loads(raw)
        instruments = data if isinstance(data, list) else data.get("data", [])
        if not instruments:
            return f"LarraínVial: nemotécnico '{nemotecnico}' no encontrado."

        instr = instruments[0]
        isin = instr.get("isin") or instr.get("id") or instr.get("nemotecnico", "")

        # Consultar precio histórico
        hist_url = (
            f"https://mercados.larrainvial.com/api/instruments/{isin}/history"
            f"?from={fecha_fin.strftime('%Y-%m-%d')}"
            f"&to={fecha_fin.strftime('%Y-%m-%d')}"
        )
        raw2 = _fetch_url(hist_url)
        data2 = json.loads(raw2)
        prices = data2 if isinstance(data2, list) else data2.get("data", [])
        if prices:
            p = prices[-1]
            precio = p.get("close") or p.get("price") or p.get("valor")
            return f"Precio cuota {nemotecnico} al {fecha_fin}: {precio} (fuente: LarraínVial)"
        return f"LarraínVial: no hay precios para {nemotecnico} en {fecha_fin}."
    except Exception as e:
        return f"Error al consultar LarraínVial para {nemotecnico}: {e}"


def obtener_precio_cuota(nemotecnico: str, año: int, mes: int) -> str:
    """
    Obtiene el valor cuota de un fondo para el último día del mes indicado.
    Intenta primero CMF, luego Larraín Vial.
    Retorna el precio encontrado o instrucciones para ingresarlo manualmente.
    """
    nemotecnico = nemotecnico.strip().upper()

    # Intento 1: CMF
    resultado_cmf = obtener_precio_cuota_cmf(nemotecnico, año, mes)
    if "Error" not in resultado_cmf and "no retornó" not in resultado_cmf:
        return resultado_cmf

    # Intento 2: Larraín Vial
    resultado_lv = obtener_precio_cuota_larrainvial(nemotecnico, año, mes)
    if "Error" not in resultado_lv and "no encontrado" not in resultado_lv:
        return resultado_lv

    fecha = _last_day_of_month(año, mes)
    return (
        f"No se pudo obtener precio automáticamente para {nemotecnico} "
        f"({fecha.strftime('%d/%m/%Y')}).\n"
        f"  CMF: {resultado_cmf}\n"
        f"  LarraínVial: {resultado_lv}\n"
        f"Buscar manualmente en: https://mercados.larrainvial.com/www/v2/index.html?mercado=chile\n"
        f"Usar nemotécnico: {nemotecnico}"
    )


def obtener_precios_mes(año: int, mes: int) -> str:
    """
    Obtiene todos los precios necesarios para el mes indicado:
    CFITRIPT-E (A&R PT), CFITOERI1A/C/I (A&R Rentas).
    """
    resultados = []
    for nemo, label in NEMOTECNICOS.items():
        r = obtener_precio_cuota(nemo, año, mes)
        resultados.append(f"{label} ({nemo}):\n  {r}")
    return "\n\n".join(resultados)
