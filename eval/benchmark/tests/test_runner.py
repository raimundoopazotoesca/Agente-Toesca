from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.adapters.base import Turn, Usage
from eval.benchmark.cases_loader import CASES_DIR, load_cases
from eval.benchmark.runner import run_case


class _Session:
    def __init__(self):
        self._answers = iter(("PT 50% en 2026-06", "Apo 40% en 2026-06"))

    def ask(self, _question: str) -> Turn:
        return Turn(text=next(self._answers), usage=Usage(provider="test", calls=0))


class _Adapter:
    name = "test"

    def new_session(self, _session_id: str) -> _Session:
        return _Session()


def test_run_case_passes_declared_correction_context_to_f5(monkeypatch):
    case = next(case for case in load_cases(CASES_DIR, split="dev") if case.id == "tce-entitycorrection-001")
    received = []

    def fake_score_turn(turn, turn_spec, resolved, correction_context=None):
        received.append(correction_context)
        from eval.benchmark.graders.deterministic import score_turn
        return score_turn(turn, turn_spec, resolved, correction_context=correction_context)

    monkeypatch.setattr("eval.benchmark.runner.score_turn", fake_score_turn)
    monkeypatch.setattr("eval.benchmark.runner.resolve_ground_truth", lambda *_args: {})
    run_case(_Adapter(), case, sandbox=None)

    assert received == [None, ({"fondo": "PT"}, {"fondo": "Apo"})]
