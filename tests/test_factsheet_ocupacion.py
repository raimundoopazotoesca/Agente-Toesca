from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts" / "build_factsheet.py").read_text(encoding="utf-8")


def test_grafico_ocupacion_inmosa_se_corta_al_periodo_operacional():
    """El histórico debe respetar el mes elegido en el selector operacional."""
    assert "function limitOcupacionInmosaData(data, cutoff)" in SOURCE
    assert "limitOcupacionInmosaData(F.page6.ocupacion_inmosa, usadoOp)" in SOURCE

