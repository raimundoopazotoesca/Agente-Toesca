"""Derivacion de raw_er_activo_line desde el pipeline JLL v2.

Dos origenes distintos alimentan el ER de estos activos:

  'jll_v2'        agregacion de raw_movimiento_contable_line por
                  (activo_key, periodo, cuenta_codigo). N movimientos -> 1 fila,
                  con el detalle en la tabla puente raw_er_movimiento_lineage.

  'regla_interna' contribuciones y seguros, que JLL NO entrega. Se calculan con
                  tools/db/er_reglas.py y apuntan a la version de regla usada.

Cuando ambos producen la misma cuenta (contribuciones de Apo4501/4700), MANDA LO
INTERNO y la diferencia se reporta como control cruzado. Confirmado con el
usuario 2026-08-28; JLL tiene una consulta abierta por esa diferencia.

DEUDA DECLARADA: `raw_er_activo_line.monto_clp` contiene UF de facto para estos
activos (Apo4501 2026-05 = 13.135 son UF, no pesos). El dato canonico del
pipeline nuevo es `raw_movimiento_contable_line.monto_uf`; escribir en monto_clp
es un PUENTE de compatibilidad para no quebrar los consumidores de NOI, no la
semantica del diseno nuevo. Aislado en `legacy_er_compat_adapter` para que sea
localizable el dia que se renombre la columna.
"""
from __future__ import annotations

import sqlite3

from tools.db import er_reglas

# Cuentas cuyo valor oficial es interno. Si JLL tambien las trae, se descarta su
# valor para el ER y se emite una alerta con la diferencia.
#
# APO3001_SEG queda deliberadamente FUERA: la autoridad real del seguro de
# Apo3001 es JLL (confirmado con el usuario 2026-08-28: "Apo3001: JLL"), no
# interna. No hay ninguna regla sembrada en dim_er_regla_interna para
# (Apo3001, APO3001_SEG) -- si esta cuenta hubiera quedado en el set, el
# camino fail-closed la habria bloqueado para siempre (nunca hay regla que
# evaluar), descartando en silencio un dato que JLL SI tiene autoridad para
# entregar. APO_SEG (Apo4501/4700) tampoco tiene regla sembrada, pero se deja
# en el set porque esos activos no tienen seguro (interno ni de JLL) y el
# fail-closed ahi es el comportamiento correcto: no inventar un valor.
CUENTAS_INTERNAS = {
    "APO_CONTRIB",
    "PT_CONTRIB",
    "APO3001_CONTRIB_SOBRETASA",
    "PT_SEG",
    "APO_SEG",
}

