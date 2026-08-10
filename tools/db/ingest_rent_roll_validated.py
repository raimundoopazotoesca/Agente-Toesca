"""Valida y persiste archivos Rent Roll JLL/TresA (.xlsx) a raw_rent_roll_line.

Ubicación operativa:
SharePoint > Inmobiliario Toesca > Renta Comercial > Rent Rolls.
JLL lo envía Nicole; TresA lo envía Sebastián Bravo.
Generalmente hay que pedirlos e insistir, porque se demoran en mandarlos.

Reusa el parser y las 4 validaciones de tools/rentroll_tools.py y agrega:
  - gate duro: no se puede ingestar si el validador (VAL1-VAL4 o lectura)
    reporta cualquier error
  - diff de absorción vs el snapshot vigente del período anterior en DB
    (altas / bajas / renovaciones / movimientos / cambios de renta), con
    detección de casos raros a confirmar por el usuario (posible renombre de
    arrendatario, saltos grandes de m²/renta, movimientos con caída fuerte
    de renta, unidades que aparecen/desaparecen sin evento claro)
  - persistencia idempotente por file_hash = sha256(bytes del archivo)

No expone CLI; lo consume scripts/ingesta_server (Flask).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "memory" / "agente_toesca_v2.db"

from tools.rentroll_tools import (  # noqa: E402
    _cierre_mes,
    _validar_archivo,
    _read_source_data,
    resolve_rr_activo_key,
    _rr_num,
    _rr_date_str,
    _tabla_val3,
)
from tools.db.connection import get_conn_for  # noqa: E402
from tools.db import repo_audit, repo_rent_roll  # noqa: E402

RENOMBRE_UMBRAL = 0.3          # levenshtein(a,b)/max(len) por debajo de esto -> "posible renombre"
DELTA_M2_WARN = 0.02            # 2% de variación de m2 totales por activo
DELTA_RENTA_WARN = 0.05         # 5% de variación de renta UF total por activo
CAIDA_RENTA_MOVIMIENTO = 0.8    # renta nueva < 80% de la anterior en un movimiento


# ── Utilidades de fecha/periodo ──────────────────────────────────────────────

def _periodo_anterior(periodo: str) -> str:
    y, m = periodo.split("-")
    y, m = int(y), int(m)
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def _cierre_from_periodo(periodo: str):
    y, m = periodo.split("-")
    return _cierre_mes(int(y), int(m))


def _renta_gracia_calculada(rec: dict, periodo: str) -> float:
    """Renta en gracia real del mes: si 'Inicio Pago Renta' del contrato es
    posterior al cierre del período reportado, el arrendatario todavía no
    empieza a pagar (sigue en gracia) y la renta esperada ponderada de ese mes
    completo está en gracia. Si ya empezó a pagar (fecha pasada o del mismo
    mes), no hay gracia — no se usa la columna "Renta en gracia (UF)" de JLL
    tal cual porque no refleja esta regla (confirmado con el usuario
    2026-07-29)."""
    inicio_pago = rec.get("Inicio Pago Renta")
    if isinstance(inicio_pago, datetime):
        inicio_pago = inicio_pago.date()
    if not isinstance(inicio_pago, date):
        return 0.0
    if inicio_pago > _cierre_from_periodo(periodo):
        return _rr_num(rec.get("Renta Esperada Ponderada (UF/mes)")) or 0.0
    return 0.0


# ── Similaridad de strings (para detectar renombres de arrendatario) ────────

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _nombre_similar(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b or a == b:
        return False
    dist = _levenshtein(a, b)
    return dist / max(len(a), len(b)) < RENOMBRE_UMBRAL


def _es_vacante(arrendatario) -> bool:
    return not arrendatario or "vacante" in str(arrendatario).lower()


# "Tipo Activo 2 (no va vacante)" viene en singular y SIEMPRE trae el tipo real
# (a diferencia de "Tipo Activo 3", que en unidades vacantes puede venir pisado
# con el literal "Vacante"/"vacante" y perder la clasificación real). Se prioriza
# sobre "Tipo Activo 3" para clasificar oficinas/locales/bodegas/estacionamientos.
_TIPO_ACTIVO_2_MAP = {
    "Oficina": "Oficinas",
    "Local": "Locales Comerciales",
    "Bodega": "Bodegas",
    "Estacionamiento": "Estacionamientos",
}

# Tipos que cuentan para la vacancia "de edificio" (excluye bodegas/estacionamientos,
# que tienen dinámica de ocupación distinta y distorsionan el % si se mezclan).
_TIPOS_VACANCIA_EDIFICIO = ("Oficinas", "Locales Comerciales")


def _tipo_real(tipo_activo_2, tipo_activo_3) -> str | None:
    if tipo_activo_2:
        return _TIPO_ACTIVO_2_MAP.get(tipo_activo_2, tipo_activo_2)
    return tipo_activo_3


def _monto_mensual_uf(rec: dict) -> float:
    """raw_rent_roll_line.renta_uf es una TASA (UF/m²/mes), no un monto total.
    El monto mensual de una unidad = tasa * m2."""
    m2 = rec.get("m2") or 0.0
    tasa = rec.get("renta_uf") or 0.0
    return m2 * tasa


# ── Snapshots (dict {(activo2, unidad): {...}}) ──────────────────────────────

def _snapshot_from_db(activo_key: str, periodo: str) -> dict:
    conn = get_conn_for(str(DB_PATH))
    try:
        rows = repo_rent_roll.list_by_periodo(conn, activo_key, periodo)
        out = {}
        for r in rows:
            try:
                extra = json.loads(r["extra_json"] or "{}")
            except (TypeError, ValueError):
                extra = {}
            key = (extra.get("activo2") or "", r["unidad"])
            out[key] = {
                "arrendatario": r["arrendatario"],
                "m2": r["m2"],
                "renta_uf": r["renta_uf"],
                "vencimiento": r["vencimiento"],
                "tipo": _tipo_real(extra.get("tipo_activo_2"), extra.get("tipo_activo_3")),
            }
        return out
    finally:
        conn.close()


def _snapshot_from_source(activo_key: str, source_data: dict) -> dict:
    out = {}
    for (activo2, detalle), rec in source_data.items():
        activo1 = str(rec.get("Activo1") or "").strip()
        if resolve_rr_activo_key(activo1, activo2) != activo_key:
            continue
        arr = rec.get("Arrendatario")
        out[(activo2, detalle)] = {
            "arrendatario": str(arr).strip() if arr is not None else None,
            "m2": _rr_num(rec.get("Area Arrendable (m2)")),
            "renta_uf": _rr_num(rec.get("Renta Fija (UF/m2 /mes)")),
            "vencimiento": _rr_date_str(rec.get("Término del Contrato")),
            "tipo": _tipo_real(
                rec.get("Tipo Activo 2 (no va vacante)"), rec.get("Tipo Activo 3")
            ),
        }
    return out


# ── Clasificación de eventos por unidad ──────────────────────────────────────

def _clasificar_evento(antes: dict | None, ahora: dict | None) -> dict:
    """Clasifica el cambio de una unidad (activo2, unidad) entre dos snapshots."""
    vac_antes = antes is None or _es_vacante(antes.get("arrendatario"))
    vac_ahora = ahora is None or _es_vacante(ahora.get("arrendatario"))

    if vac_antes and not vac_ahora:
        return {"evento": "alta"}
    if not vac_antes and vac_ahora:
        return {"evento": "baja"}
    if vac_antes and vac_ahora:
        return {"evento": "sin_cambio"}

    # Ambos ocupados
    arr_antes = (antes.get("arrendatario") or "").strip()
    arr_ahora = (ahora.get("arrendatario") or "").strip()

    if arr_antes == arr_ahora:
        venc_antes, venc_ahora = antes.get("vencimiento"), ahora.get("vencimiento")
        if venc_antes and venc_ahora and venc_ahora > venc_antes:
            return {"evento": "renovacion", "vencimiento_antes": venc_antes, "vencimiento_ahora": venc_ahora}
        if antes.get("renta_uf") != ahora.get("renta_uf"):
            return {
                "evento": "cambio_renta",
                "renta_antes": antes.get("renta_uf"),
                "renta_ahora": ahora.get("renta_uf"),
            }
        return {"evento": "sin_cambio"}

    # Distinto arrendatario en la misma unidad -> movimiento
    evento = {"evento": "movimiento", "arrendatario_antes": arr_antes, "arrendatario_ahora": arr_ahora}
    if _nombre_similar(arr_antes, arr_ahora):
        evento["posible_renombre"] = True
    renta_antes, renta_ahora = antes.get("renta_uf"), ahora.get("renta_uf")
    if renta_antes and renta_ahora and renta_ahora < renta_antes * CAIDA_RENTA_MOVIMIENTO:
        evento["caida_renta_fuerte"] = True
    return evento


def _totales_activo(snapshot: dict) -> dict:
    """Totales por activo. renta_uf_total/vacante son montos mensuales (UF/mes),
    calculados como tasa (UF/m²/mes) * m² por unidad — no una suma de tasas."""
    m2_total = 0.0
    m2_ocupado = 0.0
    m2_vacante = 0.0
    renta_total = 0.0
    renta_vacante = 0.0
    for rec in snapshot.values():
        m2 = rec.get("m2") or 0.0
        monto = _monto_mensual_uf(rec)
        m2_total += m2
        if _es_vacante(rec.get("arrendatario")):
            m2_vacante += m2
            renta_vacante += monto
        else:
            m2_ocupado += m2
            renta_total += monto
    pct_vacancia = (m2_vacante / m2_total * 100) if m2_total else None
    return {
        "m2_total": round(m2_total, 2),
        "m2_ocupado": round(m2_ocupado, 2),
        "m2_vacante": round(m2_vacante, 2),
        "pct_vacancia": round(pct_vacancia, 2) if pct_vacancia is not None else None,
        "renta_uf_total": round(renta_total, 2),
        "renta_uf_vacante": round(renta_vacante, 2),
    }


def _detalle_vacancia_por_edificio(snapshot: dict) -> dict:
    """{edificio: {"Oficinas": totales, "Locales Comerciales": totales, "Total": totales}}.

    "Total" = Oficinas + Locales Comerciales únicamente (excluye bodegas y
    estacionamientos, que no cuentan para la vacancia de edificio)."""
    edificios = sorted({k[0] for k in snapshot.keys() if k[0]})
    out = {}
    for edificio in edificios:
        recs_edificio = [v for k, v in snapshot.items() if k[0] == edificio]
        por_tipo = {
            tipo: _totales_activo({("_", str(i)): r for i, r in enumerate(
                [rec for rec in recs_edificio if rec.get("tipo") == tipo]
            )})
            for tipo in _TIPOS_VACANCIA_EDIFICIO
        }
        recs_total = [rec for rec in recs_edificio if rec.get("tipo") in _TIPOS_VACANCIA_EDIFICIO]
        por_tipo["Total"] = _totales_activo({("_", str(i)): r for i, r in enumerate(recs_total)})
        out[edificio] = por_tipo
    return out


_SUFIJO_DUPLICADO = re.compile(r" #\d+$")


def _piso_base(detalle: str) -> str:
    """'Piso 6 #2' -> 'Piso 6' (agrupa unidades subdivididas del mismo piso/zona,
    ver sufijo agregado en tools.rentroll_tools._read_source_data)."""
    return _SUFIJO_DUPLICADO.sub("", detalle or "")


def _vacancia_por_piso(activo_key: str, source_data: dict) -> dict:
    """{(edificio, piso_base): totales} restringido a Oficinas+Locales Comerciales
    (misma regla de negocio que _detalle_vacancia_por_edificio)."""
    snap = _snapshot_from_source(activo_key, source_data)
    por_piso: dict[tuple[str, str], list] = {}
    for (edificio, detalle), rec in snap.items():
        if rec.get("tipo") not in _TIPOS_VACANCIA_EDIFICIO:
            continue
        por_piso.setdefault((edificio, _piso_base(detalle)), []).append(rec)
    return {
        key: _totales_activo({("_", str(i)): r for i, r in enumerate(recs)})
        for key, recs in por_piso.items()
    }


def _persistir_vacancia_por_piso(conn, activo_key: str, periodo: str, source_data: dict, run_id: int) -> None:
    """Guarda el % de vacancia por piso en derived_kpi (entidad_tipo='activo').
    No se muestra en el preview de ingesta; lo consume el fact sheet."""
    totales = _vacancia_por_piso(activo_key, source_data)
    for (edificio, piso), t in totales.items():
        entidad_key = f"{activo_key}::{edificio}::{piso}"
        conn.execute(
            "INSERT INTO derived_kpi "
            "(entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula, ingest_run_id) "
            "VALUES ('activo', ?, ?, 'vacancia_pct_piso', ?, '%', 'rent_roll_piso', ?) "
            "ON CONFLICT(entidad_tipo, entidad_key, periodo, kpi, variante) DO UPDATE SET "
            "valor=excluded.valor, ingest_run_id=excluded.ingest_run_id, computed_at=datetime('now')",
            (entidad_key, periodo, t["pct_vacancia"], run_id),
        )
        conn.execute(
            "INSERT INTO derived_kpi "
            "(entidad_tipo, entidad_key, periodo, kpi, valor, unidad, formula, ingest_run_id) "
            "VALUES ('activo', ?, ?, 'vacancia_m2_piso', ?, 'm2', 'rent_roll_piso', ?) "
            "ON CONFLICT(entidad_tipo, entidad_key, periodo, kpi, variante) DO UPDATE SET "
            "valor=excluded.valor, ingest_run_id=excluded.ingest_run_id, computed_at=datetime('now')",
            (entidad_key, periodo, t["m2_vacante"], run_id),
        )


def vacancia_consolidada_fondo(fondo_key: str, periodo: str) -> dict:
    """Vacancia de Oficinas+Locales Comerciales consolidada a nivel fondo,
    sumando los activos (edificios) de raw_rent_roll_line que pertenecen a
    ese fondo en dim_activo. Cálculo al vuelo, no se persiste (barato y no
    vale la pena cachear vs. el riesgo de quedar desincronizado)."""
    conn = get_conn_for(str(DB_PATH))
    try:
        activo_keys = [
            r[0] for r in conn.execute(
                "SELECT activo_key FROM dim_activo WHERE fondo_key=?", (fondo_key,)
            ).fetchall()
        ]
    finally:
        conn.close()

    recs = []
    for activo_key in activo_keys:
        snap = _snapshot_from_db(activo_key, periodo)
        recs.extend(v for v in snap.values() if v.get("tipo") in _TIPOS_VACANCIA_EDIFICIO)

    totales = _totales_activo({("_", str(i)): r for i, r in enumerate(recs)})
    return {"fondo_key": fondo_key, "periodo": periodo, "activos": activo_keys, **totales}


# Label de grupo para activos que se muestran consolidados en el preview
# (varios edificios del mismo fondo). Fondos con un solo activo en el archivo
# (ej. TRI con solo Apo3001) se muestran con el nombre del activo mismo.
_GRUPO_PREVIEW_LABEL = {"Apo": "Apoquindo", "PT": "PT"}


def _sumar_totales(lista: list[dict]) -> dict:
    m2_total = sum(t["m2_total"] for t in lista)
    m2_ocupado = sum(t["m2_ocupado"] for t in lista)
    m2_vacante = sum(t["m2_vacante"] for t in lista)
    renta_total = sum(t["renta_uf_total"] for t in lista)
    renta_vacante = sum(t["renta_uf_vacante"] for t in lista)
    pct_vacancia = (m2_vacante / m2_total * 100) if m2_total else None
    return {
        "m2_total": round(m2_total, 2),
        "m2_ocupado": round(m2_ocupado, 2),
        "m2_vacante": round(m2_vacante, 2),
        "pct_vacancia": round(pct_vacancia, 2) if pct_vacancia is not None else None,
        "renta_uf_total": round(renta_total, 2),
        "renta_uf_vacante": round(renta_vacante, 2),
    }


def _grupos_preview(activos: list[str], diffs: dict) -> list[dict]:
    """Agrupa los activos por fondo para el preview (ej. Apo4501+Apo4700 →
    'Apoquindo', Torre A+Boulevard → 'PT'), con el detalle de cada activo
    anidado y los totales consolidados (Oficinas+Locales) sumados."""
    conn = get_conn_for(str(DB_PATH))
    try:
        fondo_de = {}
        for a in activos:
            row = conn.execute("SELECT fondo_key FROM dim_activo WHERE activo_key=?", (a,)).fetchone()
            fondo_de[a] = row[0] if row else None
    finally:
        conn.close()

    por_fondo: dict[str | None, list[str]] = {}
    for a, f in fondo_de.items():
        por_fondo.setdefault(f, []).append(a)

    def _total_oficinas_locales(d: dict, periodo_key: str) -> dict:
        # Cada activo (post-refactor) es un solo edificio, pero se itera por
        # si acaso para no asumir cardinalidad.
        edificios = d["detalle_vacancia"][periodo_key]
        return _sumar_totales([tipos["Total"] for tipos in edificios.values()]) if edificios \
            else _sumar_totales([])

    grupos = []
    for fondo, acts in por_fondo.items():
        acts = sorted(acts)
        label = acts[0] if len(acts) == 1 else _GRUPO_PREVIEW_LABEL.get(fondo, fondo or "Otros")
        grupos.append({
            "label": label,
            "activos": acts,
            "totales": {
                "periodo_actual": _sumar_totales(
                    [_total_oficinas_locales(diffs[a], "periodo_actual") for a in acts]
                ),
                "periodo_anterior": _sumar_totales(
                    [_total_oficinas_locales(diffs[a], "periodo_anterior") for a in acts]
                ),
            },
        })
    return sorted(grupos, key=lambda g: g["label"])


def diff_absorcion(activo_key: str, periodo: str, source_data: dict) -> dict:
    """Compara el snapshot nuevo (del archivo) vs el vigente en DB para
    (activo_key, periodo_anterior). Devuelve eventos + totales + casos raros.
    """
    periodo_prev = _periodo_anterior(periodo)
    snap_prev = _snapshot_from_db(activo_key, periodo_prev)
    snap_nuevo = _snapshot_from_source(activo_key, source_data)

    eventos = {"alta": [], "baja": [], "renovacion": [], "movimiento": [], "cambio_renta": []}
    casos_raros = []

    if not snap_prev:
        # Primera ingesta del activo: no hay nada contra qué comparar, así que
        # no existe absorción real todavía (todo "alta" sería ruido, no un
        # movimiento del mes).
        return {
            "activo_key": activo_key,
            "periodo": periodo,
            "periodo_anterior": periodo_prev,
            "tiene_snapshot_anterior": False,
            "eventos": eventos,
            "casos_raros": casos_raros,
            "totales": {
                "periodo_anterior": _totales_activo(snap_prev),
                "periodo_actual": _totales_activo(snap_nuevo),
            },
            "detalle_vacancia": {
                "periodo_anterior": _detalle_vacancia_por_edificio(snap_prev),
                "periodo_actual": _detalle_vacancia_por_edificio(snap_nuevo),
            },
            "absorcion": {"bruta_m2": 0.0, "bruta_uf": 0.0, "neta_m2": 0.0, "neta_uf": 0.0},
        }

    todas_keys = set(snap_prev.keys()) | set(snap_nuevo.keys())
    for key in sorted(todas_keys):
        antes = snap_prev.get(key)
        ahora = snap_nuevo.get(key)
        clasif = _clasificar_evento(antes, ahora)
        ev = clasif["evento"]
        if ev == "sin_cambio":
            continue
        activo2, unidad = key
        item = {"activo2": activo2, "unidad": unidad, **clasif}
        if ev in eventos:
            eventos[ev].append(item)

        if clasif.get("posible_renombre"):
            casos_raros.append({
                "tipo": "posible_renombre",
                "activo2": activo2,
                "unidad": unidad,
                "detalle": f"'{clasif['arrendatario_antes']}' -> '{clasif['arrendatario_ahora']}' "
                           "podría ser el mismo arrendatario (nombre similar). Si es así, no es "
                           "un movimiento real de absorción.",
            })
        if clasif.get("caida_renta_fuerte"):
            casos_raros.append({
                "tipo": "caida_renta_fuerte",
                "activo2": activo2,
                "unidad": unidad,
                "detalle": f"Renta bajó de {clasif.get('renta_antes')} a {clasif.get('renta_ahora')} "
                           "UF/m² en el movimiento — verificar que no sea un error de tipeo.",
            })

    unidades_desaparecidas = [
        k for k in snap_prev.keys() - snap_nuevo.keys()
        if not _es_vacante(snap_prev[k].get("arrendatario"))
    ]
    for (activo2, unidad) in unidades_desaparecidas:
        casos_raros.append({
            "tipo": "unidad_desaparecio_del_archivo",
            "activo2": activo2,
            "unidad": unidad,
            "detalle": "Esta unidad estaba ocupada el mes anterior y la fila ya no existe en el "
                       "archivo nuevo (se contabilizó como baja; verificar que no sea fusión, "
                       "subdivisión o cambio de nomenclatura de la unidad).",
        })

    m2_antes = sum((r.get("m2") or 0.0) for r in snap_prev.values())
    m2_ahora = sum((r.get("m2") or 0.0) for r in snap_nuevo.values())
    renta_antes = sum(_monto_mensual_uf(r) for r in snap_prev.values())
    renta_ahora = sum(_monto_mensual_uf(r) for r in snap_nuevo.values())
    if m2_antes and abs(m2_ahora - m2_antes) / m2_antes > DELTA_M2_WARN:
        casos_raros.append({
            "tipo": "delta_m2_total_activo",
            "activo2": None,
            "unidad": None,
            "detalle": f"m² arrendables totales de {activo_key} cambiaron de {m2_antes:.1f} a "
                       f"{m2_ahora:.1f} ({(m2_ahora / m2_antes - 1) * 100:+.1f}%).",
        })
    if renta_antes and abs(renta_ahora - renta_antes) / renta_antes > DELTA_RENTA_WARN:
        casos_raros.append({
            "tipo": "delta_renta_total_activo",
            "activo2": None,
            "unidad": None,
            "detalle": f"Renta UF total de {activo_key} cambió de {renta_antes:.1f} a "
                       f"{renta_ahora:.1f} ({(renta_ahora / renta_antes - 1) * 100:+.1f}%).",
        })

    absorcion_bruta_m2 = sum((snap_nuevo[k]["m2"] or 0.0) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["alta"]
    ] if k in snap_nuevo)
    absorcion_bruta_uf = sum(_monto_mensual_uf(snap_nuevo[k]) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["alta"]
    ] if k in snap_nuevo)
    absorcion_baja_m2 = sum((snap_prev[k]["m2"] or 0.0) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["baja"]
    ] if k in snap_prev)
    absorcion_baja_uf = sum(_monto_mensual_uf(snap_prev[k]) for k in [
        (e["activo2"], e["unidad"]) for e in eventos["baja"]
    ] if k in snap_prev)

    return {
        "activo_key": activo_key,
        "periodo": periodo,
        "periodo_anterior": periodo_prev,
        "tiene_snapshot_anterior": bool(snap_prev),
        "eventos": eventos,
        "casos_raros": casos_raros,
        "totales": {
            "periodo_anterior": _totales_activo(snap_prev),
            "periodo_actual": _totales_activo(snap_nuevo),
        },
        "detalle_vacancia": {
            "periodo_anterior": _detalle_vacancia_por_edificio(snap_prev),
            "periodo_actual": _detalle_vacancia_por_edificio(snap_nuevo),
        },
        "absorcion": {
            "bruta_m2": round(absorcion_bruta_m2, 2),
            "bruta_uf": round(absorcion_bruta_uf, 2),
            "neta_m2": round(absorcion_bruta_m2 - absorcion_baja_m2, 2),
            "neta_uf": round(absorcion_bruta_uf - absorcion_baja_uf, 2),
        },
    }


# ── Validación (gate duro) ────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.ok = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.data: dict = {}

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.ok = False

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, **self.data}


_ERROR_LABELS = {
    "lectura": "Error de lectura",
    "val1_vacantes": "VAL1 — Coherencia de vacantes",
    "val2_absorcion": "VAL2 — Movimientos sin registro en Absorción",
    "val3_escalonada": "VAL3 — Renta escalonada no coincide",
    "val4_terminos": "VAL4 — Contratos con fecha de término vencida",
    "val5_renta_vacante": "VAL5 — Celda vacante sin Renta Fija (UF/m2/mes)",
}


def _flatten_validator_errors(errores: dict) -> list[str]:
    """Convierte el dict de _validar_archivo en mensajes legibles para el gate duro."""
    out = []
    if "lectura" in errores:
        out.append(f"{_ERROR_LABELS['lectura']}: {errores['lectura']}")
        return out
    for key in ("val1_vacantes", "val2_absorcion", "val3_escalonada", "val4_terminos"):
        rows = errores.get(key)
        if not rows:
            continue
        label = _ERROR_LABELS[key]
        out.append(f"{label}: {len(rows)} caso(s) — no se puede ingestar hasta corregir el archivo fuente.")
    return out


def _flatten_validator_warnings(errores: dict) -> list[str]:
    """VAL5 (celda vacante sin Renta Fija) no bloquea la ingesta — el proveedor
    frecuentemente omite la renta esperada de mercado para locales vacantes y
    exigirla como gate duro dejaba fondos enteros sin poder actualizar su rent
    roll (caso Viña Centro mayo/junio 2026, confirmado con el usuario
    2026-08-10). Se ingesta igual con renta_uf=0 para esas unidades y se avisa
    para seguimiento con el proveedor."""
    rows = errores.get("val5_renta_vacante")
    if not rows:
        return []
    return [f"{_ERROR_LABELS['val5_renta_vacante']}: {len(rows)} caso(s) — se ingestó con renta vacante en 0; pedir al proveedor la renta esperada de mercado."]


def _format_errores_detalle(errores: dict) -> str:
    """Formatea los errores de _validar_archivo como texto plano detallado,
    listo para que el usuario copie y pegue en un correo al proveedor."""
    parts = []
    if "val1_vacantes" in errores:
        parts.append("Inconsistencia en columna Vacante:")
        for e in errores["val1_vacantes"]:
            v = e["valores"]
            parts.append(
                f"  Fila {e['fila']}: Tipo Activo 1={v['Tipo Activo 1']} | "
                f"Tipo Activo 3={v['Tipo Activo 3']} | "
                f"Arrendatario={v['Arrendatario']} | "
                f"Tipo Arrendatario={v['Tipo Arrendatario']}"
            )
            parts.append(
                "  → Si el espacio está vacante, debería marcarse como 'Vacante' en todas esas columnas."
            )
        parts.append("")
    if "val2_absorcion" in errores:
        parts.append("Movimientos sin registro en Absorción:")
        for e in errores["val2_absorcion"]:
            parts.append(
                f"  Local {e['local']} ({e['activo']}): "
                f"pasó de [{e['anterior']}] a [{e['actual']}] "
                f"pero no aparece el '{e['movimiento_esperado']}' en la hoja Absorción."
            )
        parts.append("")
    if "val3_escalonada" in errores:
        n = len(errores["val3_escalonada"])
        parts.append(f"Renta escalonada ({n} caso(s)):")
        parts.append("  Arrendatarios con escalones que ya deberían estar vigentes, pero la Renta Fija registrada no coincide:")
        parts.append(_tabla_val3(errores["val3_escalonada"]))
        parts.append("")
    if "val4_terminos" in errores:
        parts.append("Contratos con fecha de término vencida:")
        for e in errores["val4_terminos"]:
            parts.append(f"  Fila {e['fila']} [{e['arrendatario']}]: venció el {e['fecha_termino']}.")
        parts.append("  → ¿Estos contratos están renovados y pendiente de actualizar, o ya terminaron?")
        parts.append("")
    if "val5_renta_vacante" in errores:
        parts.append("Celdas vacantes sin Renta Fija (UF/m2/mes):")
        for e in errores["val5_renta_vacante"]:
            parts.append(f"  Fila {e['fila']} [{e['arrendatario']}]: falta la renta esperada.")
        parts.append("  → Sin este dato no se puede calcular la renta vacante del fact sheet; completar con la renta de mercado esperada para ese espacio.")
        parts.append("")
    return "\n".join(parts).strip()


def _file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _write_tmp(file_bytes: bytes, filename: str) -> str:
    suffix = os.path.splitext(filename)[1] or ".xlsx"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return tmp_path


def validate(file_bytes: bytes, filename: str, periodo: str) -> ValidationResult:
    """Dry-run completo: valida VAL1-VAL4, arma diff de absorción por activo,
    detecta casos raros. No toca la DB (salvo lecturas).
    """
    result = ValidationResult()

    try:
        y, m = periodo.split("-")
        int(y), int(m)
    except (ValueError, AttributeError):
        result.add_error(f"periodo {periodo!r} inválido, se espera 'YYYY-MM'")
        return result

    tmp_path = _write_tmp(file_bytes, filename)
    try:
        cierre = _cierre_from_periodo(periodo)
        val = _validar_archivo(tmp_path, cierre)
        errores = val.get("errores", {})
        for msg in _flatten_validator_errors(errores):
            result.add_error(msg)
        for msg in _flatten_validator_warnings(errores):
            result.warnings.append(msg)

        if not result.ok:
            result.data = {"periodo": periodo, "filename": val.get("archivo"), "errores_detalle": errores}
            if "lectura" not in errores:
                result.data["errores_formateados"] = _format_errores_detalle(errores)
            return result

        source_data = _read_source_data(tmp_path)
        if not source_data:
            result.add_error("No se pudieron leer filas de la hoja 'Rent Roll' (¿formato distinto al esperado?)")
            return result

        activos_presentes = sorted({
            resolve_rr_activo_key(str(rec.get("Activo1") or "").strip(), activo2)
            for (activo2, _detalle), rec in source_data.items()
            if resolve_rr_activo_key(str(rec.get("Activo1") or "").strip(), activo2)
        })
        if not activos_presentes:
            result.add_error("No se reconoció ningún activo mapeable (Activo1) en el archivo.")
            return result

        diffs = {activo: diff_absorcion(activo, periodo, source_data) for activo in activos_presentes}

        casos_raros_total = sum(len(d["casos_raros"]) for d in diffs.values())
        if casos_raros_total:
            result.warnings.append(
                f"{casos_raros_total} caso(s) fuera de lo común detectados en el diff de absorción — "
                "revisar y confirmar antes de ingestar."
            )
        for activo, d in diffs.items():
            if not d["tiene_snapshot_anterior"]:
                result.warnings.append(
                    f"{activo}: no hay snapshot en DB para {d['periodo_anterior']} — no se puede "
                    "calcular absorción vs mes anterior (se ingesta igual, solo faltará el diff)."
                )

        fh = _file_hash(file_bytes)
        conn = get_conn_for(str(DB_PATH))
        try:
            periodos_ocupados = {}
            for activo in activos_presentes:
                rows = conn.execute(
                    "SELECT COUNT(*) FROM raw_rent_roll_line "
                    "WHERE activo_key=? AND periodo=? AND superseded_at IS NULL",
                    (activo, periodo),
                ).fetchone()[0]
                if rows:
                    periodos_ocupados[activo] = rows
        finally:
            conn.close()

        if periodos_ocupados:
            detalle = ", ".join(f"{a} ({n} filas)" for a, n in periodos_ocupados.items())
            result.add_error(
                f"Ya existe un Rent Roll ingestado para {periodo} en: {detalle}. "
                "No se puede reingestar un período ya cargado (evita duplicar vacancia/absorción)."
            )

        result.data = {
            "periodo": periodo,
            "filename": val.get("archivo"),
            "activos": activos_presentes,
            "diffs": diffs,
            "grupos_preview": _grupos_preview(activos_presentes, diffs),
            "n_filas_fuente": len(source_data),
            "file_hash": fh,
            "ya_ingestado": bool(periodos_ocupados),
        }
        return result
    finally:
        os.remove(tmp_path)


def commit(file_bytes: bytes, filename: str, periodo: str) -> dict:
    """Re-valida (defensa en profundidad) y persiste. Lanza ValueError si no pasa el gate."""
    result = validate(file_bytes, filename, periodo)
    if not result.ok:
        raise ValueError("No se puede ingestar: " + "; ".join(result.errors))

    fh = result.data["file_hash"]
    tmp_path = _write_tmp(file_bytes, filename)
    try:
        source_data = _read_source_data(tmp_path)

        conn = get_conn_for(str(DB_PATH))
        try:
            existing = conn.execute(
                "SELECT COUNT(*) FROM raw_rent_roll_line WHERE file_hash=?", (fh,)
            ).fetchone()[0]
            if existing:
                return {"status": "skipped_duplicate", "rows_inserted": 0, "activos": result.data["activos"]}

            run_id = repo_audit.start_ingest_run(
                conn, tool="ingest_rent_roll_validated:jll", source_file=filename, file_hash=fh,
            )

            lines = []
            for i, ((activo2, detalle), rec) in enumerate(source_data.items()):
                activo1 = str(rec.get("Activo1") or "").strip()
                activo_key = resolve_rr_activo_key(activo1, activo2)
                if activo_key is None:
                    continue
                extra = {
                    "activo1": activo1,
                    "activo2": activo2,
                    "tipo_activo_1": rec.get("Tipo Activo 1"),
                    "tipo_activo_2": rec.get("Tipo Activo 2 (no va vacante)"),
                    "tipo_activo_3": rec.get("Tipo Activo 3"),
                    "tipo_arrendatario": rec.get("Tipo Arrendatario"),
                    "rol": rec.get("Rol"),
                    "fecha_inicio": _rr_date_str(rec.get("Fecha Inicio")),
                    "inicio_pago_renta": _rr_date_str(rec.get("Inicio Pago Renta")),
                    # Montos totales (UF/mes) ya calculados por JLL en el rent
                    # roll. renta_gracia es calculada por nosotros (ver
                    # _renta_gracia_calculada), no una copia de la columna JLL.
                    "renta_esperada_total": _rr_num(rec.get("Renta Esperada Total(UF/mes)")),
                    "renta_esperada_ponderada": _rr_num(rec.get("Renta Esperada Ponderada (UF/mes)")),
                    "renta_vacante_jll": _rr_num(rec.get("Renta Vacante (UF)")),
                    "renta_gracia_jll": _rr_num(rec.get("Renta en gracia (UF)")),
                    "renta_gracia": _renta_gracia_calculada(rec, periodo),
                    "renta_real": _rr_num(rec.get("Renta real (UF/mes)")),
                }
                lines.append({
                    "activo_key": activo_key,
                    "periodo": periodo,
                    "unidad": detalle,
                    "arrendatario": (str(rec.get("Arrendatario")).strip()
                                     if rec.get("Arrendatario") is not None else None),
                    "m2": _rr_num(rec.get("Area Arrendable (m2)")),
                    "renta_uf": _rr_num(rec.get("Renta Fija (UF/m2 /mes)")),
                    "vencimiento": _rr_date_str(rec.get("Término del Contrato")),
                    "extra_json": json.dumps(extra, ensure_ascii=False, default=str),
                    "source_file": filename,
                    "source_sheet": "Rent Roll",
                    "source_row": i,
                    "file_hash": fh,
                })

            n = repo_rent_roll.insert_lines(conn, lines, run_id)
            for activo_key in result.data["activos"]:
                _persistir_vacancia_por_piso(conn, activo_key, periodo, source_data, run_id)
            conn.commit()
            repo_audit.finish_ingest_run(conn, run_id, rows_in=len(lines), rows_loaded=n, status="ok")
            return {
                "status": "ok",
                "run_id": run_id,
                "rows_inserted": n,
                "activos": result.data["activos"],
            }
        finally:
            conn.close()
    finally:
        os.remove(tmp_path)
