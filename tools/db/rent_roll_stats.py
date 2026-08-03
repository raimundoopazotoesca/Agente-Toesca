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
import re
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


def get_vacancia_fondo(activo_key: str, periodo: str) -> dict | None:
    """% vacancia (m²) del fondo completo (todos los edificios agregados,
    Oficinas + Locales Comerciales), mes actual vs mes anterior. Mismo
    criterio que la fila "Edificio" de get_vacancia_edificios pero sin
    filtrar por edificio individual. None si no hay rent roll para
    (activo_key, periodo)."""
    snapshot_actual = _snapshot(activo_key, periodo)
    if not snapshot_actual:
        return None

    periodo_anterior = _meses_atras(periodo, 1)
    snapshot_anterior = _snapshot(activo_key, periodo_anterior)

    def _pct(snapshot):
        filtradas = {k: v for k, v in snapshot.items() if v["tipo_activo_3"] in _VACANCIA_TIPOS_EDIFICIO}
        if not filtradas:
            return None
        m2_total = sum(v["m2"] for v in filtradas.values())
        m2_vac = sum(v["m2"] for v in filtradas.values() if _es_vacante(v["arrendatario"]))
        return round(m2_vac / m2_total * 100, 2) if m2_total else None

    actual = _pct(snapshot_actual)
    anterior = _pct(snapshot_anterior) if snapshot_anterior else None
    variacion = round(actual - anterior, 2) if actual is not None and anterior is not None else None
    return {"pct_actual": actual, "pct_anterior": anterior, "variacion": variacion}


def get_vacancia_fondo_por_tipo(activo_key: str, periodo: str) -> dict | None:
    """% vacancia (m²) del fondo desglosado por tipo de activo (Oficinas /
    Locales Comerciales), mes actual vs mes anterior. Mismo criterio que
    get_vacancia_fondo pero sin agregar los tipos. Usado para la narrativa
    "Vacancia del Fondo" de la página 3 de PT (FONDOS_CFG["PT"]["page3"]
    ["aspectos_mes"]). None si no hay rent roll para (activo_key, periodo)."""
    snapshot_actual = _snapshot(activo_key, periodo)
    if not snapshot_actual:
        return None

    periodo_anterior = _meses_atras(periodo, 1)
    snapshot_anterior = _snapshot(activo_key, periodo_anterior)

    def _pct_por_tipo(snapshot):
        out = {}
        for tipo in _VACANCIA_TIPOS_EDIFICIO:
            filtradas = {k: v for k, v in snapshot.items() if v["tipo_activo_3"] == tipo}
            if not filtradas:
                out[tipo] = None
                continue
            m2_total = sum(v["m2"] for v in filtradas.values())
            m2_vac = sum(v["m2"] for v in filtradas.values() if _es_vacante(v["arrendatario"]))
            out[tipo] = round(m2_vac / m2_total * 100, 2) if m2_total else None
        return out

    por_tipo_actual = _pct_por_tipo(snapshot_actual)
    por_tipo_anterior = _pct_por_tipo(snapshot_anterior) if snapshot_anterior else {t: None for t in _VACANCIA_TIPOS_EDIFICIO}

    out = {}
    for tipo in _VACANCIA_TIPOS_EDIFICIO:
        actual = por_tipo_actual.get(tipo)
        anterior = por_tipo_anterior.get(tipo)
        variacion = round(actual - anterior, 2) if actual is not None and anterior is not None else None
        out[tipo] = {"pct_actual": actual, "pct_anterior": anterior, "variacion": variacion}
    return out


def get_gla_edificios(activo_key: str, edificios: list[str]) -> dict | None:
    """m² totales (ocupados + vacantes, Oficinas + Locales Comerciales — mismo
    criterio de área arrendable que _VACANCIA_TIPOS_EDIFICIO, excluye
    Bodegas/Estacionamientos) por edificio, para el donut "GLA (m²)" de la
    página 3 de Apo (layout "edificio"). A diferencia de los donuts de PT
    (ingresos/GLA por arrendatario), este SÍ es estático: la superficie de un
    edificio no cambia mes a mes, así que se calcula una sola vez con el
    período más reciente disponible (no varía con el selector de período del
    fact sheet). None si no hay rent roll ingestado para activo_key."""
    periodos = _periodos_disponibles(activo_key)
    if not periodos:
        return None
    snapshot = _snapshot(activo_key, periodos[-1])
    if not snapshot:
        return None

    out: dict[str, float] = {}
    for k, v in snapshot.items():
        if k[0] not in edificios or v["tipo_activo_3"] not in _VACANCIA_TIPOS_EDIFICIO:
            continue
        out[k[0]] = out.get(k[0], 0.0) + (v["m2"] or 0.0)
    return {k: round(v, 1) for k, v in out.items() if v}


