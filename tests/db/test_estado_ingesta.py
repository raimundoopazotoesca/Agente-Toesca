from __future__ import annotations

from datetime import date

from tools.db.estado_ingesta import (
    _shift_periodo,
    _periodo_en_curso,
    _periodo_cerrado,
)


def test_shift_periodo_forward_within_year():
    assert _shift_periodo("2026-01", 2) == "2026-03"


def test_shift_periodo_forward_across_year():
    assert _shift_periodo("2025-11", 3) == "2026-02"


def test_shift_periodo_backward_across_year():
    assert _shift_periodo("2026-01", -1) == "2025-12"


def test_periodo_en_curso_mensual():
    assert _periodo_en_curso(date(2026, 7, 23), "mensual") == "2026-07"


def test_periodo_en_curso_trimestral_mid_quarter():
    # Julio cae en el trimestre Jul-Sep, que termina en Septiembre
    assert _periodo_en_curso(date(2026, 7, 23), "trimestral") == "2026-09"


def test_periodo_en_curso_trimestral_first_month_of_quarter():
    # Enero cae en el trimestre Ene-Mar, que termina en Marzo
    assert _periodo_en_curso(date(2026, 1, 5), "trimestral") == "2026-03"


def test_periodo_cerrado_mensual():
    assert _periodo_cerrado("2026-07", "mensual") == "2026-06"


def test_periodo_cerrado_trimestral():
    assert _periodo_cerrado("2026-09", "trimestral") == "2026-06"


def test_periodo_cerrado_trimestral_year_wrap():
    assert _periodo_cerrado("2026-03", "trimestral") == "2025-12"
