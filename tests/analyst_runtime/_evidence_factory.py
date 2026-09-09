"""Test-only helper for constructing ToolEvidence fixtures against the A3.2a
contract. Mirrors ToolEvidence.build's shape but keeps positional
(evidence_id, evidence_class) call sites terse for fixture-heavy test files.
Not a second evidence system: it is a thin, test-scoped wrapper around the
same ToolEvidence.build factory production code uses."""
from __future__ import annotations

from typing import Any

from tools.analyst_runtime.transport import ToolEvidence


def mk_evidence(evidence_id: str, evidence_class: str, *, facts: tuple[dict[str, Any], ...] = (),
                 scope: dict[str, Any] | None = None, semantic_contract: dict[str, Any] | None = None,
                 provenance: dict[str, Any] | None = None, coverage: dict[str, Any] | None = None,
                 tool_name: str = "test_tool", source_kind: str | None = None,
                 metric_id: str | None = None, dataset_id: str | None = None,
                 requested_temporal: dict[str, Any] | None = None, granularity: str = "month") -> ToolEvidence:
    return ToolEvidence.build(
        evidence_id=evidence_id, evidence_class=evidence_class, tool_name=tool_name, source_kind=source_kind,
        scope=scope or {}, semantic_contract=semantic_contract or {}, provenance=provenance or {}, facts=facts,
        coverage=coverage, metric_id=metric_id, dataset_id=dataset_id,
        requested_temporal=requested_temporal, granularity=granularity,
    )
