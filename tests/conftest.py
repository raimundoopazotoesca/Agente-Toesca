"""Fixtures globales para tests."""
import json
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path a un archivo SQLite temporal (no se aplica schema)."""
    return str(tmp_path / "test.db")


@pytest.fixture
def tmp_db(tmp_db_path):
    """Conexión SQLite a un archivo temporal con schema aplicado."""
    from tools.db.connection import apply_migrations, get_conn_for

    apply_migrations(tmp_db_path)
    conn = get_conn_for(tmp_db_path)
    yield conn
    conn.close()


@pytest.fixture
def governed_v84_db(tmp_path):
    """Deterministic schema-84 temp DB for tests that exercise the real
    ResolveEntityAction -> SchemaSearchAction -> RunSqlAction path over the
    governed rent-roll dataset (``v_rent_roll_semantic``, added in migration
    083; migration 084 only touches the unrelated vacancy/parking views).

    ``BASELINE_VERSION`` in tools/db/connection.py is 84 and ``baseline.sql``
    is *equivalent* to applying migrations 001..084 (see its header) -- so
    applying only the baseline gives an exact schema-84 DB deterministically,
    without depending on whatever version the tracked
    memory/agente_toesca_v2.db happens to be at (it was 81 at the time this
    fixture was written -- see tests/db/test_baseline.py for the invariant
    that keeps baseline.sql honest), and without accidentally picking up the
    JLL-gated migrations 085-091 that plain ``apply_migrations()`` would
    apply next on an empty DB.

    Seeds the golden Apo3001 2026-06 rent-roll used across
    tests/datasets/test_rent_roll_semantics.py's ``_pre_083_db`` fixture (10
    vacant units summing m2=1656.6 across office/parking/storage categories,
    15 occupied units), plus the ``dim_activo``/``dim_fondo`` rows entity
    resolution needs to match "Apoquindo 3001" -> "Apo3001" via
    ``exact_display`` (the display name must equal semantic/entities.yaml's
    ``nombre`` for that key).
    """
    from tools.db.connection import _aplicar_baseline, _ensure_schema_version_table, get_conn_for

    db_path = tmp_path / "governed-v84.db"
    conn = get_conn_for(str(db_path))
    try:
        _ensure_schema_version_table(conn)
        _aplicar_baseline(conn)
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 84

        # dim_fondo (TRI/PT/Apo) is already seeded by the baseline itself --
        # see tests/db/test_baseline.py::test_seeds_de_dimensiones_presentes.
        conn.execute(
            "INSERT OR IGNORE INTO dim_activo(activo_key, fondo_key, nombre) VALUES "
            "('Apo3001', 'TRI', 'Apoquindo 3001')"
        )

        def row(unidad, arrendatario, m2, categoria, source_row):
            return (
                "Apo3001", "2026-06", unidad, arrendatario, m2,
                json.dumps({"tipo_activo_2": categoria}),
                "fixture.xlsx", "Rent Roll", source_row, "fixture-governed-v84",
            )

        vacancies = [
            row(f"Piso {index}", "Vacante", m2, "Oficina", index)
            for index, m2 in enumerate((440.3, 440.3, 234.0, 234.0, 234.0), start=1)
        ]
        vacancies.extend(
            row(f"Zocalo {index}", "Vacante", 8.0, "Estacionamiento", index)
            for index in range(6, 9)
        )
        vacancies.extend(
            row(f"Bodega {index}", "Vacante", 25.0, "Bodega", index)
            for index in range(9, 11)
        )
        occupied = [
            row(f"Oficina ocupada {index}", "Tenant", 100.0, "Oficina", index)
            for index in range(11, 26)
        ]
        conn.executemany(
            """
            INSERT INTO raw_rent_roll_line(
                activo_key, periodo, unidad, arrendatario, m2, extra_json,
                source_file, source_sheet, source_row, file_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            vacancies + occupied,
        )
        conn.commit()
    finally:
        conn.close()
    return db_path
