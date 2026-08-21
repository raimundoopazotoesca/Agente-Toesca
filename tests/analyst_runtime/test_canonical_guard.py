from tools.analyst_runtime.canonical_guard import validate_and_render
from tools.analyst_runtime.transport import ToolEvidence


EVIDENCE = ToolEvidence("e1", "canonical_metric", facts=({"metric_key": "vacancia", "value": 5.945, "unit": "%", "entity_id": "A", "period": "2026-06"},))


def test_renders_only_value_from_matching_evidence():
    result = validate_and_render({"fragments": [{"type": "text", "text": "Fue "}, {"type": "canonical_metric_ref", "claim_id": "c"}], "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "vacancia", "value": 5.945, "unit": "%", "entity_id": "A", "period": "2026-06"}]}, [EVIDENCE])
    assert result.content == "Fue 5.945%"
    assert result.valid


def test_rejects_model_value_conflict_and_uses_evidence_fallback():
    result = validate_and_render({"fragments": [{"type": "canonical_metric_ref", "claim_id": "c"}], "canonical_metric_claims": [{"claim_id": "c", "evidence_id": "e1", "metric_key": "vacancia", "value": 5.39, "unit": "%", "entity_id": "A", "period": "2026-06"}]}, [EVIDENCE])
    assert not result.valid
    assert result.content == "vacancia: 5.945%"
