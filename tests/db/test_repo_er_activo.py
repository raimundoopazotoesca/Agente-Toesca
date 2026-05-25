"""Tests de repo_er_activo."""
from tools.db import repo_audit, repo_er_activo


def _run(tmp_db):
    return repo_audit.start_ingest_run(tmp_db, tool="t", source_file=None, file_hash="HE")


def test_insert_and_list(tmp_db):
    rid = _run(tmp_db)
    n = repo_er_activo.insert_lines(
        tmp_db,
        [
            {
                "activo_key": "Viña Centro",
                "periodo": "2026-04",
                "cuenta_codigo": None,
                "cuenta_nombre": "Arriendos",
                "monto_clp": 50000.0,
                "monto_uf": None,
                "source_file": "/x.xlsx",
                "source_sheet": "ER",
                "source_row": 10,
                "file_hash": "HE",
            }
        ],
        rid,
    )
    assert n == 1
    rows = repo_er_activo.list_by_periodo(tmp_db, "Viña Centro", "2026-04")
    assert len(rows) == 1


def test_idempotente(tmp_db):
    rid = _run(tmp_db)
    line = {"activo_key": "Viña Centro", "periodo": "2026-04", "source_row": 1, "file_hash": "HE"}
    assert repo_er_activo.insert_lines(tmp_db, [line], rid) == 1
    assert repo_er_activo.insert_lines(tmp_db, [line], rid) == 0


def test_mark_superseded(tmp_db):
    rid = _run(tmp_db)
    repo_er_activo.insert_lines(
        tmp_db,
        [{"activo_key": "Viña Centro", "periodo": "2026-04", "source_row": 1, "file_hash": "HE"}],
        rid,
    )
    repo_er_activo.mark_superseded(tmp_db, file_hash="HE")
    assert repo_er_activo.list_by_periodo(tmp_db, "Viña Centro", "2026-04") == []
