"""A3.3 integration tests: the post-FinalPresenter trend-drift check in
presentation.py. Covers the adversarial matrix from the A3.3 implementation
authorization (rule 9) for cases D/E and the presenter-level A-C cases."""
from __future__ import annotations

from types import SimpleNamespace

from tools.analyst_runtime.presentation import AllowedClaim, OpenAIResponsesFinalPresenter


CLAIM = AllowedClaim("c1", "e1", "noi", "A", 120.0, "clp", "2026-02", entity_display="Torre A")
TREND_INDEX_DOWN = {("A", "noi"): "DOWN"}


class _Responses:
    def __init__(self, output: str | Exception):
        self.output = output
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.output, Exception):
            raise self.output
        return SimpleNamespace(output_text=self.output)


class _Client:
    def __init__(self, output: str | Exception):
        self.responses = _Responses(output)


def _present(draft: str, output: str, claims=(CLAIM,), trend_index=TREND_INDEX_DOWN):
    client = _Client(output)
    result = OpenAIResponsesFinalPresenter(client, "gpt-5.6-terra").present(
        user_message="¿Cómo evolucionó el NOI de Torre A?", draft_answer=draft, claims=claims, trend_index=trend_index,
    )
    return result


def _segments(*, text: str) -> str:
    return ('{"segments":[{"type":"text","text":"' + text + '"},'
            '{"type":"claim_ref","claim_id":"c1"}]}')


# A/C: same direction (exact word or synonym) -> PASS -----------------------

def test_same_direction_exact_word_passes():
    draft = "El NOI de Torre A cayó a"
    result = _present(draft, _segments(text="El NOI de Torre A cayó a "))
    assert result.applied is True
    assert result.integrity_status == "passed"


def test_same_direction_different_synonym_passes():
    draft = "El NOI de Torre A cayó a"
    result = _present(draft, _segments(text="El NOI de Torre A disminuyó a "))
    assert result.applied is True
    assert result.integrity_status == "passed"


# B: direction changed -> FAIL -----------------------------------------------

def test_direction_inverted_by_presenter_fails_closed():
    draft = "El NOI de Torre A cayó a"
    result = _present(draft, _segments(text="El NOI de Torre A subió a "))
    assert result.applied is False
    assert result.content == draft
    assert result.integrity_status == "presentation_trend_drift"


# D: presenter introduces a trend assertion the draft never made -> FAIL ----

def test_presenter_introducing_a_new_trend_assertion_fails_closed():
    draft = "El NOI de Torre A fue"
    result = _present(draft, _segments(text="El NOI de Torre A cayó a "))
    assert result.applied is False
    assert result.content == draft
    assert result.integrity_status == "presentation_trend_introduced"


# E: presenter removes a trend assertion the draft had -> PASS (omission) ---

def test_presenter_removing_a_trend_assertion_passes():
    draft = "El NOI de Torre A cayó a"
    result = _present(draft, _segments(text="El NOI de Torre A fue "))
    assert result.applied is True
    assert result.integrity_status == "passed"


# No trend_index at all (no eligible derived claim anywhere in the turn):
# the check must be a no-op, never block a normal presentation.

def test_no_trend_index_is_a_no_op():
    draft = "El NOI de Torre A fue"
    result = _present(draft, _segments(text="El NOI de Torre A fue "), trend_index=None)
    assert result.applied is True
    assert result.integrity_status == "passed"


def test_empty_trend_index_is_a_no_op():
    draft = "El NOI de Torre A fue"
    result = _present(draft, _segments(text="El NOI de Torre A fue "), trend_index={})
    assert result.applied is True
    assert result.integrity_status == "passed"
