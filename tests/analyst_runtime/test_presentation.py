from __future__ import annotations

from types import SimpleNamespace

from tools.analyst_runtime.presentation import OpenAIResponsesFinalPresenter


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
        user_message="¿Cuál es la vacancia?", draft_answer=draft
    )
    return result, client.responses.calls


def test_presenter_accepts_markdown_that_preserves_explicit_facts():
    draft = "La vacancia de TRI en junio de 2026 fue 5,945%.\n\nDato verificado: corresponde al KPI."
    result, calls = _present(draft, "La vacancia de TRI en junio de 2026 fue **5,945%**.")
    assert result.applied is True
    assert result.content.endswith("**5,945%**.")
    assert result.integrity_status == "passed"
    assert calls[0]["tools"] == []
    assert calls[0]["tool_choice"] == "none"
    assert calls[0]["store"] is False


def test_presenter_falls_closed_for_changed_or_new_numbers():
    draft = "La vacancia fue 5,945%."
    for output in ("La vacancia fue 6,2%.", "La vacancia fue 5,95%.", "La vacancia fue 5,945% y 94,1%."):
        result, _ = _present(draft, output)
        assert result.applied is False
        assert result.content == draft
        assert result.integrity_status == "failed_facts"


def test_presenter_falls_closed_for_empty_error_or_missing_caveat():
    draft = "La vacancia fue 5,945%, aunque la cobertura es parcial."
    for output in ("", RuntimeError("provider unavailable"), "La vacancia fue 5,945%."):
        result, _ = _present(draft, output)
        assert result.applied is False
        assert result.content == draft


def test_presenter_accepts_a_material_caveat_when_it_is_preserved():
    draft = "La vacancia fue 5,945%, aunque la cobertura es parcial."
    result, _ = _present(draft, "La vacancia fue **5,945%**, aunque la cobertura es parcial.")

    assert result.applied is True
    assert result.integrity_status == "passed"
