"""Tests de repo_kpi."""
import pytest

from tools.db import repo_kpi
from tools.db.errors import NotFoundError


def test_upsert_kpi(tmp_db):
    repo_kpi.upsert(
        tmp_db,
        entidad_tipo="activo",
        entidad_key="PT",
        periodo="2026-04",
        kpi="NOI",
        valor=1_234_567.0,
        unidad="CLP",
        recipe="noi_v1",
    )
    val = repo_kpi.get(tmp_db, "activo", "PT", "2026-04", "NOI", "noi_v1")
    assert val == 1_234_567.0


def test_upsert_sobrescribe_misma_recipe(tmp_db):
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "NOI", 1.0, "CLP", "noi_v1")
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "NOI", 2.0, "CLP", "noi_v1")
    assert repo_kpi.get(tmp_db, "activo", "PT", "2026-04", "NOI", "noi_v1") == 2.0


def test_get_not_found(tmp_db):
    with pytest.raises(NotFoundError):
        repo_kpi.get(tmp_db, "activo", "PT", "2026-04", "NOI", "noi_v1")


def test_serie_temporal(tmp_db):
    for periodo, val in [("2026-01", 1.0), ("2026-02", 2.0), ("2026-03", 3.0)]:
        repo_kpi.upsert(tmp_db, "activo", "PT", periodo, "NOI", val, "CLP", "noi_v1")

    rows = repo_kpi.serie_temporal(tmp_db, "activo", "PT", "NOI")
    assert [(r["periodo"], r["valor"]) for r in rows] == [
        ("2026-01", 1.0),
        ("2026-02", 2.0),
        ("2026-03", 3.0),
    ]


def test_serie_temporal_filtra_rango(tmp_db):
    for periodo, val in [("2026-01", 1.0), ("2026-02", 2.0), ("2026-03", 3.0)]:
        repo_kpi.upsert(tmp_db, "activo", "PT", periodo, "NOI", val, "CLP", "noi_v1")
    rows = repo_kpi.serie_temporal(
        tmp_db, "activo", "PT", "NOI", desde="2026-02", hasta="2026-02"
    )
    assert [r["periodo"] for r in rows] == ["2026-02"]


def test_snapshot_periodo(tmp_db):
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "NOI", 100.0, "CLP", "noi_v1")
    repo_kpi.upsert(tmp_db, "activo", "PT", "2026-04", "vacancia", 0.05, "%", "vac_v1")
    snap = repo_kpi.snapshot_periodo(tmp_db, "activo", "PT", "2026-04")
    kpis = {r["kpi"]: r["valor"] for r in snap}
    assert kpis == {"NOI": 100.0, "vacancia": 0.05}


def test_tipo_entidad_invalido(tmp_db):
    with pytest.raises(Exception):
        repo_kpi.upsert(tmp_db, "BAD_TIPO", "X", "2026-04", "K", 1.0, "u", "r")
