"""Tests de repo_rent_roll."""
from tools.db import repo_audit, repo_rent_roll


def _seed_run(tmp_db):
    return repo_audit.start_ingest_run(
        tmp_db, tool="ingest_rent_roll_jll", source_file="/x/rr.xlsx", file_hash="HASH1"
    )


def test_insert_lines(tmp_db):
    run_id = _seed_run(tmp_db)
    n = repo_rent_roll.insert_lines(
        tmp_db,
        lines=[
            {
                "activo_key": "PT",
                "periodo": "2026-04",
                "unidad": "1001",
                "arrendatario": "Acme",
                "m2": 100.5,
                "renta_uf": 50.0,
                "vencimiento": "2027-12-31",
                "source_file": "/x/rr.xlsx",
                "source_sheet": "RR",
                "source_row": 5,
                "file_hash": "HASH1",
            }
        ],
        ingest_run_id=run_id,
    )
    assert n == 1


def test_insert_lines_idempotente(tmp_db):
    run_id = _seed_run(tmp_db)
    line = {
        "activo_key": "PT",
        "periodo": "2026-04",
        "source_row": 5,
        "file_hash": "HASH1",
    }
    assert repo_rent_roll.insert_lines(tmp_db, [line], run_id) == 1
    assert repo_rent_roll.insert_lines(tmp_db, [line], run_id) == 0


def test_list_by_periodo(tmp_db):
    run_id = _seed_run(tmp_db)
    repo_rent_roll.insert_lines(
        tmp_db,
        [
            {"activo_key": "PT", "periodo": "2026-04", "source_row": 1, "file_hash": "H1"},
            {"activo_key": "PT", "periodo": "2026-04", "source_row": 2, "file_hash": "H1"},
            {"activo_key": "PT", "periodo": "2026-03", "source_row": 1, "file_hash": "H2"},
        ],
        run_id,
    )
    rows = repo_rent_roll.list_by_periodo(tmp_db, activo_key="PT", periodo="2026-04")
    assert len(rows) == 2


def test_mark_superseded(tmp_db):
    run_id = _seed_run(tmp_db)
    repo_rent_roll.insert_lines(
        tmp_db,
        [{"activo_key": "PT", "periodo": "2026-04", "source_row": 1, "file_hash": "H1"}],
        run_id,
    )
    repo_rent_roll.mark_superseded(tmp_db, file_hash="H1")
    row = tmp_db.execute(
        "SELECT superseded_at FROM raw_rent_roll_line WHERE file_hash=?", ("H1",)
    ).fetchone()
    assert row["superseded_at"] is not None
