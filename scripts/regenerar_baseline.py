"""Regenera tools/db/baseline.sql desde el esquema de la DB productiva.

El baseline es el esquema consolidado que se aplica a una DB vacía en lugar de
re-ejecutar la cadena histórica de migraciones (que no reproduce producción; ver
el encabezado de baseline.sql). Debe regenerarse cuando una migración nueva
cambie el esquema, para que `apply_migrations()` sobre una DB vacía siga
produciendo exactamente el esquema de producción.

Uso:
    python scripts/regenerar_baseline.py            # regenera y muestra el diff
    python scripts/regenerar_baseline.py --check    # solo verifica que esté al día

Verificación de que sigue siendo fiel: tests/db/test_baseline.py compara objeto
por objeto una DB creada desde cero contra la DB productiva.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db.connection import (  # noqa: E402
    BASELINE_PATH,
    BASELINE_VERSION,
    DEFAULT_DB_PATH,
    get_conn_for,
)

# Objetos que existieron en las migraciones históricas pero se excluyen a
# propósito. El porqué de cada uno está en el encabezado de baseline.sql.
EXCLUIDOS = {"dim_cuenta", "publish_run"}

# Dimensiones cuyos datos son catálogo (no datos de negocio) y viajan en el
# baseline para que una DB nueva sea usable y los tests tengan sus referencias.
TABLAS_SEED = [
    "dim_fondo",
    "dim_serie",
    "dim_sociedad",
    "dim_activo",
    "dim_concepto_parking",
    "dim_cuenta_eeff",
]

HEADER = f"""\
-- ════════════════════════════════════════════════════════════════════════════
-- BASELINE del esquema — equivale a aplicar las migraciones 001..{BASELINE_VERSION:03d}.
--
-- GENERADO POR scripts/regenerar_baseline.py — no editar a mano.
--
-- Por qué existe
-- --------------
-- La DB productiva nunca se construyó ejecutando las migraciones: se bootstrapeó
-- desde tools/db/schema_v2.sql (2026-06-01) y las versiones 2–22 se marcaron
-- aplicadas en un solo lote, con timestamp idéntico, sin ejecutarse. Resultado:
-- una DB nueva creada con apply_migrations() tenía un esquema DISTINTO del de
-- producción, y los tests validaban un esquema que producción no tenía.
--
-- Este archivo es el esquema real de producción. El runner lo aplica a una DB
-- vacía y registra 1..{BASELINE_VERSION} como aplicadas — ahora sí de forma veraz, porque el
-- baseline incorpora sus efectos. Las migraciones históricas se conservan como
-- referencia pero ya no se ejecutan sobre DBs nuevas.
--
-- Decisiones tomadas al construirlo
-- ---------------------------------
-- INCLUIDO: los 12 índices que las migraciones declaraban y producción no tenía
--   (recuperados en la migración 059; aditivos, sin efecto sobre datos).
--
-- EXCLUIDO — `dim_cuenta` (001/002): obsoleta, reemplazada por `dim_cuenta_eeff`.
--   Nunca existió en producción. Peor: las migraciones declaraban FK
--   `raw_{{eeff,er_activo,flujo}}_line.cuenta_codigo -> dim_cuenta(codigo)` sobre
--   una tabla que quedaba vacía, así que en una DB nueva **toda ingesta con
--   cuenta_codigo fallaba**. Se excluyen la tabla y esas tres FKs.
--
-- EXCLUIDO — `publish_run` (005): nunca se creó en producción ni se usó. Sus
--   únicos consumidores (`repo_audit.start/finish_publish_run`) fallaban con
--   "no such table" y se eliminaron.
--
-- PENDIENTE a propósito — `UNIQUE(file_hash, source_row)` en las 4 tablas raw
--   `_line`. La migración 002 lo declaraba y producción no lo tiene; por eso el
--   `INSERT OR IGNORE` de los repos es un no-op y hay duplicados vivos.
--   Imponerlo hoy fallaría. Entra tras el saneamiento (ROADMAP F0.4), en una
--   migración aplicada a producción y reflejada aquí a la vez.
-- ════════════════════════════════════════════════════════════════════════════

"""


def _literal(valor: object) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)):
        return repr(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def construir() -> str:
    con = get_conn_for(str(DEFAULT_DB_PATH))
    try:
        partes = [HEADER]
        for tipo in ("table", "index", "view"):
            for nombre, sql in con.execute(
                "SELECT name, sql FROM sqlite_master WHERE type=? AND sql IS NOT NULL "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                (tipo,),
            ):
                # schema_version la crea el runner antes de aplicar el baseline.
                if nombre == "schema_version" or nombre in EXCLUIDOS:
                    continue
                partes.append(sql.strip().rstrip(";") + ";\n")

        partes.append(
            "\n-- ── Seeds de dimensiones ───────────────────────────────────────────────\n"
        )
        for tabla in TABLAS_SEED:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')")]
            filas = con.execute(f"SELECT {', '.join(cols)} FROM '{tabla}'").fetchall()
            if not filas:
                continue
            partes.append(f"\n-- {tabla} ({len(filas)} filas)")
            partes.append(f"INSERT OR IGNORE INTO {tabla} ({', '.join(cols)}) VALUES")
            partes.append(
                ",\n".join(
                    "    (" + ", ".join(_literal(v) for v in fila) + ")" for fila in filas
                )
                + ";\n"
            )
        return "\n".join(partes)
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="no escribe; falla si está desactualizado")
    args = ap.parse_args()

    nuevo = construir()
    actual = BASELINE_PATH.read_text(encoding="utf-8") if BASELINE_PATH.exists() else ""

    if nuevo == actual:
        print(f"baseline.sql al día (versión {BASELINE_VERSION}).")
        return 0
    if args.check:
        print(
            f"baseline.sql DESACTUALIZADO respecto de la DB productiva.\n"
            f"Regenera con: python scripts/regenerar_baseline.py",
            file=sys.stderr,
        )
        return 1

    BASELINE_PATH.write_text(nuevo, encoding="utf-8")
    print(
        f"baseline.sql regenerado ({len(nuevo.splitlines())} líneas, "
        f"versión {BASELINE_VERSION})."
    )
    print("Recuerda: BASELINE_VERSION en tools/db/connection.py debe ser la última migración.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
