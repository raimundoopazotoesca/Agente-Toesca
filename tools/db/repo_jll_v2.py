"""Repos de las tablas canonicas de facturacion, cartera y recaudacion.

Las tres tablas de la migracion 086 comparten exactamente el mismo contrato:
lineage completo, `fuente_proveedor`/`fuente_formato` obligatorios en filas
nuevas, unico parcial sobre las vivas y supersession por
(fuente_proveedor, activo_key, periodo). Por eso van en un solo modulo con un
insert parametrizado, en vez de tres archivos casi identicos como
repo_rent_roll.py / repo_er_activo.py: la duplicacion seria la unica diferencia.

Ninguna funcion hace commit. La transaccion la maneja quien orquesta
(tools/db/ingest_jll_planilla.py), porque un archivo JLL entra entero o no entra.
"""
from __future__ import annotations

import sqlite3

# columnas propias de cada tabla, en orden de insert
_COLS = {
    "raw_movimiento_contable_line": [
        "activo_key", "periodo", "fecha_fuente", "rubro", "clasificacion",
        "codigo_rubro", "tercero", "descripcion", "monto_uf",
        "cuenta_codigo_mapeada", "mapping_status",
    ],
    "raw_cartera_line": [
        "activo_key", "periodo", "fecha_corte_fuente", "cliente", "marca",
        "identificacion", "documento", "concepto", "inmueble",
        "fecha_vencimiento", "dias_vencimiento", "vencido_1_30",
        "vencido_31_60", "vencido_61_90", "vencido_mas_91", "saldo_por_vencer",
        "saldo_a_favor", "total_cartera",
    ],
    "raw_recaudacion": [
        "activo_key", "periodo", "fecha_corte_fuente", "monto_uf",
    ],
}

# comunes a las tres, siempre al final
_COMUNES = [
    "fuente_proveedor", "fuente_formato",
    "source_file", "source_sheet", "source_row", "file_hash", "ingest_run_id",
]

TABLAS = tuple(_COLS)


class LineageIncompleto(ValueError):
    """Una fila nueva llego sin la procedencia obligatoria."""


def insert_lines(
    conn: sqlite3.Connection,
    tabla: str,
    lines: list[dict],
    *,
    ingest_run_id: int,
    fuente_proveedor: str,
    fuente_formato: str,
    source_file: str,
    source_sheet: str,
    file_hash: str,
) -> int:
    """Inserta filas. Devuelve cuantas entraron.

    `fuente_proveedor` y `fuente_formato` se exigen aca y no como NOT NULL de
    tabla en raw_rent_roll_line, cuyo historico legitimamente los tiene en NULL.
    En estas tres tablas el NOT NULL tambien existe; esta validacion da el error
    con nombre en vez de un IntegrityError opaco.
    """
    if tabla not in _COLS:
        raise ValueError("Tabla desconocida: %r" % tabla)
    if not fuente_proveedor:
        raise LineageIncompleto(
            "fuente_proveedor es obligatorio para filas nuevas de %s" % tabla
        )
    if not fuente_formato:
        raise LineageIncompleto(
            "fuente_formato es obligatorio para filas nuevas de %s" % tabla
        )

    cols = _COLS[tabla] + _COMUNES
    # INSERT normal, no "OR IGNORE": una restriccion incumplida debe fallar y
    # hacer rollback de todo el archivo, nunca descartar una fila en silencio.
    # Descartar filas calladamente es el modo de falla que este pipeline existe
    # para eliminar.
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (
        tabla, ", ".join(cols), ", ".join(["?"] * len(cols))
    )
    fijos = {
        "fuente_proveedor": fuente_proveedor,
        "fuente_formato": fuente_formato,
        "source_file": source_file,
        "source_sheet": source_sheet,
        "file_hash": file_hash,
        "ingest_run_id": ingest_run_id,
    }

    inserted = 0
    for line in lines:
        values = tuple(fijos.get(c, line.get(c)) for c in cols)
        cur = conn.execute(sql, values)
        inserted += max(cur.rowcount, 0)
    return inserted


def mark_superseded_scope(
    conn: sqlite3.Connection, tabla: str, scope: set
) -> int:
    """Supersede las filas vivas de cada (fuente_proveedor, activo_key, periodo).

    El proveedor va en la clave a proposito: una fuente no puede superseder los
    datos de otra sobre el mismo activo y periodo.
    """
    if tabla not in _COLS:
        raise ValueError("Tabla desconocida: %r" % tabla)
    sql = (
        "UPDATE %s SET superseded_at = datetime('now') "
        " WHERE fuente_proveedor = ? AND activo_key = ? AND periodo = ? "
        "   AND superseded_at IS NULL" % tabla
    )
    afectadas = 0
    for proveedor, activo, periodo in sorted(scope):
        cur = conn.execute(sql, (proveedor, activo, periodo))
        afectadas += max(cur.rowcount, 0)
    return afectadas


def hash_ya_ingestado_con_exito(conn: sqlite3.Connection, file_hash: str) -> bool:
    """True si ese archivo ya completo una ingesta exitosa alguna vez.

    Contrato de retry, en tres mitades:

    - Un hash con al menos un `ingest_run` en estado 'ok' es DUPLICADO para
      siempre, aunque sus filas hayan sido supersedidas despues por un archivo
      posterior. Mirar solo filas vivas seria incorrecto: en la secuencia
      A(ok) -> B(ok, supersede a A) -> A otra vez, A ya no tiene filas vivas y
      se reingestaria, superseder??a a B y haria retroceder los datos.
    - Un hash con evidencia PERSISTIDA (viva o supersedida) en cualquiera de
      las tablas del pipeline es DUPLICADO, incluso si su `ingest_run` nunca
      llego a 'ok'. Escenario crash-safe: el proceso muere DESPUES de
      `conn.commit()` de los datos pero ANTES de `finish_ingest_run()` (que
      corre en una conexion separada, ver ingest_jll_planilla.commit()). Ahi
      los datos SI quedaron persistidos pero el run se ve 'started' para
      siempre. Reintentar en ese estado duplicaria filas o -peor- volveria a
      ejecutar la derivacion de ER sobre datos ya derivados.
    - Un hash SIN evidencia persistida y SIN run 'ok' no es duplicado: no dejo
      ningun rastro de datos, asi que reintentarlo es legitimo y necesario
      (el caso tipico es un fallo de parseo o de restriccion antes de que
      cualquier INSERT se ejecutara).

    Por eso el `ingest_run` debe sobrevivir al rollback (ver ingest_jll_planilla).
    """
    row = conn.execute(
        """SELECT 1 FROM ingest_run
            WHERE file_hash = ? AND status = 'ok' AND tool LIKE 'ingest_jll_planilla%'
            LIMIT 1""",
        (file_hash,),
    ).fetchone()
    if row is not None:
        return True

    for tabla in list(TABLAS) + ["raw_rent_roll_line"]:
        row = conn.execute(
            "SELECT 1 FROM %s WHERE file_hash = ? LIMIT 1" % tabla,
            (file_hash,),
        ).fetchone()
        if row is not None:
            return True
    return False


def contar_vivas(conn: sqlite3.Connection, tabla: str, scope_key: tuple) -> int:
    proveedor, activo, periodo = scope_key
    return conn.execute(
        "SELECT COUNT(*) FROM %s WHERE fuente_proveedor = ? AND activo_key = ? "
        "  AND periodo = ? AND superseded_at IS NULL" % tabla,
        (proveedor, activo, periodo),
    ).fetchone()[0]
