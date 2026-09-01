"""Regenera tools/db/baseline.sql desde el esquema operacional.

El baseline es el esquema consolidado que se aplica a una DB vacía en lugar de
re-ejecutar la cadena histórica de migraciones (que no reproduce producción; ver
el encabezado de baseline.sql). Debe regenerarse cuando una migración nueva
cambie el esquema, para que `apply_migrations()` sobre una DB vacía siga
produciendo el esquema operacional y luego aplicando las migraciones posteriores.

Uso:
    python scripts/regenerar_baseline.py            # regenera y muestra el diff
    python scripts/regenerar_baseline.py --check    # solo verifica que esté al día
    python scripts/regenerar_baseline.py --source ruta/a/snapshot.db

BASELINE_VERSION es el watermark operacional incorporado al baseline, no
necesariamente la última migración. La fuente se abre read-only y, si está
atrás, solo una copia temporal recibe las migraciones necesarias para llegar al
watermark.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.db.connection import (  # noqa: E402
    BASELINE_PATH,
    BASELINE_VERSION,
    DEFAULT_DB_PATH,
    _discover_migrations,
    _execute_migration,
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
-- BASELINE_VERSION es el watermark operacional incorporado aquí, no
-- necesariamente la última migración del repositorio. Las migraciones
-- posteriores se aplican normalmente a una DB vacía después del baseline.
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


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _version_registrada(path: Path) -> int:
    con = _connect_read_only(path)
    try:
        versiones = [row[0] for row in con.execute(
            "SELECT version FROM schema_version ORDER BY version"
        )]
    finally:
        con.close()
    maximo = versiones[-1] if versiones else 0
    if versiones != list(range(1, maximo + 1)):
        raise RuntimeError("El snapshot fuente tiene huecos en schema_version")
    return maximo


def _migraciones_hasta_baseline(origen_version: int) -> list[tuple[int, Path]]:
    if origen_version > BASELINE_VERSION:
        raise RuntimeError(
            f"El snapshot fuente está en {origen_version}, sobre el watermark "
            f"del baseline {BASELINE_VERSION}; no se puede retroceder."
        )
    disponibles = dict(_discover_migrations())
    requeridas = list(range(origen_version + 1, BASELINE_VERSION + 1))
    faltantes = [version for version in requeridas if version not in disponibles]
    if faltantes:
        raise RuntimeError(
            f"Faltan migraciones para reconstruir baseline {BASELINE_VERSION}: {faltantes}"
        )
    return [(version, disponibles[version]) for version in requeridas]


def _reconstruir_referencia(origen: Path, destino: Path) -> None:
    origen_version = _version_registrada(origen)
    migraciones = _migraciones_hasta_baseline(origen_version)
    shutil.copy2(origen, destino)
    con = sqlite3.connect(destino)
    try:
        for version, path in migraciones:
            con.execute("BEGIN IMMEDIATE")
            try:
                _execute_migration(con, path.read_text(encoding="utf-8"))
                con.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                con.commit()
            except Exception:
                con.rollback()
                raise
    finally:
        con.close()
    if _version_registrada(destino) != BASELINE_VERSION:
        raise RuntimeError(
            f"La referencia temporal no llegó al watermark {BASELINE_VERSION}"
        )


def construir(referencia: Path) -> str:
    con = _connect_read_only(referencia)
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


def construir_desde_fuente(origen: Path) -> str:
    if not origen.is_file():
        raise RuntimeError(f"No existe el snapshot fuente: {origen}")
    with tempfile.TemporaryDirectory(prefix="baseline-") as temporal:
        referencia = Path(temporal) / "referencia.db"
        _reconstruir_referencia(origen, referencia)
        return construir(referencia)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="no escribe; falla si está desactualizado")
    ap.add_argument(
        "--source", type=Path, default=Path(DEFAULT_DB_PATH),
        help="snapshot fuente read-only; se reconstruye temporalmente al watermark",
    )
    args = ap.parse_args()

    try:
        nuevo = construir_desde_fuente(args.source)
    except RuntimeError as exc:
        print(f"No se pudo reconstruir el baseline: {exc}", file=sys.stderr)
        return 2
    actual = BASELINE_PATH.read_text(encoding="utf-8") if BASELINE_PATH.exists() else ""

    if nuevo == actual:
        print(f"baseline.sql al día (versión {BASELINE_VERSION}).")
        return 0
    if args.check:
        print(
            f"baseline.sql DESACTUALIZADO respecto del baseline operacional.\n"
            f"Regenera con: python scripts/regenerar_baseline.py",
            file=sys.stderr,
        )
        return 1

    BASELINE_PATH.write_text(nuevo, encoding="utf-8")
    print(
        f"baseline.sql regenerado ({len(nuevo.splitlines())} líneas, "
        f"versión {BASELINE_VERSION})."
    )
    print(
        "Recuerda: BASELINE_VERSION es el watermark operacional incorporado al "
        "baseline, no necesariamente la última migración."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
