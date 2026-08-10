"""Manual eval runner for the analyst-agent intent layer. Not part of pytest
CI (makes real LLM calls via db_chat's existing provider chain). Run with:
    python tests/eval/run_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openai import OpenAI

from tools import db_chat
from tools.analyst.conversation_state import clear_state
from tools.analyst.intent import extract_intent

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"
SESSION_ID = "eval-session"


def _llm_call(prompt: str) -> str:
    """Reuses db_chat's provider chain (`_provider_chain`) instead of
    duplicating client-selection/fallback logic. `_get_client` does not
    exist in db_chat.py -- the client construction lives inline inside
    `_chat_completion_with_fallback`, so we replicate just that one line
    (`OpenAI(api_key=..., base_url=...)`) here, using the first provider
    in the chain (no fallback loop; a manual eval script doesn't need
    multi-provider retry)."""
    provider = db_chat._provider_chain()[0]
    client = OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])
    response = client.chat.completions.create(
        model=provider["model"],
        messages=[{"role": "system", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content or ""


def run() -> None:
    cases = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    clear_state(SESSION_ID)

    metric_correct = 0
    entity_correct = 0
    total = len(cases)

    for case in cases:
        result = extract_intent(case["question"], SESSION_ID, _llm_call)
        expected_metric = case.get("expected_metric")
        metric_ok = result.metric == expected_metric
        metric_correct += int(metric_ok)

        expected_entities = case.get("expected_entities")
        entity_ok = expected_entities is None or all(
            result.entities.get(k) == v for k, v in expected_entities.items()
        )
        entity_correct += int(entity_ok)

        status = "OK" if metric_ok and entity_ok else "MISS"
        print(f"[{status}] {case['question']}")
        print(f"    esperado: metric={expected_metric} entities={expected_entities}")
        print(f"    obtenido: metric={result.metric} entities={result.entities} confidence={result.confidence}")
        if case.get("notes"):
            print(f"    nota: {case['notes']}")

    print(f"\nMetric accuracy: {metric_correct}/{total}")
    print(f"Entity accuracy: {entity_correct}/{total}")


if __name__ == "__main__":
    run()
