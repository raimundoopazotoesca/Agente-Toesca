"""Tests de repo_flujo."""
from tools.db import repo_audit, repo_flujo


def _run(tmp_db):
    return repo_audit.start_ingest_run(tmp_db, tool="t", source_file=None, file_hash="HF")


def test_insert_and_list(tmp_db):
    rid = _run(tmp_db)
    n = repo_flujo.insert_lines(
        tmp_db,
        [
            {
                "activo_key": "INMOSA",
                "periodo": "2026-04",
                "cuenta_codigo": None,
                "cuenta_nombre": "Ingresos",
                "monto_clp": 12345.0,
                "monto_uf": None,
                "source_file": "/x.xlsx",
                "source_sheet": "Flujo",
                "source_row": 7,
                "file_hash": "HF",
            }
        ],
        rid,
    )
    assert n == 1
    rows = repo_flujo.list_by_periodo(tmp_db, "INMOSA", "2026-04")
    assert len(rows) == 1


def test_idempotente(tmp_db):
    rid = _run(tmp_db)
    line = {"activo_key": "INMOSA", "periodo": "2026-04", "source_row": 1, "file_hash": "HF"}
    assert repo_flujo.insert_lines(tmp_db, [line], rid) == 1
    assert repo_flujo.insert_lines(tmp_db, [line], rid) == 0


def test_mark_superseded(tmp_db):
    rid = _run(tmp_db)
    repo_flujo.insert_lines(
        tmp_db,
        [{"activo_key": "INMOSA", "periodo": "2026-04", "source_row": 1, "file_hash": "HF"}],
        rid,
    )
    repo_flujo.mark_superseded(tmp_db, file_hash="HF")
    assert repo_flujo.list_by_periodo(tmp_db, "INMOSA", "2026-04") == []
