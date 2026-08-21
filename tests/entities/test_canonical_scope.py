from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.entities.canonical_scope import CanonicalScopeValidator, expected_asset_universe


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dim_fondo (fondo_key TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE dim_activo (activo_key TEXT, fondo_key TEXT, vigente_hasta TEXT)")
    conn.executemany("INSERT INTO dim_fondo VALUES (?)", [("TRI",), ("PT",)])
    conn.executemany("INSERT INTO dim_activo VALUES (?, ?, ?)", [
        ("INMOSA", "TRI", None),
        ("Apo3001", "TRI", None),
        ("Strip Machali", "TRI", "2025-08"),
        ("Torre A", "PT", None),
    ])
    conn.commit()
    conn.close()
    return path


def test_validate_fund_exact_match_only(db: Path):
    validator = CanonicalScopeValidator(db)
    assert validator.validate_fund("TRI").valid is True
    assert validator.validate_fund("tri").valid is False
    assert validator.validate_fund("NoSuchFund").valid is False


def test_validate_asset_exact_match_only(db: Path):
    validator = CanonicalScopeValidator(db)
    assert validator.validate_asset("Apo3001").valid is True
    assert validator.validate_asset("apo3001").valid is False


def test_null_vigente_hasta_is_decidable_and_included(db: Path):
    """Per migration 050_dim_activo_vigente_hasta.sql: NULL = activo vigente
    (no end date), not 'unknown data'. It must be included in the universe,
    not excluded and not treated as undetermined."""
    universe = expected_asset_universe(db, "TRI", "2026-06")
    assert universe.status == "determined"
    assert "INMOSA" in universe.eligible_keys
    assert "Apo3001" in universe.eligible_keys


def test_temporal_exclusion_after_vigente_hasta(db: Path):
    before = expected_asset_universe(db, "TRI", "2025-08")
    after = expected_asset_universe(db, "TRI", "2025-09")
    assert "Strip Machali" in before.eligible_keys
    assert "Strip Machali" not in after.eligible_keys
    assert "INMOSA" in after.eligible_keys  # unaffected, still vigente


def test_undetermined_universe_for_unknown_fund(db: Path):
    result = expected_asset_universe(db, "NoSuchFund", "2026-06")
    assert result.status == "undetermined"
    assert result.eligible_keys == frozenset()
