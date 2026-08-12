from datetime import date

from tools.analyst.temporal import resolve_temporal, TemporalResolution


_TODAY = date(2026, 8, 10)  # August 2026, for deterministic tests


def test_este_mes():
    r = resolve_temporal("¿cómo viene la vacancia este mes?", today=_TODAY)
    assert r.period == "2026-08"
    assert r.period_range is None
    assert r.comparison_period is None


def test_mes_pasado():
    r = resolve_temporal("dame el NOI del mes pasado", today=_TODAY)
    assert r.period == "2026-07"


def test_mes_pasado_cruza_anio():
    r = resolve_temporal("mes pasado", today=date(2026, 1, 15))
    assert r.period == "2025-12"


def test_este_anio():
    r = resolve_temporal("evolución de la ocupación este año", today=_TODAY)
    assert r.period is None
    assert r.period_range == ("2026-01", "2026-12")


def test_ytd():
    r = resolve_temporal("dividend yield YTD", today=_TODAY)
    assert r.period_range == ("2026-01", "2026-08")


def test_anio_pasado():
    r = resolve_temporal("NOI del año pasado", today=_TODAY)
    assert r.period_range == ("2025-01", "2025-12")


def test_mismo_periodo_anio_anterior():
    r = resolve_temporal("¿y el mismo período del año anterior?", today=_TODAY)
    assert r.comparison_period == "same_period_last_year"


def test_ultimos_12_meses():
    r = resolve_temporal("últimos 12 meses de NOI", today=_TODAY)
    assert r.period_range == ("2025-09", "2026-08")


def test_proximos_12_meses_flags_gap():
    r = resolve_temporal("proyección próximos 12 meses", today=_TODAY)
    assert r.period_range == ("2026-09", "2027-08")
    assert r.data_gap_warning is not None


def test_hoy_snapshot_behavior():
    r = resolve_temporal("saldo de caja hoy", today=_TODAY, time_behavior="snapshot")
    assert r.period == "2026-08"
    assert "snapshot" in r.label.lower() or "cierre" in r.label.lower()


def test_ultimo_cierre_flow_behavior():
    r = resolve_temporal("último cierre de NOI", today=_TODAY, time_behavior="flow")
    assert r.period is None
    assert r.label  # explains "último dato disponible", no invented period


def test_no_temporal_phrase_returns_none():
    assert resolve_temporal("vacancia de Parque Titanium", today=_TODAY) is None
