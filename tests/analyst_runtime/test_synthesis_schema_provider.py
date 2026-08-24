"""Live-provider regression: SYNTHESIS_ENVELOPE_SCHEMA must be accepted by
OpenAI's real Structured Outputs validator under strict=True.

Stage 5.4 shipped with only a mock-client test (test_structured_transport.py),
which cannot catch schema keywords OpenAI's strict subset rejects (e.g.
'oneOf' inside strict json_schema, only 'anyOf' is supported there). That gap
let a schema that always 400s in production merge and pass CI. This test
hits the real API with the exact schema/model used in production and would
have failed before the oneOf -> anyOf fix.

Skipped automatically when OPENAI_API_KEY is not configured (e.g. offline CI).
"""
from __future__ import annotations

import os

import pytest

import config  # noqa: F401 - loads OPENAI_API_KEY from .env, as production does
from tools.analyst_runtime.synthesis_schema import SYNTHESIS_ENVELOPE_SCHEMA

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="requires a real OPENAI_API_KEY to validate the schema against OpenAI's live Structured Outputs API",
)


def test_synthesis_envelope_schema_accepted_by_openai_strict_structured_outputs():
    from openai import OpenAI

    client = OpenAI(max_retries=0)
    response = client.responses.create(
        model="gpt-5.6-terra",
        instructions="Responde con un fragmento de texto trivial.",
        input=[{"role": "user", "content": "Di 'ok'."}],
        tools=[],
        tool_choice="none",
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "SynthesisEnvelope",
                "schema": SYNTHESIS_ENVELOPE_SCHEMA,
                "strict": True,
            }
        },
    )

    import json

    parsed = json.loads(response.output_text)
    assert "fragments" in parsed
    assert "canonical_metric_claims" in parsed
    assert "governed_dataset_claims" in parsed