_PISO_RE = re.compile(r"^(\d+)")


def _piso_de_unidad(unidad: str) -> str | None:
    """Extrae el piso desde el código de unidad del rent roll (ej. "703" ->
    "7", "1301" -> "13", "401 #2" -> "4"). Los 2 últimos dígitos son la
    posición dentro del piso (nomenclatura JLL estándar en Apo4501/Apo4700);
    solo se usa para los gráficos "Status Actual Oficinas" de la página 3 de
    Apo (layout "edificio"). None si la unidad no sigue esa nomenclatura
    (ej. locales que usan letras, "1A")."""
    m = _PISO_RE.match(unidad.strip())
    if not m:
        return None
    digitos = m.group(1)
    return digitos[:-2] if len(digitos) > 2 else digitos


def get_status_oficinas(activo_key: str, periodo: str, edificios: list[str]) -> dict | None:
    """{edificio: {"pisos": [{piso, m2, ocupado_pct, unidades: [{unidad, m2,
    vacante, arrendatario, renta_uf}]}] (ordenados de piso más alto a más
    bajo), "ocupacion_pct": float}} para el gráfico "Status Actual Oficinas
    por Activo" de la página 3 de Apo (layout "edificio") — la forma del
    edificio (ancho de cada piso, proporcional a su m² real) no cambia mes a
    mes, solo el % ocupado y el detalle de arrendatarios de cada piso.
    "unidades" alimenta el tooltip por piso (arrendatario, UF/m²/mes, m²
    totales de cada unidad). None si no hay rent roll para (activo_key,
    periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    out = {}
    for ed in edificios:
        pisos: dict[str, dict] = {}
        for (edificio, unidad), v in snapshot.items():
            if edificio != ed or v["tipo_activo_3"] != "Oficinas":
                continue
            piso = _piso_de_unidad(unidad)
            if piso is None:
                continue
            d = pisos.setdefault(piso, {"m2": 0.0, "m2_vac": 0.0, "unidades": []})
            m2 = v["m2"] or 0.0
            vacante = _es_vacante(v["arrendatario"])
            d["m2"] += m2
            if vacante:
                d["m2_vac"] += m2
            d["unidades"].append({
                "unidad": unidad,
                "m2": round(m2, 1),
                "vacante": vacante,
                "arrendatario": v["arrendatario"] if not vacante else None,
                "renta_uf": round(v["renta_uf"], 2) if not vacante else 0.0,
            })
        if not pisos:
            continue
        m2_total = sum(d["m2"] for d in pisos.values())
        m2_vac_total = sum(d["m2_vac"] for d in pisos.values())
        pisos_out = [
            {
                "piso": p,
                "m2": round(d["m2"], 1),
                "ocupado_pct": round(100 * (d["m2"] - d["m2_vac"]) / d["m2"], 1) if d["m2"] else 0.0,
                "unidades": sorted(d["unidades"], key=lambda u: u["unidad"]),
            }
            for p, d in sorted(pisos.items(), key=lambda kv: int(kv[0]), reverse=True)
        ]
        out[ed] = {
            "pisos": pisos_out,
            "ocupacion_pct": round(100 * (m2_total - m2_vac_total) / m2_total, 1) if m2_total else 0.0,
        }
    return out or None


def get_status_locales(activo_key: str, periodo: str, edificios: list[str]) -> dict | None:
    """{edificio: {"locales": [{unidad, m2, vacante}] (ordenados de mayor a
    menor m²), "ocupacion_pct": float}} para el gráfico "Status Actual
    Locales por Activo" de la página 3 de Apo (layout "edificio") — el
    tamaño relativo de cada local en el treemap es proporcional a su m² real
    (no cambia mes a mes), solo el color (ocupado/vacante). None si no hay
    rent roll para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    out = {}
    for ed in edificios:
        locales = []
        for (edificio, unidad), v in snapshot.items():
            if edificio != ed or v["tipo_activo_3"] != "Locales Comerciales":
                continue
            m2 = v["m2"] or 0.0
            if m2 <= 0:
                continue
            vacante = _es_vacante(v["arrendatario"])
            locales.append({
                "unidad": unidad,
                "m2": round(m2, 1),
                "vacante": vacante,
                "arrendatario": v["arrendatario"] if not vacante else None,
                "renta_uf": round(v["renta_uf"], 2) if not vacante else 0.0,
            })
        if not locales:
            continue
        locales.sort(key=lambda l: l["m2"], reverse=True)
        m2_total = sum(l["m2"] for l in locales)
        m2_vac = sum(l["m2"] for l in locales if l["vacante"])
        out[ed] = {
            "locales": locales,
            "ocupacion_pct": round(100 * (m2_total - m2_vac) / m2_total, 1) if m2_total else 0.0,
        }
    return out or None


