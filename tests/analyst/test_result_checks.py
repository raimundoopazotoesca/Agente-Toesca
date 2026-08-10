from tools.analyst.result_checks import check_result


def test_vacancia_within_bounds_passes():
    result = check_result("vacancia_pct", 45.0)
    assert result.passed is True
    assert result.violated == []


def test_vacancia_over_100_fails():
    result = check_result("vacancia_pct", 134.0)
    assert result.passed is False
    assert "0 <= value <= 100" in result.violated


def test_metric_without_invariants_always_passes():
    result = check_result("noi", -50000.0)
    assert result.passed is True


def test_unknown_metric_raises():
    import pytest
    with pytest.raises(KeyError):
        check_result("metrica_inexistente", 1.0)
