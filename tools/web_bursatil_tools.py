"""
Precios de cuotas de fondos de inversión chilenos.
Fuente: mercados.larrainvial.com (endpoints internos, sin autenticación).
"""
import json
import re
import urllib.request
import urllib.error
from datetime import date
from calendar import monthrange


NEMOTECNICOS = {
    "CFITRIPT-E":  "Toesca Rentas Inmobiliarias PT",
    "CFITOERI1A":  "Toesca Rentas Inmobiliarias Serie A",
    "CFITOERI1C":  "Toesca Rentas Inmobiliarias Serie C",
    "CFITOERI1I":  "Toesca Rentas Inmobiliarias Serie I",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html",
    "Referer": "https://mercados.larrainvial.com/www/v2/index.html",
}

_ID_CACHE: dict[str, str] = {}


def _fetch(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _get_notation_id(nemotecnico: str) -> str:
    """Obtiene el ID de notación de LarraínVial para el nemotécnico."""
    if nemotecnico in _ID_CACHE:
        return _ID_CACHE[nemotecnico]
    url = (f"https://mercados.larrainvial.com/www/buscador.html"
           f"?SEARCH_VALUE={nemotecnico}&MERCADO=chile")
    raw = _fetch(url)
    data = json.loads(raw)
    if not data:
        raise ValueError(f"Nemotécnico '{nemotecnico}' no encontrado en LarraínVial.")
    notation_id = str(data[0]["id"])
    _ID_CACHE[nemotecnico] = notation_id
    return notation_id


def _last_trading_day_of_month(history: list[dict], year: int, month: int) -> dict | None:
    """Retorna la última entrada del mes indicado (mes 1-indexed)."""
    # JS month is 0-indexed; our month param is 1-indexed
    js_month = month - 1
    entries = [e for e in history if e["year"] == year and e["js_month"] == js_month]
    return entries[-1] if entries else None


def _parse_datachart(raw: str) -> list[dict]:
    """Parsea el formato JS: {date:new Date(y,m,d,...),close:P,...}"""
    pattern = r"new Date\((\d+),\s*(\d+),\s*(\d+)[^)]*\),close:([\d.]+)"
    entries = []
    for m in re.finditer(pattern, raw):
        entries.append({
            "year": int(m.group(1)),
            "js_month": int(m.group(2)),
            "day": int(m.group(3)),
            "close": float(m.group(4)),
        })
    return entries


def obtener_precio_cuota(nemotecnico: str, año: int, mes: int) -> str:
    """
    Obtiene el valor cuota del último día bursátil del mes indicado.
    Fuente: mercados.larrainvial.com
    """
    nemotecnico = nemotecnico.strip().upper()
    try:
        notation_id = _get_notation_id(nemotecnico)
        url = (f"https://mercados.larrainvial.com/www/datachart.html"
               f"?ID_NOTATION={notation_id}&TIME_SPAN=2Y&QUALITY=1&VOLUME=true")
        raw = _fetch(url)
        history = _parse_datachart(raw)
        if not history:
            return f"No se pudo parsear datos de precio para {nemotecnico}."
        entry = _last_trading_day_of_month(history, año, mes)
        if entry is None:
            return (f"No hay datos para {nemotecnico} en {mes:02d}/{año}. "
                    f"Rango disponible: {history[0]['year']}/{history[0]['js_month']+1} "
                    f"- {history[-1]['year']}/{history[-1]['js_month']+1}.")
        last_day = date(año, mes, monthrange(año, mes)[1])
        actual_day = date(entry["year"], entry["js_month"] + 1, entry["day"])
        return (f"Precio cuota {nemotecnico} al {actual_day.strftime('%d/%m/%Y')}"
                f" (último bursátil de {last_day.strftime('%m/%Y')}): "
                f"{entry['close']:,.4f} (fuente: LarraínVial)")
    except Exception as e:
        return f"Error obteniendo precio de {nemotecnico}: {e}"


def obtener_precios_mes(año: int, mes: int) -> str:
    """Obtiene todos los precios necesarios para el mes indicado."""
    resultados = []
    for nemo, label in NEMOTECNICOS.items():
        r = obtener_precio_cuota(nemo, año, mes)
        resultados.append(f"{label} ({nemo}):\n  {r}")
    return "\n\n".join(resultados)


# Legacy aliases kept for compatibility
def obtener_precio_cuota_cmf(nemotecnico: str, año: int, mes: int) -> str:
    return obtener_precio_cuota(nemotecnico, año, mes)


def obtener_precio_cuota_larrainvial(nemotecnico: str, año: int, mes: int) -> str:
    return obtener_precio_cuota(nemotecnico, año, mes)
