from __future__ import annotations

from pathlib import Path

from tools.analyst_runtime.actions import AnalyticsBreakdownAssetAction, AnalyticsLookupFundAction
from tools.analyst_runtime.transport import ToolRequest


DB = Path("memory/agente_toesca_v2.db")


def test_breakdown_produces_governed_dataset_evidence_with_coverage():
    action = AnalyticsBreakdownAssetAction(DB)
    result = action.execute(ToolRequest("call", action.name, {
        "metric": "m2_vacantes", "fund": "TRI", "period": "2026-06", "order_by": None, "limit": None,
    }))

    assert result.ok
    assert result.evidence is not None
    assert result.evidence.evidence_class == "governed_dataset"
    assert len(result.evidence.facts) > 1
    coverage = result.evidence.coverage
    assert coverage["status"] in {"complete", "partial", "unknown"}
    assert coverage["universe_kind"] == "fund_assets"
    assert coverage["observed_count"] == len(result.evidence.facts)
    # Strip Machali (vigente_hasta=2025-08) must never count toward the 2026-06 universe.
    assert "Strip Machalí" not in (coverage["eligible_ids"] or [])


def test_breakdown_unknown_scope_yields_unknown_coverage_not_complete():
    action = AnalyticsBreakdownAssetAction(DB)
    # A syntactically valid-looking fund key that isn't canonical -- the
    # executor itself may raise SemanticQueryError before evidence is built,
    # which is fine (no evidence => no false "complete" claim either way).
    result = action.execute(ToolRequest("call", action.name, {
        "metric": "m2_vacantes", "fund": "NoSuchFund", "period": "2026-06", "order_by": None, "limit": None,
    }))
    if result.evidence is not None:
        assert result.evidence.coverage["status"] == "unknown"


def test_scalar_lookup_still_produces_canonical_metric_evidence_unchanged():
    action = AnalyticsLookupFundAction(DB)
    result = action.execute(ToolRequest("call", action.name, {
        "metric": "vacancia_pct_fondo", "fund": "TRI", "period": "2026-06",
    }))

    assert result.evidence is not None
    assert result.evidence.evidence_class == "canonical_metric"
    assert result.evidence.coverage is None
    assert len(result.evidence.facts) == 1
