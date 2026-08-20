from pathlib import Path

import pytest

from eval.product_alpha.cases import CaseValidationError, load_cases


def test_loads_the_eight_initial_product_regressions():
    cases = load_cases()

    assert [case.id for case in cases] == [
        "alpha-canonical-source",
        "alpha-ranking-drivers",
        "alpha-entity-resolution",
        "alpha-coverage-claim",
        "alpha-follow-up",
        "alpha-presentation",
        "alpha-simple-lookup",
        "alpha-raw-exploration",
    ]
    canonical = cases[0]
    assert canonical.deterministic["required_numbers"] == [5.945]
    assert canonical.prohibited["numbers"] == [5.39]


def test_rejects_duplicate_case_ids(tmp_path: Path):
    case = """id: duplicate\nturns: [hola]\npurpose: test\ndeterministic: {}\nsemantic: {}\nprohibited: {}\ntags: [test]\n"""
    (tmp_path / "a.yaml").write_text(case, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(case, encoding="utf-8")

    with pytest.raises(CaseValidationError, match="duplicate"):
        load_cases(tmp_path)


def test_rejects_a_case_without_user_turns(tmp_path: Path):
    (tmp_path / "bad.yaml").write_text(
        "id: bad\npurpose: test\ndeterministic: {}\nsemantic: {}\nprohibited: {}\ntags: [test]\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseValidationError, match="turns"):
        load_cases(tmp_path)
