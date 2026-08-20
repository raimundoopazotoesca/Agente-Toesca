from __future__ import annotations

import re

from eval.product_alpha.models import EvaluationResult, ProductCase, TrialEvidence


def _contains_number(text: str, value: float) -> bool:
    pattern = rf"(?<![\d.,]){re.escape(str(value)).replace(r'\.', '[.,]')}(?![\d.,])"
    return bool(re.search(pattern, text))


def grade_case(case: ProductCase, trial: TrialEvidence) -> EvaluationResult:
    text = trial.response_text.casefold()
    failures: list[str] = []
    for value in case.deterministic.get("required_numbers", []):
        if not _contains_number(text, float(value)):
            failures.append(f"required_number:{value}")
    for value in case.prohibited.get("numbers", []):
        if _contains_number(text, float(value)):
            failures.append(f"forbidden_number:{value}")
    for entity in case.deterministic.get("required_entities", []):
        if str(entity).casefold() not in text:
            failures.append(f"required_entity:{entity}")
    for phrase in case.prohibited.get("phrases", []):
        if str(phrase).casefold() in text:
            failures.append(f"forbidden_phrase:{str(phrase).casefold()}")
    for capability in case.capabilities:
        if capability not in trial.capabilities:
            failures.append(f"required_capability:{capability}")
    return EvaluationResult(case_id=case.id, passed=not failures, failed_constraints=tuple(failures))
