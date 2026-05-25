"""Tests del backfill histórico (Fase 2)."""
from tools.db.backfill import _periodo_jll, _periodo_tresa


def test_periodo_jll():
    assert _periodo_jll("2509 Rent Roll y NOI.xlsx") == "2025-09"
    assert _periodo_jll("2601 Rent Roll y NOI.xlsx") == "2026-01"
    assert _periodo_jll("2603 Rent Roll y NOI JLL.xlsx") == "2026-03"


def test_periodo_jll_invalido():
    assert _periodo_jll("Rent Roll sin fecha.xlsx") is None


def test_periodo_tresa():
    assert _periodo_tresa("Excel Tres A Viña Marzo 2026.xlsx") == "2026-03"
    assert _periodo_tresa("Excel Tres A Curicó Diciembre 2025.xlsx") == "2025-12"
    assert _periodo_tresa("Excel Tres A Viña Enero 2026.xlsx") == "2026-01"


def test_periodo_tresa_invalido():
    assert _periodo_tresa("archivo sin mes ni año.xlsx") is None
    assert _periodo_tresa("solo Marzo sin año.xlsx") is None
