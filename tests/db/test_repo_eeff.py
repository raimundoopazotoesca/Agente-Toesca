"""Tests de repo_eeff."""
from tools.db import repo_audit, repo_eeff
import pytest


def _seed_run(tmp_db):
    return repo_audit.start_ingest_run(
        tmp_db, tool="ingest_eeff_pdf", source_file="/x/eeff.pdf", file_hash="HX"
    )


def test_insert_and_list(tmp_db):
    run_id = _seed_run(tmp_db)
    n = repo_eeff.insert_lines(
        tmp_db,
        lines=[
            {
                "fondo_key": "PT",
                "periodo": "2026-03",
                "cuenta_codigo": None,
                "cuenta_nombre": "Activos totales",
                "monto_clp": 1_000_000.0,
                "monto_uf": None,
                "source_file": "/x/eeff.pdf",
                "source_row": 12,
                "file_hash": "HX",
            }
        ],
        ingest_run_id=run_id,
    )
    assert n == 1

    rows = repo_eeff.list_by_periodo(tmp_db, fondo_key="PT", periodo="2026-03")
    assert len(rows) == 1
    assert rows[0]["cuenta_nombre"] == "Activos totales"


@pytest.mark.xfail(
    reason="Producción no tiene UNIQUE(file_hash, source_row): el INSERT OR IGNORE "
           "de los repos es un no-op y por eso hay duplicados vivos. La restricción "
           "entra tras el saneamiento (ROADMAP F0.4); cuando eso ocurra este test "
           "pasará y strict=True obligará a quitar el marcador.",
    strict=True,
)
def test_insert_idempotente(tmp_db):
    run_id = _seed_run(tmp_db)
    line = {"fondo_key": "PT", "periodo": "2026-03", "source_row": 1, "file_hash": "HX"}
    assert repo_eeff.insert_lines(tmp_db, [line], run_id) == 1
    assert repo_eeff.insert_lines(tmp_db, [line], run_id) == 0


def test_mark_superseded(tmp_db):
    run_id = _seed_run(tmp_db)
    repo_eeff.insert_lines(
        tmp_db,
        [{"fondo_key": "PT", "periodo": "2026-03", "source_row": 1, "file_hash": "HX"}],
        run_id,
    )
    repo_eeff.mark_superseded(tmp_db, file_hash="HX")
    rows = repo_eeff.list_by_periodo(tmp_db, fondo_key="PT", periodo="2026-03")
    assert rows == []