_INSERT_ER = """
INSERT INTO raw_er_activo_line
    (activo_key, periodo, cuenta_codigo, cuenta_nombre, monto_clp, monto_uf,
     seccion, es_operacional, source_file, source_sheet, file_hash,
     ingest_run_id, origen, origen_regla_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _seccion(clasificacion: str | None) -> tuple[str, int]:
    """(seccion, es_operacional) segun la clasificacion presupuestal de JLL."""
    c = (clasificacion or "").strip().lower()
    if c == "ingresos":
        return "INGRESOS_OPERACION", 1
    if c == "gastos no operacionales":
        return "GASTOS_OPERACION", 0
    return "GASTOS_OPERACION", 1


def agregar_movimientos(conn: sqlite3.Connection, file_hash: str) -> list[dict]:
    """Agrupa los movimientos mapeados de un archivo por cuenta y periodo.

    Devuelve un grupo por (activo_key, periodo, cuenta_codigo) con el monto y
    los ids de los movimientos que lo componen, para poblar el lineage.
    Los `unmapped` quedan fuera a proposito: ya estan persistidos en crudo y
    reportados; inventarles una cuenta seria peor que no derivarlos.
    """
    rows = conn.execute(
        """SELECT id, activo_key, periodo, cuenta_codigo_mapeada AS cuenta,
                  clasificacion, monto_uf
             FROM raw_movimiento_contable_line
            WHERE file_hash = ? AND superseded_at IS NULL
              AND mapping_status = 'mapped'
            ORDER BY activo_key, periodo, cuenta_codigo_mapeada, id""",
        (file_hash,),
    ).fetchall()

    grupos: dict[tuple, dict] = {}
    for r in rows:
        clave = (r["activo_key"], r["periodo"], r["cuenta"])
        g = grupos.setdefault(clave, {
            "activo_key": r["activo_key"],
            "periodo": r["periodo"],
            "cuenta_codigo": r["cuenta"],
            "clasificacion": r["clasificacion"],
            "monto_uf": 0.0,
            "aportes": [],
        })
        monto = r["monto_uf"] or 0.0
        g["monto_uf"] += monto
        g["aportes"].append((r["id"], monto))
    return list(grupos.values())


def pares_activo_periodo(conn: sqlite3.Connection, file_hash: str) -> set[tuple]:
    """(activo_key, periodo) de TODOS los movimientos del auxiliar de este archivo.

    A proposito NO filtra por mapping_status. Un activo-periodo cuyos rubros
    son todos 'unmapped' (p.ej. Apo3001, que solo trae arriendo + admin
    mapeados y el resto sin cuenta) igual necesita que sus reglas internas
    -contribuciones, seguros- se evaluen: esos gastos no dependen de que JLL
    haya podido mapear nada. Restringir a `agregar_movimientos()` (que si
    filtra por 'mapped') dejaria esos periodos sin ER de contribuciones ni
    seguros, silenciosamente.
    """
    rows = conn.execute(
        """SELECT DISTINCT activo_key, periodo FROM raw_movimiento_contable_line
            WHERE file_hash = ? AND superseded_at IS NULL""",
        (file_hash,),
    ).fetchall()
    return {(r["activo_key"], r["periodo"]) for r in rows}


def legacy_er_compat_adapter(
    conn: sqlite3.Connection,
    *,
    activo_key: str,
    periodo: str,
    cuenta_codigo: str,
    monto_uf: float,
    clasificacion: str | None,
    origen: str,
    source_file: str,
    source_sheet: str,
    file_hash: str | None,
    ingest_run_id: int,
    origen_regla_id: int | None = None,
) -> int:
    """Escribe una fila de ER. PUENTE LEGACY, no semantica del diseno nuevo.

    El monto va a `monto_clp` porque es lo que leen hoy los consumidores de NOI
    para estos activos, aunque el valor sea UF (ver docstring del modulo). Se
    escribe tambien en `monto_uf`, que si es honesto, para que la migracion
    futura sea un cambio de lectura y no una reconstruccion.
    """
    seccion, operacional = _seccion(clasificacion)
    cur = conn.execute(
        _INSERT_ER,
        (
            activo_key, periodo, cuenta_codigo, cuenta_codigo,
            monto_uf,   # monto_clp: deuda declarada, contiene UF
            monto_uf,   # monto_uf: el valor honesto
            seccion, operacional,
            source_file, source_sheet, file_hash, ingest_run_id,
            origen, origen_regla_id,
        ),
    )
    return cur.lastrowid


def supersede_cuentas(conn: sqlite3.Connection, claves: set) -> int:
    """Supersede las filas vivas de ER de (activo_key, periodo, cuenta_codigo).

    Reemplazo QUIRURGICO: sólo las cuentas que esta corrida efectivamente
    reescribe. Sin esto, cada ingesta agregaba una fila más y dejaba dos vivas
    para la misma cuenta, duplicando el NOI.

    Deliberadamente NO se supersede por (activo, periodo) completo: el archivo
    JLL v2 no reconstruye todas las cuentas del ER (para PT y Apo3001 trae casi
    sólo ingreso), así que barrer el período entero borraría gastos vigentes que
    esta fuente no puede reponer.
    """
    afectadas = 0
    for activo, periodo, cuenta in sorted(claves):
        cur = conn.execute(
            """UPDATE raw_er_activo_line
                  SET superseded_at = datetime('now')
                WHERE activo_key = ? AND periodo = ? AND cuenta_codigo = ?
                  AND superseded_at IS NULL""",
            (activo, periodo, cuenta),
        )
        afectadas += max(cur.rowcount, 0)
    return afectadas


def derivar(
    conn: sqlite3.Connection,
    *,
    file_hash: str,
    source_file: str,
    ingest_run_id: int,
    periodos: list[str] | None = None,
) -> dict:
    """Deriva el ER de un archivo ya ingestado. No hace commit.

    Debe correr DENTRO de la transaccion de la ingesta para que el ER derivado
    no pueda existir sin sus movimientos de origen.

    Va en dos fases a proposito: primero PLANIFICA todas las filas que va a
    escribir, luego supersede exactamente esas cuentas, y recien despues
    inserta. Planificar antes de superseder es lo que permite que el reemplazo
    sea quirurgico: si una regla no se puede evaluar, su cuenta no entra en el
    plan y por tanto tampoco se supersede, dejando vivo el valor anterior en vez
    de borrarlo sin reemplazo.
    """
    grupos = agregar_movimientos(conn, file_hash)

    # Pares (activo, periodo) que el auxiliar de ESTE archivo cubre. Las reglas
    # internas se evaluan sobre TODOS los movimientos del archivo, no solo los
    # 'mapped' de `grupos`: un activo-periodo cuyos rubros son todos unmapped
    # (Apo3001 con casi solo arriendo+admin mapeados) igual tiene contribuciones
    # y seguros que evaluar. Restringir a `grupos` dejaba esos periodos sin ER
    # interno, silenciosamente. Aplicar todas las reglas a activos x periodos sin
    # restriccion tampoco vale: seria un producto cartesiano que inventa filas
    # para combinaciones que el archivo nunca reporto.
    pares = pares_activo_periodo(conn, file_hash)
    if periodos is not None:
        permitidos = set(periodos)
        pares = {(a, p) for a, p in pares if p in permitidos}

    alertas: list[dict] = []
    no_evaluadas: list[dict] = []

    # --- fase 1: planificar -------------------------------------------------
    plan_internas: list[dict] = []
    internas: set[tuple] = set()
    for activo, periodo in sorted(pares):
        filas, errores = er_reglas.evaluar_periodo(
            conn, periodo, [activo], tolerante=True
        )
        no_evaluadas.extend(errores)
        for fila in filas:
            plan_internas.append(fila)
            internas.add((fila["activo_key"], fila["periodo"], fila["cuenta_codigo"]))

    # Errores de evaluacion indexados por (activo,periodo,cuenta), para poder
    # explicar en el reporte POR QUE una cuenta de autoridad interna quedo sin
    # evaluar (falta UF, parametro invalido, etc.) cuando corresponda.
    errores_por_clave = {
        (e["activo_key"], e["periodo"], e["cuenta_codigo"]): e["motivo"]
        for e in no_evaluadas
    }

    plan_jll: list[dict] = []
    bloqueadas_fail_closed: list[dict] = []
    for g in grupos:
        clave = (g["activo_key"], g["periodo"], g["cuenta_codigo"])
        if periodos is not None and g["periodo"] not in set(periodos):
            continue
        if g["cuenta_codigo"] in CUENTAS_INTERNAS:
            if clave in internas:
                # Manda lo interno. El valor de JLL no se persiste en el ER;
                # queda como alerta de control cruzado contra el interno.
                interno = next(
                    (f["monto_uf"] for f in plan_internas
                     if (f["activo_key"], f["periodo"], f["cuenta_codigo"]) == clave),
                    None,
                )
                alertas.append({
                    "tipo": "control_cruzado",
                    "activo_key": g["activo_key"],
                    "periodo": g["periodo"],
                    "cuenta_codigo": g["cuenta_codigo"],
                    "jll_uf": round(g["monto_uf"], 2),
                    "interno_uf": round(interno, 2) if interno else None,
                    "diferencia_pct": (
                        round(100 * (g["monto_uf"] - interno) / interno, 1)
                        if interno else None
                    ),
                    "nota": "manda lo interno; el valor de JLL no se persistio en el ER",
                })
                continue
            # FAIL-CLOSED: la cuenta es de autoridad interna pero la regla no
            # se pudo evaluar (falta UF/parametro) o no existe ninguna regla
            # sembrada para (activo, cuenta). En ningun caso JLL puede tomar
            # el control por default de una cuenta que no le pertenece: eso
            # seria precedence fail-open, exactamente lo que la separacion de
            # autoridades (JLL vs interno) existe para impedir. El valor de
            # JLL queda solo en raw_movimiento_contable_line (ya persistido),
            # no entra al ER, y el ER anterior de esa cuenta NO se supersede
            # -- se deja vivo el ultimo valor conocido en vez de un hueco.
            bloqueadas_fail_closed.append({
                "tipo": "autoridad_interna_no_evaluable",
                "activo_key": g["activo_key"],
                "periodo": g["periodo"],
                "cuenta_codigo": g["cuenta_codigo"],
                "jll_uf_en_raw": round(g["monto_uf"], 2),
                "motivo": errores_por_clave.get(
                    clave, "no existe regla interna sembrada para esta cuenta"
                ),
                "nota": (
                    "cuenta de autoridad interna sin regla evaluable; JLL NO "
                    "toma el control por default. Queda en raw, no en ER; el "
                    "ER anterior de esta cuenta no se modifica."
                ),
            })
            continue
        plan_jll.append(g)

    # --- fase 2: superseder solo lo que se reescribe -------------------------
    claves = internas | {
        (g["activo_key"], g["periodo"], g["cuenta_codigo"]) for g in plan_jll
    }
    superseded = supersede_cuentas(conn, claves)

    # --- fase 3: insertar ---------------------------------------------------
    for fila in plan_internas:
        legacy_er_compat_adapter(
            conn,
            activo_key=fila["activo_key"],
            periodo=fila["periodo"],
            cuenta_codigo=fila["cuenta_codigo"],
            monto_uf=fila["monto_uf"],
            clasificacion="Gastos",
            origen="regla_interna",
            source_file="regla_interna:dim_er_regla_interna",
            source_sheet=None,
            file_hash=None,
            ingest_run_id=ingest_run_id,
            origen_regla_id=fila["origen_regla_id"],
        )

    for g in plan_jll:
        er_id = legacy_er_compat_adapter(
            conn,
            activo_key=g["activo_key"],
            periodo=g["periodo"],
            cuenta_codigo=g["cuenta_codigo"],
            monto_uf=g["monto_uf"],
            clasificacion=g["clasificacion"],
            origen="jll_v2",
            source_file=source_file,
            source_sheet="AuxiliarContable",
            file_hash=file_hash,
            ingest_run_id=ingest_run_id,
        )
        conn.executemany(
            "INSERT INTO raw_er_movimiento_lineage (er_line_id, movimiento_id, aporte_uf) "
            "VALUES (?, ?, ?)",
            [(er_id, mid, aporte) for mid, aporte in g["aportes"]],
        )

    return {
        "filas_jll_v2": len(plan_jll),
        "filas_regla_interna": len(plan_internas),
        "cuentas_superseded": superseded,
        "alertas_control_cruzado": alertas,
        "reglas_no_evaluadas": no_evaluadas,
        "autoridad_interna_no_evaluable": bloqueadas_fail_closed,
    }
