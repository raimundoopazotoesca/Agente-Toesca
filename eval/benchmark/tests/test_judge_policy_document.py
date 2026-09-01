from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.benchmark.graders import judge


POLICY_PATH = Path(__file__).resolve().parents[3] / "docs" / "toesca-analyst-llm-judge-policy-v1.md"


def test_policy_names_every_current_judge_member_and_preserves_deterministic_authority():
    """A new judge-owned member must be governed before it can ship."""
    policy = POLICY_PATH.read_text(encoding="utf-8")

    for name in judge.DIMENSION_NAMES + judge.GATE_NAMES:
        assert f"`{name}`" in policy

    assert "must never re-score or override a deterministic verdict" in policy
