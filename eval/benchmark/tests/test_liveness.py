from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.liveness import LivenessError, assert_liveness


_DETERMINISTIC_GATES = {"F2": False, "F3": False, "F4": False, "C1": False, "C2": False, "C3": False}


def test_declared_correction_turn_requires_boolean_f5_verdict():
    reports = [{"correction_context": {"previous_entities": {"fondo": "PT"}, "corrected_entities": {"fondo": "Apo"}}, "gate_results": _DETERMINISTIC_GATES | {"F5": None}}]

    with pytest.raises(LivenessError, match="F5"):
        assert_liveness(reports)


def test_judge_owned_pending_gate_is_allowed():
    reports = [{"correction_context": None, "gate_results": _DETERMINISTIC_GATES | {"F1": None, "C4": None, "C5": None}}]

    assert_liveness(reports)
