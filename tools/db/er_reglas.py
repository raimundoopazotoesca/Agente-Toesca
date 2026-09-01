"""Reglas internas de ER: contribuciones y seguros.

Contribuciones y seguros no los entrega JLL — se manejan internamente. Este
módulo es la contraparte en código de `dim_er_regla_interna` (migración 087):
la tabla guarda **sólo parámetros**, la aritmética vive acá, versionada y
testeada. Nunca se evalúan expresiones provenientes de la DB.

Ver docs/rent-roll-renta-semantics-v1.md y el encabezado de la migración 087.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

# Convenciones de UF soportadas. `dia_5` es la que usa JLL en su propia hoja
# `Data` (columna Tasa_UF_Dia5) y la que mejor reproduce los valores históricos
# de contribuciones en raw_er_activo_line.
UF_DIA_5 = "dia_5"
UF_FIN_MES = "fin_mes"


class ReglaError(Exception):
    """Parámetros insuficientes o inconsistentes para evaluar una regla."""


@dataclass(frozen=True)
class Regla:
    id: int
    activo_key: str
    cuenta_codigo: str
    tipo: str
    parametros: dict
    version: int
    vigente_desde: str | None
    vigente_hasta: str | None


def uf_del_periodo(
    conn: sqlite3.Connection, periodo: str, convencion: str = UF_DIA_5
) -> float:
    """UF a aplicar para un período YYYY-MM.

    `dia_5`: valor del día 5; si ese día no existe (fin de semana, feriado) se
    toma el primer día disponible a partir del 5, y si el mes no llega tan
    lejos, el último disponible del mes.
    `fin_mes`: último día disponible del mes.
    """
    if convencion == UF_FIN_MES:
        row = conn.execute(
            "SELECT valor FROM fact_uf WHERE fecha LIKE ? ORDER BY fecha DESC LIMIT 1",
            (f"{periodo}%",),
        ).fetchone()
    elif convencion == UF_DIA_5:
        row = conn.execute(
            "SELECT valor FROM fact_uf WHERE fecha >= ? AND fecha LIKE ? "
            "ORDER BY fecha LIMIT 1",
            (f"{periodo}-05", f"{periodo}%"),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT valor FROM fact_uf WHERE fecha LIKE ? ORDER BY fecha DESC LIMIT 1",
                (f"{periodo}%",),
            ).fetchone()
    else:
        raise ReglaError(f"Convención de UF desconocida: {convencion!r}")

    if row is None:
        raise ReglaError(f"No hay UF para el período {periodo}")
    return float(row[0])


def _contribuciones(params: dict, uf: float) -> float:
    """factor * sum(base_clp) / divisor / UF.

    `base_clp` son los avalúos en pesos (negativos, porque son gasto);
    `divisor` traduce la periodicidad de la base a mensual (trimestral -> 3).
    """
    try:
        base = params["base_clp"]
        divisor = params["divisor"]
    except KeyError as exc:
        raise ReglaError(f"formula_contribuciones sin parámetro {exc}") from exc
    if not isinstance(base, (list, tuple)) or not base:
        raise ReglaError("base_clp debe ser una lista no vacía")
    if not divisor:
        raise ReglaError("divisor no puede ser 0")
    factor = params.get("factor", 1.0)
    return factor * sum(base) / divisor / uf


def _monto_fijo(params: dict, uf: float | None) -> float:
    try:
        return float(params["monto_uf"])
    except KeyError as exc:
        raise ReglaError(f"monto_fijo_uf sin parámetro {exc}") from exc


_EVALUADORES = {
    "formula_contribuciones": _contribuciones,
    "monto_fijo_uf": _monto_fijo,
}

# Tipos cuya aritmética necesita convertir CLP a UF. Un monto ya expresado en UF
# no debe fallar por falta de UF del período: sería un acoplamiento espurio.
_REQUIEREN_UF = {"formula_contribuciones"}


def _fila_a_regla(row: sqlite3.Row) -> Regla:
    return Regla(
        id=row["id"],
        activo_key=row["activo_key"],
        cuenta_codigo=row["cuenta_codigo"],
        tipo=row["tipo"],
        parametros=json.loads(row["parametros_json"]),
        version=row["version"],
        vigente_desde=row["vigente_desde"],
        vigente_hasta=row["vigente_hasta"],
    )


def reglas_vigentes(conn: sqlite3.Connection, periodo: str) -> list[Regla]:
    """Reglas aplicables a un período, una por (activo_key, cuenta_codigo).

    La vigencia se compara sobre YYYY-MM: NULL en `vigente_desde` significa
    "desde siempre" y en `vigente_hasta`, "aún vigente".
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM dim_er_regla_interna
         WHERE (vigente_desde IS NULL OR vigente_desde <= ?)
           AND (vigente_hasta IS NULL OR vigente_hasta >= ?)
         ORDER BY activo_key, cuenta_codigo, version DESC
        """,
        (periodo, periodo),
    ).fetchall()

    vistas: set[tuple[str, str]] = set()
    out = []
    for row in rows:
        clave = (row["activo_key"], row["cuenta_codigo"])
        if clave in vistas:
            # Solapamiento de vigencias: no debería ocurrir (hay un invariante
            # que lo prohíbe). Se gana la versión más alta, determinísticamente.
            continue
        vistas.add(clave)
        out.append(_fila_a_regla(row))
    return out


def evaluar(conn: sqlite3.Connection, regla: Regla, periodo: str) -> float:
    """Monto UF que la regla aporta al ER en ese período."""
    evaluador = _EVALUADORES.get(regla.tipo)
    if evaluador is None:
        raise ReglaError(f"Tipo de regla no soportado: {regla.tipo!r}")
    uf = None
    if regla.tipo in _REQUIEREN_UF:
        convencion = regla.parametros.get("uf_convencion", UF_DIA_5)
        uf = uf_del_periodo(conn, periodo, convencion)
    return evaluador(regla.parametros, uf)


def evaluar_periodo(
    conn: sqlite3.Connection,
    periodo: str,
    activos: list[str] | None = None,
    tolerante: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Evalúa todas las reglas vigentes del período.

    Devuelve `(filas, errores)`. Las filas quedan listas para persistir en
    raw_er_activo_line, cada una con la `origen_regla_id` de la versión concreta
    que se usó.

    Con `tolerante=True`, una regla que no se puede evaluar (falta la UF del
    período, parámetros incompletos) va a `errores` en vez de abortar: las demás
    reglas del período sí se evalúan. Es lo que necesita la ingesta, donde los
    datos crudos ya están persistidos y no deben perderse por una UF faltante.
    """
    out: list[dict] = []
    errores: list[dict] = []
    for regla in reglas_vigentes(conn, periodo):
        if activos is not None and regla.activo_key not in activos:
            continue
        try:
            monto = evaluar(conn, regla, periodo)
        except ReglaError as exc:
            if not tolerante:
                raise
            errores.append(
                {
                    "activo_key": regla.activo_key,
                    "cuenta_codigo": regla.cuenta_codigo,
                    "periodo": periodo,
                    "motivo": str(exc),
                }
            )
            continue
        out.append(
            {
                "activo_key": regla.activo_key,
                "periodo": periodo,
                "cuenta_codigo": regla.cuenta_codigo,
                "monto_uf": monto,
                "origen": "regla_interna",
                "origen_regla_id": regla.id,
            }
        )
    return out, errores
