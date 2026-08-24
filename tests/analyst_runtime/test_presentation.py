from __future__ import annotations

from types import SimpleNamespace

from tools.analyst_runtime.presentation import AllowedClaim, OpenAIResponsesFinalPresenter


CLAIM = AllowedClaim("c1", "e1", "vacancia_pct_fondo", "TRI", 5.945, "%", "2026-06")


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


def _present(draft: str, output: str | Exception):
    client = _Client(output)
    result = OpenAIResponsesFinalPresenter(client, "gpt-5.6-terra").present(
        user_message="¿Cuál es la vacancia?", draft_answer=draft, claims=(CLAIM,)
    )
    return result, client.responses.calls


def test_presenter_accepts_structured_segments_and_renders_the_claim():
    draft = "La vacancia de TRI en junio de 2026 fue 5,945%.\n\nDato verificado: corresponde al KPI."
    result, calls = _present(draft, '{"segments":[{"type":"text","text":"la vacancia fue "},{"type":"claim_ref","claim_id":"c1"}]}')
    assert result.applied is True
    assert result.content == "la vacancia fue TRI · 2026-06: 5,95 %"
    assert result.integrity_status == "passed"
    assert calls[0]["tools"] == []
    assert calls[0]["tool_choice"] == "none"
    assert calls[0]["store"] is False


def test_presenter_falls_closed_for_unknown_or_new_free_prose_quantities():
    draft = "La vacancia fue 5,945%."
    for output in ('{"segments":[{"type":"claim_ref","claim_id":"other"}]}',
                   '{"segments":[{"type":"text","text":"fue 6,2%"},{"type":"claim_ref","claim_id":"c1"}]}'):
        result, _ = _present(draft, output)
        assert result.applied is False
        assert result.content == draft
        assert result.integrity_status.startswith("invalid_structured_output:")


def test_presenter_falls_closed_for_empty_error_or_missing_caveat():
    draft = "La vacancia fue 5,945%, aunque la cobertura es parcial."
    for output in ("", RuntimeError("provider unavailable"), '{"segments":[]}'):
        result, _ = _present(draft, output)
        assert result.applied is False
        assert result.content == draft


def test_presenter_skips_unstructured_drafts():
    client = _Client("unused")
    result = OpenAIResponsesFinalPresenter(client, "gpt-5.6-terra").present(
        user_message="¿Cuál es la vacancia?", draft_answer="texto sin claim"
    )
    assert result.applied is False
    assert result.integrity_status == "not_applicable"
    assert client.responses.calls == []
