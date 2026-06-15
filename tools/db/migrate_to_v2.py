"""
Migra datos desde agente_toesca.db (v1) hacia agente_toesca_v2.db (schema limpio).

Ejecutar: python tools/db/migrate_to_v2.py
"""
import sqlite3
import os

SRC = os.path.join("memory", "agente_toesca.db")
DST = os.path.join("memory", "agente_toesca_v2.db")
SCHEMA = os.path.join("tools", "db", "schema_v2.sql")


def run():
    if os.path.exists(DST):
        os.remove(DST)
        print(f"Removed existing {DST}")

    with open(SCHEMA) as f:
        schema_sql = f.read()

    dst = sqlite3.connect(DST)
    dst.executescript(schema_sql)
    dst.execute("PRAGMA foreign_keys=OFF")  # disable for bulk migration
    dst.commit()
    print("Schema created")

    src = sqlite3.connect(SRC)
    counts = {}

    # ── ingest_run primero (FK referenciada por raw tables) ──
    ir_rows = src.execute("SELECT * FROM ingest_run").fetchall()
    ir_cols = [d[1] for d in src.execute("PRAGMA table_info(ingest_run)")]
    placeholders = ",".join("?" * len(ir_cols))
    dst.executemany(
        f"INSERT OR IGNORE INTO ingest_run({','.join(ir_cols)}) VALUES ({placeholders})",
        ir_rows,
    )
    counts["ingest_run"] = len(ir_rows)

    # ── Dimensions ──────────────────────────────────────────
    for table in ("dim_fondo", "dim_activo", "dim_serie"):
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        cols = [d[1] for d in src.execute(f"PRAGMA table_info({table})")]
        placeholders = ",".join("?" * len(cols))
        dst.executemany(
            f"INSERT OR IGNORE INTO {table}({','.join(cols)}) VALUES ({placeholders})",
            rows,
        )
        counts[table] = len(rows)

    # ── Raw tables (direct copy) ─────────────────────────────
    direct_copy = [
        "raw_eeff_line",
        "raw_er_activo_line",
        "raw_flujo_line",
        "raw_rent_roll_line",
        "raw_valor_cuota_line",
        "raw_capital_suscrito_line",
    ]
    for table in direct_copy:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        cols = [d[1] for d in src.execute(f"PRAGMA table_info({table})")]
        placeholders = ",".join("?" * len(cols))
        dst.executemany(
            f"INSERT INTO {table}({','.join(cols)}) VALUES ({placeholders})",
            rows,
        )
        counts[table] = len(rows)

    # ── raw_dividendo_line: merge raw_dividendo_line + fact_dividendo ──
    # TRI dividends from raw_dividendo_line
    tri_rows = src.execute(
        "SELECT fondo_key, nemotecnico, fecha_pago, monto_uf_cuota, monto_clp_cuota, "
        "periodo, source_file, file_hash, loaded_at, superseded_at "
        "FROM raw_dividendo_line"
    ).fetchall()
    dst.executemany(
        "INSERT INTO raw_dividendo_line(fondo_key, nemotecnico, fecha_pago, "
        "monto_uf_cuota, monto_clp_cuota, periodo, source_file, file_hash, "
        "loaded_at, superseded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        tri_rows,
    )

    # PT dividends from fact_dividendo (monto = CLP/cuota, fondo_key inferred from nemotecnico)
    pt_rows = src.execute(
        "SELECT nemotecnico, fecha_pago, monto, loaded_at FROM fact_dividendo"
    ).fetchall()
    pt_mapped = []
    for nemo, fecha, monto_clp, loaded_at in pt_rows:
        if nemo.startswith("CFITOERI"):
            fondo_key = "TRI"
        elif nemo.startswith("CFITOPT") or nemo.startswith("CFITOPTA"):
            fondo_key = "PT"
        else:
            # fallback: derive from dim_serie if exists
            row = src.execute(
                "SELECT fondo_key FROM dim_serie WHERE nemotecnico=?", (nemo,)
            ).fetchone()
            fondo_key = row[0] if row else "PT"
        # periodo from fecha_pago YYYY-MM
        periodo = fecha[:7] if fecha and len(fecha) >= 7 else None
        pt_mapped.append((fondo_key, nemo, fecha, None, monto_clp, periodo,
                          "legacy_fact_dividendo", None, loaded_at, None))

    dst.executemany(
        "INSERT INTO raw_dividendo_line(fondo_key, nemotecnico, fecha_pago, "
        "monto_uf_cuota, monto_clp_cuota, periodo, source_file, file_hash, "
        "loaded_at, superseded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        pt_mapped,
    )
    counts["raw_dividendo_line"] = len(tri_rows) + len(pt_mapped)

    # ── raw_precio_cuota_line (from fact_precio_cuota) ──────
    precio_rows = src.execute(
        "SELECT nemotecnico, fecha, precio, fuente, loaded_at FROM fact_precio_cuota"
    ).fetchall()
    dst.executemany(
        "INSERT OR IGNORE INTO raw_precio_cuota_line"
        "(nemotecnico, fecha, precio_clp, fuente, loaded_at) VALUES (?,?,?,?,?)",
        precio_rows,
    )
    counts["raw_precio_cuota_line"] = len(precio_rows)

    # ── derived_kpi ──────────────────────────────────────────
    kpi_rows = src.execute(
        "SELECT entidad_tipo, entidad_key, periodo, kpi, valor, unidad, "
        "recipe, ingest_run_id, computed_at FROM derived_kpi"
    ).fetchall()
    dst.executemany(
        "INSERT OR IGNORE INTO derived_kpi(entidad_tipo, entidad_key, periodo, kpi, "
        "valor, unidad, recipe, ingest_run_id, computed_at) VALUES (?,?,?,?,?,?,?,?,?)",
        kpi_rows,
    )
    counts["derived_kpi"] = len(kpi_rows)

    dst.commit()
    src.close()
    dst.close()

    print("\n--- Migration complete ---")
    for table, n in counts.items():
        print(f"  {table}: {n} rows")
    print(f"\nNew DB: {DST}")


if __name__ == "__main__":
    run()
