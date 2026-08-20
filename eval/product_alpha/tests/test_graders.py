from eval.product_alpha.cases import load_cases
from eval.product_alpha.grader import grade_case
from eval.product_alpha.models import TrialEvidence


def test_canonical_case_accepts_canonical_value_and_rejects_alternative():
    case = load_cases()[0]

    accepted = grade_case(case, TrialEvidence(response_text="La vacancia fue 5,945%."))
    rejected = grade_case(case, TrialEvidence(response_text="La vacancia fue 5,39%."))

    assert accepted.passed
    assert not rejected.passed
    assert "forbidden_number:5.39" in rejected.failed_constraints


def test_ranking_case_requires_the_observed_driver_entities():
    case = load_cases()[1]

    result = grade_case(case, TrialEvidence(response_text="Mall Curicó y Apoquindo 3001 son focos."))

    assert result.passed


def test_presentation_case_rejects_internal_evidence_labels():
    case = load_cases()[5]

    result = grade_case(case, TrialEvidence(response_text="Dato verificado: la vacancia bajó."))

    assert not result.passed
    assert "forbidden_phrase:dato verificado:" in result.failed_constraints


def test_capability_constraints_and_trials_are_independent():
    case = load_cases()[7]
    failing = grade_case(case, TrialEvidence(response_text="", capabilities=frozenset()))
    passing = grade_case(case, TrialEvidence(response_text="Exploré el dato.", capabilities=frozenset({"run_sql"})))

    assert not failing.passed
    assert passing.passed