def get_plano_locales(activo_key: str, periodo: str, edificio: str, unidades: list[str]) -> dict | None:
    """{unidad: {vacante, arrendatario, renta_uf, m2}} para el overlay del
    "Plano Local 100" de la página 4 de PT (ver FONDOS_CFG["PT"]["page4"]
    ["plano"]) — a diferencia de get_status_locales, acá el layout no es un
    treemap ni una silueta calculada: son rectángulos fijos calcados sobre
    una imagen real del plano de arquitectura (ver PLANO_LOCALES_LAYOUT en
    scripts/build_factsheet.py), y solo se necesita el estado de cada unidad
    puntual por su código real (ej. "100-9"), no una lista ordenada. None si
    no hay rent roll para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    out = {}
    for unidad in unidades:
        v = snapshot.get((edificio, unidad))
        if not v:
            continue
        vacante = _es_vacante(v["arrendatario"])
        out[unidad] = {
            "m2": round(v["m2"] or 0.0, 1),
            "vacante": vacante,
            "arrendatario": v["arrendatario"] if not vacante else None,
            "renta_uf": round(v["renta_uf"], 2) if not vacante else 0.0,
        }
    return out or None


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


def _top_n_por_clave(snapshot: dict, clave, valor, top_n: int = 5, otros_label: str = "Otros") -> dict[str, float]:
    """Agrega `valor(v)` de unidades ocupadas agrupando por `clave(v)`,
    quedándose con los `top_n` de mayor valor y sumando el resto en
    `otros_label` — sin lista curada de categorías: el top-N se calcula en
    el momento a partir de los datos, así no queda pegado a nombres/rubros
    de una foto de un mes puntual (arrendatarios y rubros entran/salen con
    el tiempo). Unidades sin `clave(v)` (None/vacío) y vacantes se excluyen.
    Compartido por get_ingresos_arrendatario, get_m2_arrendatario y
    get_rubro_arrendatario."""
    agg: dict[str, float] = {}
    for v in snapshot.values():
        if _es_vacante(v["arrendatario"]):
            continue
        k = clave(v)
        if not k or k.strip().lower() == "vacante":
            continue
        k = k.strip()
        agg[k] = agg.get(k, 0.0) + valor(v)
    items = sorted(((k, v) for k, v in agg.items() if v), key=lambda kv: kv[1], reverse=True)
    out = {k: round(v, 1) for k, v in items[:top_n]}
    resto = items[top_n:]
    if resto:
        out[otros_label] = round(out.get(otros_label, 0.0) + sum(v for _, v in resto), 1)
    return out


def get_ingresos_arrendatario(activo_key: str, periodo: str, top_n: int = 5) -> dict | None:
    """Renta mensual ocupada (UF), agrupada por arrendatario (top-N por
    monto + "Otros"), para el donut "Ingresos (UF/mes)" de la página 3 de PT
    (layout "tenant", ver FONDOS_CFG["PT"]["page3"]["donut_arrendatario"]).
    None si no hay rent roll ingestado para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None
    return _top_n_por_clave(snapshot, lambda v: v["arrendatario"], _monto_mensual_uf, top_n)


