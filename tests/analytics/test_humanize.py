"""Human Analytical Presentation v1 -- generic tests for the display layer.

These are deliberately generic (not Toesca-specific in intent): they cover
the temporal-formatting rules, entity-display lookup, jargon-leak
prevention, and fact-integrity guarantees the spec requires, using the
existing dim_fondo/dim_activo fixtures as one concrete instantiation of a
metadata-driven, non-branching display layer.
"""
from pathlib import Path

import pytest

from tools.analytics.humanize import (
    entity_display_name,
    format_aggregation,
    format_period,
    format_period_as_of,
    format_period_range,
    humanize_text,
    strip_forbidden_jargon,
)

DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "agente_toesca_v2.db"


# --------------------------------------------------------------------------
# Period formatting -- generic temporal formatter, no hardcoded years
# --------------------------------------------------------------------------

def test_full_calendar_year_range():
    assert format_period_range("2025-01", "2025-12") == "durante 2025"
    assert format_period_range("1998-01", "1998-12") == "durante 1998"


def test_within_year_partial_range():
    assert format_period_range("2025-01", "2025-06") == "entre enero y junio de 2025"


def test_cross_year_range():
    assert format_period_range("2017-12", "2018-01") == "entre diciembre de 2017 y enero de 2018"


def test_single_month():
    assert format_period("2026-06") == "en junio de 2026"


def test_single_month_as_range_start_equals_end():
    assert format_period_range("2026-06", "2026-06") == "en junio de 2026"


def test_as_of_phrasing_for_point_in_time():
    assert format_period_as_of("2026-06") == "a junio de 2026"


def test_unparseable_period_passes_through():
    assert format_period("not-a-period") == "not-a-period"
    assert format_period_range("2025-01", "bogus") == "2025-01 a bogus"


# --------------------------------------------------------------------------
# Entity display -- sourced from dims, not hardcoded per case
# --------------------------------------------------------------------------

def test_fund_key_gets_fondo_prefix():
    assert entity_display_name("PT", DB_PATH) == "fondo PT"
    assert entity_display_name("Apo", DB_PATH) == "fondo Apo"
    assert entity_display_name("TRI", DB_PATH) == "fondo TRI"


def test_asset_key_resolves_to_dim_activo_nombre():
    assert entity_display_name("Apo4501", DB_PATH) == "Apoquindo 4501"
    assert entity_display_name("Torre A", DB_PATH) == "Torre A"


def test_unknown_entity_key_passes_through_unchanged():
    assert entity_display_name("NoSuchEntity123", DB_PATH) == "NoSuchEntity123"


def test_missing_db_path_fails_open_to_raw_key():
    assert entity_display_name("Apo4501", None) == "Apo4501"


# --------------------------------------------------------------------------
# Aggregation display -- semantic, not literal token
# --------------------------------------------------------------------------

def test_aggregation_phrases():
    assert format_aggregation("sum") == "acumulado"
    assert format_aggregation("avg") == "promedio"
    assert format_aggregation("point_in_time") == ""
    assert format_aggregation(None) == ""


# --------------------------------------------------------------------------
# Free-text humanization -- the raw_text leak path
# --------------------------------------------------------------------------

def test_humanize_text_translates_period_range():
    text = "El NOI de PT entre 2025-01..2025-12 fue de 172868.05874045362 UF."
    result = humanize_text(text, DB_PATH)
    assert "2025-01..2025-12" not in result
    assert "durante 2025" in result
    assert "fondo PT" in result
    assert "172868.05874045362" not in result
    assert "172.868,06" in result


def test_humanize_text_translates_single_period():
    text = "El LTV de TRI en 2026-06 fue 61.02%"
    result = humanize_text(text, DB_PATH)
    assert "2026-06" not in result
    assert "en junio de 2026" in result


def test_humanize_text_prefers_longest_entity_key_match():
    """Apo4501 must not be truncated to 'fondo Apo' + '4501'."""
    text = "Apo4501 tuvo vacancia alta."
    result = humanize_text(text, DB_PATH)
    assert result.startswith("Apoquindo 4501")
    assert "fondo Apo4501" not in result


def test_humanize_text_no_db_path_still_fixes_periods_and_numbers():
    text = "Valor en 2025-06: 1234.5678"
    result = humanize_text(text, None)
    assert "2025-06" not in result
    assert "en junio de 2025" in result
    assert "1234.5678" not in result


def test_humanize_text_leaves_ordinary_prose_untouched():
    text = "El fondo tuvo un buen desempeño este trimestre."
    assert humanize_text(text, DB_PATH) == text


# --------------------------------------------------------------------------
# Internal-jargon leakage prevention
# --------------------------------------------------------------------------

@pytest.mark.parametrize("jargon", [
    "canonical_metric_ref", "ToolEvidence", "AllowedClaim", "SemanticQuery",
    "coverage=", "aggregation=sum",
])
def test_strip_forbidden_jargon_removes_internal_tokens(jargon):
    text = f"prefix {jargon} suffix"
    assert jargon not in strip_forbidden_jargon(text)


# --------------------------------------------------------------------------
# Fact integrity -- humanization never changes the represented magnitude
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_value", [
    ("172868.05874045362", 172868.05874045362),
    ("0.001234567", 0.001234567),
    ("999999.999", 999999.999),
])
def test_humanize_text_reformatting_preserves_magnitude(raw, expected_value):
    text = f"valor: {raw} UF"
    result = humanize_text(text, None)
    # Re-parse the Chilean-formatted number back to float and confirm it
    # round-trips to the same value within the rendered precision (2dp) --
    # i.e. presentation never silently drops/shifts magnitude.
    import re
    match = re.search(r"[\d.]+,\d{2}", result)
    assert match is not None
    rendered = match.group(0).replace(".", "").replace(",", ".")
    assert round(float(rendered), 2) == round(expected_value, 2)
