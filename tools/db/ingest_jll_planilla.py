"""Ingesta de la planilla unica de JLL ("JLL v2").

Contrato `validate()` / `commit()`, como tools/db/ingest_rent_roll_validated.py.
Las diferencias con el camino clasico son deliberadas y estan documentadas en
docs/ y en las migraciones 085-088:

1. MULTI-PERIODO. Un archivo trae varios meses (19 en el del 2026-08-12). El
   gate clasico rechazaba reingestar un periodo ya cargado; aca el archivo
   declara su propio scope y reemplaza lo vivo de ese scope.

2. ATOMICIDAD DE DATOS, AUDITORIA SOBREVIVIENTE. Las cuatro hojas entran en una
   sola transaccion: si una falla, no entra ninguna. Pero el `ingest_run` va en
   una conexion aparte y sobrevive al rollback, porque un intento fallido que no
   deja rastro es indiagnosticable.

3. RETRY. El duplicado se determina por DATOS commiteados, no por la existencia
   de un ingest_run con ese hash. Un fallo transitorio no puede dejar un archivo
   permanentemente imposible de reingestar.

4. RAW-FIRST. Un rubro sin mapping a cuenta_codigo se persiste igual, marcado
   `unmapped` y reportado. Nunca se inventa un mapping ni se descarta una fila.

5. FAIL-LOUD. Las anomalias bloquean el commit salvo que se acepten explicita-
   mente. Nada se descarta en silencio.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sqlite3

from tools.db import derive_er_jll_v2, repo_audit, repo_jll_v2, repo_rent_roll
from tools.db.connection import get_conn_for
from tools.jll_planilla_tools import (
    FUENTE_FORMATO,
    FUENTE_PROVEEDOR,
    HOJA_AUXILIAR,
    HOJA_CARTERA,
    HOJA_RECAUDADO,
    HOJA_RENT_ROLL,
    parse_planilla,
)

TOOL = "ingest_jll_planilla:jll_v2"

# Cada hoja alimenta una tabla y supersede SOLO su propio scope.
_HOJA_A_TABLA = {
    HOJA_RENT_ROLL: "raw_rent_roll_line",
    HOJA_AUXILIAR: "raw_movimiento_contable_line",
    HOJA_CARTERA: "raw_cartera_line",
    HOJA_RECAUDADO: "raw_recaudacion",
}

# Anomalias que impiden persistir la fila y por tanto bloquean el commit
# mientras no se acepten explicitamente. El resto (UG pendiente, renta que no
# reconcilia) se reportan pero no bloquean: son datos utilizables con reserva.
ANOMALIAS_BLOQUEANTES = {
    "portafolio_vacio",
    "portafolio_desconocido",
    "sin_fecha_corte",
    "sin_periodo",
    "estado_invalido",
    "hoja_ausente",
    # Sin monto o sin rubro la fila no es persistible con sentido: monto_uf es
    # NOT NULL y un movimiento sin rubro no puede mapearse ni auditarse. Con
    # INSERT normal (sin OR IGNORE) fallaria en la DB de todos modos; bloquear
    # en validate() lo convierte en un error explicado en vez de un
    # IntegrityError opaco a mitad de la transaccion.
    "sin_monto",
    "sin_rubro",
}

# Rubro del auxiliar -> cuenta del plan de cuentas del ER, por familia de activo.
# Solo se declaran los mapeos CONFIRMADOS contra raw_er_activo_line. Lo que no
# esta aca queda `unmapped`: raw-first, no se adivina.
_FAMILIA = {
    "Apo4501": "APO", "Apo4700": "APO",
    "Boulevard": "PT", "Torre A": "PT",
    "Apo3001": "APO3001",
}

_MAPEO_RUBRO = {
    "Ingreso por arriendo": {"APO": "APO_ING_ARR", "PT": "PT_ING_ARR"},
    "Gastos Comunes Vacancia": {"APO": "APO_GC_VAC", "PT": "PT_GC_VAC",
                                "APO3001": "APO3001_GC"},
    "Comision Corredor": {"APO": "APO_COM_CORR", "PT": "PT_COM_CORR",
                          "APO3001": "APO3001_COM_CORR"},
    "Comisión Corredor": {"APO": "APO_COM_CORR", "PT": "PT_COM_CORR",
                          "APO3001": "APO3001_COM_CORR"},
    "Administracion (JLL)": {"APO": "APO_ADM", "PT": "PT_ADM",
                             "APO3001": "APO3001_ADM"},
    "Administración (JLL)": {"APO": "APO_ADM", "PT": "PT_ADM",
                             "APO3001": "APO3001_ADM"},
    "Contribuciones": {"APO": "APO_CONTRIB", "PT": "PT_CONTRIB",
                       "APO3001": "APO3001_CONTRIB_SOBRETASA"},
    "Gastos Bonos": {"APO": "APO_BONOS_LEG"},
    # Sin mapping confirmado, a proposito:
    #   "Gastos Consultores Asociados (Contabilidad)"
    #   "Otros Gastos"
    #   "Ingreso por intereses"
    # y "Ingreso por arriendo" para Apo3001, que tiene DOS cuentas de ingreso
    # (APO3001_ING_TAIPEI / APO3001_ING_OTROS) sin criterio de desambiguacion.
}

def hash_de_archivo(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# categoria_general de JLL v2 -> tipo_activo_2, la clave que ya leen las vistas
# de vacancia (migracion 084). Escribir esta clave en extra_json mantiene el
# contrato aguas abajo estable: las vistas no cambian de forma.
#
# 'UG' se mapea a si misma a proposito. Su tratamiento esta pendiente de
# confirmacion con negocio, y dejarla caer en el 'Otro' del ELSE de la vista la
# haria invisible dentro de la GLA rentable: una decision tomada por omision.
# La migracion 090 la expone como categoria propia hasta que se resuelva.
_CATEGORIA_A_TIPO = {
    "OFICINA": "Oficina",
    "LOCAL COMERCIAL": "Local",
    "BODEGA": "Bodega",
    "ESTACIONAMIENTO": "Estacionamiento",
    "UG": "UG",
}


def _extra_json_compat(fila: dict) -> str:
    """extra_json para una fila v2, con las claves que esperan las vistas.

    Capa de compatibilidad deliberada: el formato v2 trae `categoria_general` y
    `estado_rent_roll` como columnas propias, pero las vistas de vacancia y
    `v_rent_roll_semantic` leen `extra_json.$.tipo_activo_2`. Traducir aca deja
    el contrato aguas abajo intacto.
    """
    categoria = (fila.get("categoria_general") or "").strip().upper()
    return json.dumps(
        {
            "tipo_activo_2": _CATEGORIA_A_TIPO.get(categoria, categoria or None),
            "categoria_general": fila.get("categoria_general"),
            "estado_rent_roll": fila.get("estado_rent_roll"),
            "estado_contrato": fila.get("estado_contrato"),
            "piso": fila.get("piso"),
            "marca": fila.get("marca"),
            "contrato": fila.get("contrato"),
            "fecha_inicio": fila.get("fecha_inicio"),
            "renta_uf_m2": fila.get("renta_uf_m2"),
        },
        ensure_ascii=False,
    )


def _arrendatario_canonico(fila: dict):
    """'Vacante' es la codificacion canonica de "sin arrendatario" en la DB.

    Las vistas de vacancia detectan vacantes con LOWER(arrendatario)='vacante'
    (migracion 084). En v2 la razon social viene vacia y el dato vive en
    `estado_rent_roll`; traducirlo aqui evita que las vistas cuenten cero
    vacantes en silencio, que es el peor modo de falla posible.
    """
    if (fila.get("estado_rent_roll") or "").strip().lower() == "vacante":
        return "Vacante"
    return fila.get("arrendatario")


def _mapear_cuenta(activo_key: str, rubro: str | None):
    if not rubro:
        return None
    familia = _FAMILIA.get(activo_key)
    if familia is None:
        return None
    return _MAPEO_RUBRO.get(rubro.strip(), {}).get(familia)


def _resumen_anomalias(planilla) -> dict:
    por_tipo = collections.Counter(a.tipo for a in planilla.anomalias)
    return {
        "total": len(planilla.anomalias),
        "por_tipo": dict(por_tipo),
        "bloqueantes": sum(
            n for t, n in por_tipo.items() if t in ANOMALIAS_BLOQUEANTES
        ),
        "muestra": [
            {"hoja": a.hoja, "fila": a.fila, "tipo": a.tipo, "detalle": a.detalle}
            for a in planilla.anomalias[:25]
        ],
    }


def _conflictos_semantica(conn: sqlite3.Connection, planilla) -> list[dict]:
    """Semanticas de renta que quedarian vivas DESPUES de la supersession.

    Invariante (migracion 085): ningun (activo_key, periodo) puede tener filas
    vivas con mas de un valor de `renta_semantica`.

    El gate se evalua sobre el estado POST-supersession, no sobre el actual. El
    commit supersede las filas de (fuente_proveedor='JLL', activo, periodo), asi
    que el historico JLL v1 marcado 'indeterminada' -- que la migracion 089
    etiqueto con fuente_proveedor='JLL' -- desaparece en la misma transaccion y
    NO debe bloquear: es justamente el cutover que este pipeline viene a hacer.

    Lo que si bloquea es la semantica RESIDUAL: filas de otra procedencia
    (TresA, interno) o sin procedencia declarada (NULL, no derivable en la 089),
    que el barrido no alcanza y quedarian conviviendo con 'total_uf'.
    """
    out = []
    scope_rr = planilla.scope_de(planilla.rent_roll)
    for proveedor, activo, periodo in sorted(scope_rr):
        residuales = conn.execute(
            """SELECT DISTINCT renta_semantica FROM raw_rent_roll_line
                WHERE activo_key = ? AND periodo = ? AND superseded_at IS NULL
                  AND renta_semantica <> 'total_uf'
                  AND (fuente_proveedor IS NULL OR fuente_proveedor <> ?)""",
            (activo, periodo, proveedor),
        ).fetchall()
        if residuales:
            out.append({
                "activo_key": activo,
                "periodo": periodo,
                "semanticas_vivas": sorted(r[0] for r in residuales),
                "nota": "filas de otra procedencia que el commit no supersede",
            })
    return out


def _mapping_status(planilla) -> dict:
    mapeados = collections.Counter()
    sin_mapear = collections.Counter()
    for fila in planilla.movimientos.filas:
        cuenta = _mapear_cuenta(fila["activo_key"], fila["rubro"])
        if cuenta:
            mapeados[(fila["activo_key"], fila["rubro"])] += 1
        else:
            sin_mapear[(fila["activo_key"], fila["rubro"])] += 1
    return {
        "mapeados": sum(mapeados.values()),
        "unmapped": sum(sin_mapear.values()),
        "rubros_sin_mapping": sorted(
            {"%s / %s" % (a, r) for a, r in sin_mapear}
        ),
    }


def validate(path: str, db_path: str, source_name: str | None = None) -> dict:
    """Lee el archivo y devuelve el informe previo al commit. No escribe nada.

    `path` es de donde se LEE (puede ser un temporal del upload); `source_name`
    es el nombre real que vera el usuario y que se persiste. Separarlos evita
    que la DB quede con nombres tipo `jll_v2_ab12cd.xlsx`, inutiles para
    auditar de que archivo vino un dato.
    """
    source_name = source_name or os.path.basename(path)
    planilla = parse_planilla(path)
    file_hash = hash_de_archivo(path)
    conn = get_conn_for(db_path)
    try:
        ya_cargado = repo_jll_v2.hash_ya_ingestado_con_exito(conn, file_hash)
        conflictos = _conflictos_semantica(conn, planilla)
        scopes = planilla.scope_por_hoja()
        reemplazos = []
        for hoja, tabla in _HOJA_A_TABLA.items():
            for clave in sorted(scopes.get(hoja, ())):
                if tabla in repo_jll_v2.TABLAS:
                    n = repo_jll_v2.contar_vivas(conn, tabla, clave)
                else:
                    n = conn.execute(
                        "SELECT COUNT(*) FROM raw_rent_roll_line "
                        " WHERE fuente_proveedor=? AND activo_key=? AND periodo=? "
                        "   AND superseded_at IS NULL",
                        clave,
                    ).fetchone()[0]
                if n:
                    reemplazos.append({
                        "hoja": hoja, "activo_key": clave[1],
                        "periodo": clave[2], "filas_vivas": n,
                    })
    finally:
        conn.close()

    anomalias = _resumen_anomalias(planilla)
    puede_commitear = anomalias["bloqueantes"] == 0 and not conflictos

    return {
        "status": "duplicado" if ya_cargado else "ok",
        "file_hash": file_hash,
        "source_file": source_name,
        "periodos": planilla.periodos(),
        "scope_por_hoja": {h: sorted(v) for h, v in scopes.items()},
        "filas_por_hoja": {h.hoja: len(h.filas) for h in planilla.hojas},
        "anomalias": anomalias,
        "conflictos_semantica": conflictos,
        "mapeo_er": _mapping_status(planilla),
        "reemplazara": reemplazos,
        "puede_commitear": puede_commitear and not ya_cargado,
        "motivo_bloqueo": (
            "el archivo ya fue ingestado con exito" if ya_cargado
            else "hay anomalias bloqueantes" if anomalias["bloqueantes"]
            else "hay periodos con semantica de renta mezclada" if conflictos
            else None
        ),
    }


def commit(
    path: str,
    db_path: str,
    aceptar_anomalias: bool = False,
    source_name: str | None = None,
) -> dict:
    """Persiste el archivo completo. Atomico para los datos.

    El ingest_run va en su propia conexion y sobrevive al rollback; se cierra
    DESPUES de que la transaccion de datos termine, para que nunca quede un run
    marcado 'ok' sobre un commit que despues fallo.
    """
    source_name = source_name or os.path.basename(path)
    planilla = parse_planilla(path)
    file_hash = hash_de_archivo(path)

    # --- contrato de retry -------------------------------------------------
    # Duplicado = ya completo una ingesta exitosa, aunque sus filas hayan sido
    # supersedidas despues. Ver repo_jll_v2.hash_ya_ingestado_con_exito.
    chequeo = get_conn_for(db_path)
    try:
        if repo_jll_v2.hash_ya_ingestado_con_exito(chequeo, file_hash):
            return {"status": "skipped_duplicate", "file_hash": file_hash}
    finally:
        chequeo.close()

    anomalias = _resumen_anomalias(planilla)
    if anomalias["bloqueantes"] and not aceptar_anomalias:
        return {
            "status": "bloqueado",
            "motivo": "anomalias bloqueantes sin aceptar",
            "anomalias": anomalias,
        }

    # --- auditoria en conexion separada ------------------------------------
    audit = get_conn_for(db_path)
    run_id = repo_audit.start_ingest_run(audit, TOOL, source_name, file_hash)

    scopes = planilla.scope_por_hoja()
    conn = get_conn_for(db_path)
    resultado: dict = {}
    try:
        conflictos = _conflictos_semantica(conn, planilla)
        if conflictos:
            # Invariante de semantica NO anulable. `aceptar_anomalias` existe
            # para anomalias de calidad de datos (estado invalido, categoria
            # pendiente, etc.), nunca para invariantes de integridad: mezclar
            # 'total_uf' con otra semantica en el mismo (activo, periodo) hace
            # que cualquier suma aguas abajo sea aritmeticamente incorrecta, y
            # eso no es algo que un operador pueda "aceptar" fila a fila.
            raise ValueError(
                "periodos con semantica de renta mezclada (no se puede aceptar "
                "con aceptar_anomalias): %s" % conflictos
            )

        conn.execute("BEGIN IMMEDIATE")

        # Cada tabla supersede SOLO el scope de su propia hoja. Un scope global
        # borraria, por ejemplo, rent roll de periodos que unicamente aparecen
        # en el auxiliar.
        superseded = repo_rent_roll.mark_superseded_scope(
            conn, scopes.get(HOJA_RENT_ROLL, set())
        )
        for hoja, tabla in _HOJA_A_TABLA.items():
            if tabla in repo_jll_v2.TABLAS:
                superseded += repo_jll_v2.mark_superseded_scope(
                    conn, tabla, scopes.get(hoja, set())
                )

        insertadas = {}

        rr = [f for f in planilla.rent_roll.filas if f["activo_key"] and f["periodo"]]
        insertadas[HOJA_RENT_ROLL] = repo_rent_roll.insert_lines_v2(
            conn,
            [dict(f, source_file=source_name, source_sheet=HOJA_RENT_ROLL,
                  file_hash=file_hash,
                  arrendatario=_arrendatario_canonico(f),
                  extra_json=_extra_json_compat(f)) for f in rr],
            ingest_run_id=run_id,
            fuente_proveedor=FUENTE_PROVEEDOR,
            fuente_formato=FUENTE_FORMATO,
        )

        movs = []
        for f in planilla.movimientos.filas:
            if not (f["activo_key"] and f["periodo"]):
                continue
            cuenta = _mapear_cuenta(f["activo_key"], f["rubro"])
            movs.append(dict(
                f,
                cuenta_codigo_mapeada=cuenta,
                mapping_status="mapped" if cuenta else "unmapped",
            ))
        insertadas[HOJA_AUXILIAR] = repo_jll_v2.insert_lines(
            conn, "raw_movimiento_contable_line", movs,
            ingest_run_id=run_id, fuente_proveedor=FUENTE_PROVEEDOR,
            fuente_formato=FUENTE_FORMATO, source_file=source_name,
            source_sheet=HOJA_AUXILIAR, file_hash=file_hash,
        )

        for hoja, tabla in (
            (planilla.cartera, "raw_cartera_line"),
            (planilla.recaudacion, "raw_recaudacion"),
        ):
            filas = [f for f in hoja.filas if f["activo_key"] and f["periodo"]]
            insertadas[hoja.hoja] = repo_jll_v2.insert_lines(
                conn, tabla, filas,
                ingest_run_id=run_id, fuente_proveedor=FUENTE_PROVEEDOR,
                fuente_formato=FUENTE_FORMATO, source_file=source_name,
                source_sheet=hoja.hoja, file_hash=file_hash,
            )

        # El ER derivado se escribe DENTRO de la misma transaccion: no puede
        # existir una fila de ER sin los movimientos que la originaron. Los
        # periodos son los del AUXILIAR, no los del archivo completo: es esa
        # hoja la que alimenta el ER.
        er = derive_er_jll_v2.derivar(
            conn,
            file_hash=file_hash,
            source_file=source_name,
            ingest_run_id=run_id,
            periodos=sorted({p for _, _, p in scopes.get(HOJA_AUXILIAR, set())}),
        )

        conn.commit()
        resultado = {
            "status": "ok",
            "file_hash": file_hash,
            "source_file": source_name,
            "ingest_run_id": run_id,
            "superseded": superseded,
            "insertadas": insertadas,
            "periodos": planilla.periodos(),
            "anomalias": anomalias,
            "er_derivado": er,
        }
    except Exception as exc:
        conn.rollback()
        # El run ya esta commiteado en su propia conexion: marcarlo failed deja
        # el intento visible aunque no haya entrado un solo dato.
        repo_audit.fail_ingest_run(audit, run_id, str(exc))
        audit.close()
        raise
    finally:
        conn.close()

    # Solo aca, con la transaccion de datos ya cerrada, se declara el exito.
    total_in = sum(len(h.filas) for h in planilla.hojas)
    repo_audit.finish_ingest_run(
        audit, run_id, total_in, sum(resultado["insertadas"].values()), "ok"
    )
    audit.close()
    return resultado
