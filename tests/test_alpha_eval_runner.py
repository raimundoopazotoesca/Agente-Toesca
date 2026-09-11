from __future__ import annotations

import pytest


@pytest.mark.parametrize("module_name", [
    "eval.alpha_eval_v1.run_alpha_eval",
    "eval.alpha_eval_v1.run_alpha_eval_recovery",
])
def test_capturing_presenter_forwards_runtime_claims(module_name, monkeypatch):
    """Keep Alpha capture compatible with the runtime presenter contract."""
    module = __import__(module_name, fromlist=["CapturingPresenter"])

    captured = {}

    class InnerPresenter:
        def present(self, *, user_message, draft_answer, claims, trend_index=None):
            captured.update(user_message=user_message, draft_answer=draft_answer, claims=claims)
            return "result"

    monkeypatch.setattr(module, "OpenAIResponsesFinalPresenter", lambda *_: InnerPresenter())
    presenter = module.CapturingPresenter(object(), "model")

    assert presenter.present(user_message="pregunta", draft_answer="borrador", claims=("claim",)) == "result"
    assert captured == {"user_message": "pregunta", "draft_answer": "borrador", "claims": ("claim",)}