def get_m2_arrendatario(activo_key: str, periodo: str, top_n: int = 5) -> dict | None:
    """m² ocupados, agrupados por arrendatario (top-N por m² + "Otros"), para
    el donut "GLA (m²)" de la página 3 de PT (layout "tenant", ver
    FONDOS_CFG["PT"]["page3"]["donut_arrendatario"]) — el top-N por
    superficie no necesariamente coincide con el de renta (arrendatarios
    chicos en renta pueden ocupar más m², y viceversa), por eso se calcula
    aparte. None si no hay rent roll ingestado para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None
    return _top_n_por_clave(snapshot, lambda v: v["arrendatario"], lambda v: v["m2"] or 0.0, top_n)


def get_rubro_arrendatario(activo_key: str, periodo: str, top_n: int = 10) -> dict | None:
    """Renta mensual ocupada (UF), agrupada por rubro del arrendatario
    (extra_json.tipo_arrendatario, top-N por monto + "Otro"), para el
    gráfico "Composición por Rubro del Arrendatario" de la página 2 (ver
    FONDOS_CFG[fondo]["page2"]). Vacantes se excluyen. None si no hay rent
    roll ingestado para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None
    return _top_n_por_clave(
        snapshot, lambda v: v.get("tipo_arrendatario"), _monto_mensual_uf, top_n, otros_label="Otro",
    )


def get_perfil_vencimiento(activo_key: str, periodo: str, edificios: list[str]) -> dict | None:
    """Renta mensual ocupada (UF), agrupada por año de vencimiento de contrato
    y edificio, para el gráfico "Perfil de Vencimiento de Contratos" de la
    página 2 (ver FONDOS_CFG["Apo"/"PT"]["page2"]). El agrupador "edificio" usa
    _ACTIVO2_LABEL para traducir el activo2 crudo del rent roll al label del
    grupo (necesario para PT: "Torre A"->"Torre A S.A.", "Inmob. CdC"->
    "Inmob. Boulevard PT SpA"; para Apo el activo2 ya coincide 1:1). Los años
    se acotan a una
    ventana de 9 buckets partiendo del año del período (report_year..
    report_year+8); todo vencimiento posterior cae en el último bucket
    "{report_year+8}+". Vacantes se excluyen, igual que get_rubro_arrendatario
    / get_tipo_activo.

    También calcula el plazo medio de los contratos vigentes (años restantes
    desde `periodo` hasta `vencimiento`), ponderado por renta mensual UF
    (mismo criterio de ponderación usado en el resto del módulo, ver
    _monto_mensual_uf).

    Devuelve {"por_anio": {edificio: {anio_bucket: uf}}, "anios": [buckets en
    orden], "plazo_medio_anios": float | None}. None si no hay rent roll
    ingestado para (activo_key, periodo)."""
    snapshot = _snapshot(activo_key, periodo)
    if not snapshot:
        return None

    report_year = int(periodo.split("-")[0])
    report_date = f"{periodo}-01"
    anio_max = report_year + 8
    anios = [str(a) for a in range(report_year, anio_max)] + [f"{anio_max}+"]

    por_anio: dict[str, dict[str, float]] = {ed: {a: 0.0 for a in anios} for ed in edificios}
    peso_total = 0.0
    plazo_ponderado = 0.0

    for k, v in snapshot.items():
        if _es_vacante(v["arrendatario"]):
            continue
        edificio = _ACTIVO2_LABEL.get(k[0], k[0])
        if edificio not in por_anio:
            continue
        venc = v.get("vencimiento")
        if not venc:
            continue
        monto = _monto_mensual_uf(v)
        anio_venc = int(str(venc)[:4])
        bucket = str(anio_venc) if anio_venc < anio_max else f"{anio_max}+"
        por_anio[edificio][bucket] = round(por_anio[edificio].get(bucket, 0.0) + monto, 1)

        if venc > report_date and monto:
            dias = (_fecha(venc) - _fecha(report_date)).days
            plazo_ponderado += (dias / 365.0) * monto
            peso_total += monto

    plazo_medio = round(plazo_ponderado / peso_total, 2) if peso_total else None
    return {"por_anio": por_anio, "anios": anios, "plazo_medio_anios": plazo_medio}


def _fecha(s: str):
    from datetime import date
    y, m, d = (int(x) for x in s[:10].split("-"))
    return date(y, m, d)


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
