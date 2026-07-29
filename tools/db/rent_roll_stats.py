"""Estadísticas de rent roll para la tabla "Resumen Performance Activos del
Fondo" de la página 2 del fact sheet PT (ver FONDOS_CFG["PT"]["page2"] en
scripts/build_factsheet.py).

Fuente única: raw_rent_roll_line (ingestada vía tools/db/ingest_rent_roll_validated).

Mapeo activo2 (nombre corto usado por JLL en el rent roll) -> grupo del fact
sheet, confirmado con el usuario 2026-07-20:
    "Torre A"    -> "Torre A S.A."
    "Inmob. CdC" -> "Inmob. Boulevard PT SpA"
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

from tools.db import rent_roll_source  # noqa: E402
from tools.db.ingest_rent_roll_validated import (  # noqa: E402
    _monto_mensual_uf,
    _es_vacante,
    _clasificar_evento,
    _tipo_real,
)

_ACTIVO2_LABEL = {
    "Torre A": "Torre A S.A.",
    "Inmob. CdC": "Inmob. Boulevard PT SpA",
}

# Sentinel para celdas de renta que dependen de facturación real, no del rent
# roll (ver _celda). El fact sheet (factsheet.html) lo detecta y pinta
# "Pendiente" en vez de un número.
RENTA_PENDIENTE = "PENDIENTE"

# Este módulo históricamente llamaba a get_perf_table/get_vacancia_edificios
# con una clave "lógica" de fondo/activo consolidado ("PT", "Apoquindo") que
# nunca coincidió con un activo_key real de dim_activo. Mientras el rent roll
# solo existía como borrador eso no se notaba (rent_roll_source caía al
# fallback por activo1). Al ingestar el rent roll validado de junio-2026
# (raw_rent_roll_line.activo_key = "Torre A"/"Boulevard"/"Apo4501"/"Apo4700",
# ver dim_activo), _snapshot("PT", ...) dejó de encontrar filas. Se resuelve
# la clave lógica a los activo_key reales antes de consultar la DB.
_LOGICAL_ACTIVO_KEYS = {
    "PT": ["Torre A", "Boulevard"],
    "Apoquindo": ["Apo4501", "Apo4700"],
}


def _resolve_activo_keys(activo_key: str) -> list[str]:
    return _LOGICAL_ACTIVO_KEYS.get(activo_key, [activo_key])


def _snapshot(activo_key: str, periodo: str) -> dict:
    """{(activo2, unidad): {arrendatario, m2, renta_uf, vencimiento, tipo_activo_3}}

    Fuente: rent_roll_source.get_rent_roll_rows — DB si el período ya fue
    ingestado por el pipeline validado, o el Excel borrador (no verificado)
    como fallback mientras tanto. Al ingestar el rent roll bueno, esta función
    empieza a leer de DB automáticamente, sin cambios.

    tipo_activo_3 acá siempre refleja el tipo real de la unidad: se prioriza
    "Tipo Activo 2 (no va vacante)" (nunca se pisa con "Vacante") y se cae a
    "Tipo Activo 3" solo si esa columna no vino en el archivo."""
    out = {}
    for real_key in _resolve_activo_keys(activo_key):
        rows = rent_roll_source.get_rent_roll_rows(real_key, periodo)
        for r in rows:
            try:
                extra = json.loads(r["extra_json"] or "{}")
            except (TypeError, ValueError):
                extra = {}
            tipo = _tipo_real(extra.get("tipo_activo_2"), extra.get("tipo_activo_3"))
            key = (extra.get("activo2") or "", r["unidad"])
            out[key] = {
                "arrendatario": r["arrendatario"],
                "m2": r["m2"] or 0.0,
                "renta_uf": r["renta_uf"] or 0.0,
                "vencimiento": r["vencimiento"],
                "tipo_activo_3": tipo,
                "renta_gracia": extra.get("renta_gracia") or 0.0,
                "tipo_arrendatario": extra.get("tipo_arrendatario"),
            }
    return out


def _periodos_disponibles(activo_key: str) -> list[str]:
    periodos: set[str] = set()
    for real_key in _resolve_activo_keys(activo_key):
        periodos.update(rent_roll_source.periodos_disponibles(real_key))
    return sorted(periodos)


def _meses_atras(periodo: str, n: int) -> str:
    y, m = (int(x) for x in periodo.split("-"))
    total = y * 12 + (m - 1) - n
    return f"{total // 12}-{total % 12 + 1:02d}"


def _celda(grupo: str, tipo: str, snapshot: dict, activo_key: str, periodo: str) -> dict:
    filtradas = {
        k: v for k, v in snapshot.items()
        # PT usa un alias del rent roll para el grupo (ver _ACTIVO2_LABEL);
        # Apo no lo necesita, el activo2 crudo ("Apoquindo 4501"/"4700") ya
        # coincide con el label del grupo.
        if (_ACTIVO2_LABEL.get(k[0], k[0])) == grupo and v["tipo_activo_3"] == tipo
    }
    ocupadas = [v for v in filtradas.values() if not _es_vacante(v["arrendatario"])]
    vacantes = [v for v in filtradas.values() if _es_vacante(v["arrendatario"])]
    # "m² útiles" = superficie/unidades TOTALES del tipo (ocupadas + vacantes),
    # no solo lo ocupado — "útiles" describe el inventario utilizable del
    # edificio, no la parte arrendada. "m² vacantes" es el subconjunto vacante
    # dentro de ese total (no se suman por separado).
    if tipo == "Estacionamientos":
        # Estacionamientos se reporta en unidades, no en m² (un estacionamiento
        # no tiene un m² comparable/relevante como oficinas o locales).
        m2_vac = len(vacantes)
        m2_util = len(ocupadas) + m2_vac
    else:
        m2_vac = sum(v["m2"] for v in vacantes)
        m2_util = sum(v["m2"] for v in ocupadas) + m2_vac
    m2_total = m2_util
    pct_vac = round(m2_vac / m2_total * 100, 2) if m2_total else None
    if grupo == "Inmob. Boulevard PT SpA" and tipo in ("Bodegas", "Estacionamientos"):
        # Renta de Bodegas/Estacionamientos de Inmob. Boulevard PT SpA depende
        # de la facturación real (no de la tasa del rent roll) — queda
        # pendiente hasta wire con esa fuente. Torre A S.A. sí usa la tasa del
        # rent roll con normalidad. RENTA_PENDIENTE se propaga en _suma_celdas.
        renta_mensual = renta_vacante = RENTA_PENDIENTE
    else:
        renta_mensual = round(sum(_monto_mensual_uf(v) for v in ocupadas), 1)
        renta_vacante = round(sum(_monto_mensual_uf(v) for v in vacantes), 1)
    # Renta en gracia: calculada por unidad en _renta_gracia_calculada (ver
    # tools/db/ingest_rent_roll_validated.py) — Renta Esperada Ponderada si
    # el contrato aún no empieza a pagar, si no 0. No depende de facturación,
    # así que se calcula siempre (incluso para Boulevard Bodegas/
    # Estacionamientos, a diferencia de renta_mensual/vacante).
    renta_gracia = round(sum(v["renta_gracia"] for v in filtradas.values()), 1)
    pct_vac_uf = _pct_vacancia_uf(renta_mensual, renta_vacante, renta_gracia)
    return {
        "m2_utiles": round(m2_util, 1),
        "m2_vacantes": round(m2_vac, 1),
        "pct_vacancia_m2": pct_vac,
        "renta_mensual_uf": renta_mensual,
        "renta_uf_vacante": renta_vacante,
        "renta_uf_gracia": renta_gracia,
        "pct_vacancia_uf": pct_vac_uf,
        "absorcion_3m": _absorcion_ventana(activo_key, periodo, 3, grupo, tipo),
        "absorcion_12m": _absorcion_ventana(activo_key, periodo, 12, grupo, tipo),
    }


def _absorcion_ventana(
    activo_key: str, periodo: str, meses: int,
    grupo: str | None = None, tipo: str | None = None,
) -> dict:
    """Absorción bruta/neta (m² y UF) entre (periodo - meses) y periodo,
    caminando los períodos consecutivos que existan en DB dentro de esa
    ventana (los meses sin rent roll ingestado simplemente no aportan
    movimiento — no se interpola).

    Si se pasan grupo/tipo, restringe el movimiento a esa columna de la tabla
    de performance (mismo criterio de _celda); si no, es la absorción total
    del activo/fondo."""
    disponibles = _periodos_disponibles(activo_key)
    limite_inf = _meses_atras(periodo, meses)
    ventana = sorted(p for p in disponibles if limite_inf <= p <= periodo)
    if len(ventana) < 2:
        return {"bruta_m2": None, "bruta_uf": None, "neta_m2": None, "neta_uf": None}

    bruta_m2 = bruta_uf = neta_m2 = neta_uf = 0.0
    for i in range(1, len(ventana)):
        snap_a = _snapshot(activo_key, ventana[i - 1])
        snap_b = _snapshot(activo_key, ventana[i])
        for key in set(snap_a) | set(snap_b):
            antes, ahora = snap_a.get(key), snap_b.get(key)
            if grupo is not None:
                rec = ahora or antes
                if _ACTIVO2_LABEL.get(key[0], key[0]) != grupo or rec["tipo_activo_3"] != tipo:
                    continue
            ev = _clasificar_evento(antes, ahora)["evento"]
            if ev == "alta" and ahora is not None:
                bruta_m2 += ahora["m2"] or 0.0
                bruta_uf += _monto_mensual_uf(ahora)
                neta_m2 += ahora["m2"] or 0.0
                neta_uf += _monto_mensual_uf(ahora)
            elif ev == "baja" and antes is not None:
                neta_m2 -= antes["m2"] or 0.0
                neta_uf -= _monto_mensual_uf(antes)
    return {
        "bruta_m2": round(bruta_m2, 1), "bruta_uf": round(bruta_uf, 1),
        "neta_m2": round(neta_m2, 1), "neta_uf": round(neta_uf, 1),
    }


def _suma_absorciones(absorciones: list[dict]) -> dict:
    if all(a["bruta_m2"] is None for a in absorciones):
        return {"bruta_m2": None, "bruta_uf": None, "neta_m2": None, "neta_uf": None}
    return {
        k: round(sum(a[k] or 0.0 for a in absorciones), 1)
        for k in ("bruta_m2", "bruta_uf", "neta_m2", "neta_uf")
    }


def _suma_renta(valores: list) -> float | str | None:
    """Suma una columna de renta que puede traer RENTA_PENDIENTE en algunas
    celdas (Bodegas/Estacionamientos PT) — el total se marca pendiente
    también, para no mezclar un número real con uno que ignora esas
    columnas."""
    if any(v == RENTA_PENDIENTE for v in valores):
        return RENTA_PENDIENTE
    return round(sum(valores), 1)


def _pct_vacancia_uf(renta_mensual, renta_vacante, renta_gracia) -> float | str | None:
    """% vacancia (UF) = renta vacante / (renta mensual + renta vacante +
    renta en gracia). Se propaga RENTA_PENDIENTE si cualquiera de las tres
    partidas está pendiente (Boulevard Bodegas/Estacionamientos)."""
    if RENTA_PENDIENTE in (renta_mensual, renta_vacante, renta_gracia):
        return RENTA_PENDIENTE
    denom = renta_mensual + renta_vacante + renta_gracia
    return round(renta_vacante / denom * 100, 2) if denom else None


def _suma_celdas(celdas: list) -> dict:
    # m2_utiles de cada celda ya es el total (ocupado+vacante, ver _celda);
    # no volver a sumarle m2_vacantes o se duplica.
    m2_utiles = sum(c["m2_utiles"] for c in celdas)
    m2_vacantes = sum(c["m2_vacantes"] for c in celdas)
    pct_vac = round(m2_vacantes / m2_utiles * 100, 2) if m2_utiles else None
    renta_mensual = _suma_renta([c["renta_mensual_uf"] for c in celdas])
    renta_vacante = _suma_renta([c["renta_uf_vacante"] for c in celdas])
    renta_gracia = _suma_renta([c["renta_uf_gracia"] for c in celdas])
    return {
        "m2_utiles": round(m2_utiles, 1), "m2_vacantes": round(m2_vacantes, 1),
        "pct_vacancia_m2": pct_vac,
        "renta_mensual_uf": renta_mensual,
        "renta_uf_vacante": renta_vacante,
        "renta_uf_gracia": renta_gracia,
        "pct_vacancia_uf": _pct_vacancia_uf(renta_mensual, renta_vacante, renta_gracia),
        "absorcion_3m": _suma_absorciones([c["absorcion_3m"] for c in celdas]),
        "absorcion_12m": _suma_absorciones([c["absorcion_12m"] for c in celdas]),
    }


_VACANCIA_TIPOS_EDIFICIO = {"Oficinas", "Locales Comerciales"}  # excluye Bodegas/Estacionamientos

_VACANCIA_TIPO_ROW = {
    "Locales": {"Locales Comerciales"},
    "Oficinas": {"Oficinas"},
    "Edificio": _VACANCIA_TIPOS_EDIFICIO,
}


def _pct_vacancia_edificio(snapshot: dict, edificio: str, fila: str) -> float | None:
    tipos = _VACANCIA_TIPO_ROW[fila]
    filtradas = {
        k: v for k, v in snapshot.items()
        if k[0] == edificio and v["tipo_activo_3"] in tipos
    }
    if not filtradas:
        return None
    m2_total = sum(v["m2"] for v in filtradas.values())
    m2_vac = sum(v["m2"] for v in filtradas.values() if _es_vacante(v["arrendatario"]))
    return round(m2_vac / m2_total * 100, 2) if m2_total else None


def get_vacancia_edificios(activo_key: str, periodo: str, edificios_filas: dict) -> dict | None:
    """% vacancia (m²) por edificio y fila (Locales/Oficinas/Edificio), mes
    actual vs mes anterior. `edificios_filas` = {edificio: [filas]} (ver
    FONDOS_CFG[fondo]["page3"]["vacancia_edificios"]). None si no hay rent
    roll para (activo_key, periodo)."""
    snapshot_actual = _snapshot(activo_key, periodo)
    if not snapshot_actual:
        return None

    periodo_anterior = _meses_atras(periodo, 1)
    snapshot_anterior = _snapshot(activo_key, periodo_anterior)

    out = {}
    for edificio, filas in edificios_filas.items():
        for fila in filas:
            actual = _pct_vacancia_edificio(snapshot_actual, edificio, fila)
            anterior = (
                _pct_vacancia_edificio(snapshot_anterior, edificio, fila)
                if snapshot_anterior else None
            )
            variacion = (
                round(actual - anterior, 2)
                if actual is not None and anterior is not None else None
            )
            out[(edificio, fila)] = {
                "pct_actual": actual,
                "pct_anterior": anterior,
                "variacion": variacion,
            }
    return out


# Grupos/tipos por fondo para la tabla de performance (ver
# FONDOS_CFG[fondo]["page2"]["perf_groups"] en scripts/build_factsheet.py —
# debe calzar 1:1 con los "cols" definidos ahí, sin "Total" que se calcula
# aparte). Clave = activo_key lógico que recibe get_perf_table.
_GRUPOS_TIPOS_POR_FONDO = {
    "PT": {
        "Torre A S.A.": ["Oficinas", "Locales Comerciales", "Bodegas", "Estacionamientos"],
        "Inmob. Boulevard PT SpA": ["Locales Comerciales", "Bodegas", "Estacionamientos"],
    },
    "Apoquindo": {
        "Apoquindo 4501": ["Oficinas", "Locales Comerciales", "Bodegas", "Estacionamientos"],
        "Apoquindo 4700": ["Oficinas", "Locales Comerciales", "Bodegas", "Estacionamientos"],
    },
}


def get_perf_table(activo_key: str, periodo: str) -> dict | None:
    """Devuelve {(grupo, tipo): celda} para el período dado, más
    (grupo, "Total") (sub-columna del grupo, ver FONDOS_CFG[fondo]["page2"]
    ["perf_groups"]) y ("__grand_total__", "Total") para la columna Total
    final de la tabla. None si no hay rent roll ingestado para ese
    (activo_key, periodo) o si el fondo no tiene grupos definidos en
    _GRUPOS_TIPOS_POR_FONDO."""
    grupos_tipos = _GRUPOS_TIPOS_POR_FONDO.get(activo_key)
    if grupos_tipos is None:
        return None

    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    out = {}
    todas_celdas = []
    for grupo, tipos in grupos_tipos.items():
        celdas_edificio = []
        for tipo in tipos:
            celda = _celda(grupo, tipo, snapshot, activo_key, periodo)
            out[(grupo, tipo)] = celda
            todas_celdas.append(celda)
            if tipo in _VACANCIA_TIPOS_EDIFICIO:
                celdas_edificio.append(celda)
        # "Total" es el subtotal de edificio (Oficinas + Locales Comerciales),
        # misma regla de negocio que _detalle_vacancia_por_edificio: excluye
        # Bodegas/Estacionamientos, que no cuentan para la vacancia de edificio.
        out[(grupo, "Total")] = _suma_celdas(celdas_edificio)
    out[("__grand_total__", "Total")] = _suma_celdas(todas_celdas)
    out["_absorcion_3m"] = _absorcion_ventana(activo_key, periodo, 3)
    out["_absorcion_12m"] = _absorcion_ventana(activo_key, periodo, 12)
    return out


def get_rubro_arrendatario(activo_key: str, periodo: str, categorias: list[str]) -> dict | None:
    """Renta mensual ocupada (UF), agrupada por rubro del arrendatario
    (extra_json.tipo_arrendatario), para el gráfico "Composición por Rubro
    del Arrendatario" de la página 2 (ver FONDOS_CFG[fondo]["page2"]
    ["rubro_arrendatario"]). Rubros fuera de esa lista curada (larga cola de
    categorías poco frecuentes) se agrupan en "Otro". Vacantes se excluyen.
    None si no hay rent roll ingestado para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    agg: dict[str, float] = {}
    for v in snapshot.values():
        if _es_vacante(v["arrendatario"]):
            continue
        rubro = v.get("tipo_arrendatario")
        if not rubro or rubro.strip().lower() == "vacante":
            continue
        rubro = rubro.strip()
        if rubro.lower() == "otro":
            rubro = "Otro"
        if rubro not in categorias:
            rubro = "Otro"
        agg[rubro] = agg.get(rubro, 0.0) + _monto_mensual_uf(v)
    return {k: round(v, 1) for k, v in agg.items() if v}


def get_tipo_activo(activo_key: str, periodo: str) -> dict | None:
    """Renta mensual ocupada (UF), agrupada por tipo de activo (Oficinas,
    Locales Comerciales, Estacionamientos, Bodegas — ver v["tipo_activo_3"] en
    _snapshot, vocabulario cerrado fijado por _TIPO_ACTIVO_2_MAP), para el
    donut "Composición por Tipo de Activo" de la página 2 (ver
    FONDOS_CFG[fondo]["page2"]["tipo_activo"]). Vacantes se excluyen. None si
    no hay rent roll ingestado para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    agg: dict[str, float] = {}
    for v in snapshot.values():
        if _es_vacante(v["arrendatario"]):
            continue
        tipo = v.get("tipo_activo_3")
        if not tipo:
            continue
        agg[tipo] = agg.get(tipo, 0.0) + _monto_mensual_uf(v)
    return {k: round(v, 1) for k, v in agg.items() if v}
