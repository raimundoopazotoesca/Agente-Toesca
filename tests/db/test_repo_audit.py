"""Tests del repo de audit."""
from tools.db import repo_audit


def test_start_and_finish_ingest_run(tmp_db):
    run_id = repo_audit.start_ingest_run(
        tmp_db, tool="ingest_rent_roll_jll", source_file="/x/rr.xlsx", file_hash="HASH1"
    )
    assert isinstance(run_id, int) and run_id > 0

    repo_audit.finish_ingest_run(
        tmp_db, run_id, rows_in=100, rows_loaded=98, status="ok"
    )
    row = tmp_db.execute(
        "SELECT rows_in, rows_loaded, status, ended_at FROM ingest_run WHERE id=?",
        (run_id,),
    ).fetchone()
    assert row["rows_in"] == 100
    assert row["rows_loaded"] == 98
    assert row["status"] == "ok"
    assert row["ended_at"] is not None


def test_fail_ingest_run(tmp_db):
    run_id = repo_audit.start_ingest_run(tmp_db, tool="t", source_file=None, file_hash=None)
    repo_audit.fail_ingest_run(tmp_db, run_id, error="boom")
    row = tmp_db.execute(
        "SELECT status, error FROM ingest_run WHERE id=?", (run_id,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "boom"

