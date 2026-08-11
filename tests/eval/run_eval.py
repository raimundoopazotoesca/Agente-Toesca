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


def _clear_all_state(session_ids: list[str]) -> None:
    from tools.analyst.conversation_state import clear_state as _clear_state
    for sid in session_ids:
        _clear_state(sid)


def run_full() -> None:
    """End-to-end eval: runs db_chat.answer() for real (2 LLM calls + real
    SQL execution per question), not just extract_intent(). Reports metric
    accuracy, entity accuracy, SQL-execution success, and clarify-policy
    correctness for single-turn questions.yaml, plus inheritance/replacement
    correctness for conversations.yaml."""
    from tools.analyst.conversation_state import get_state

    # db_chat constructs a fresh OpenAI client per call with the SDK default
    # (max_retries=2, honoring Retry-After). When a provider's daily quota is
    # exhausted, that means multi-minute backoff sleeps per attempt, per
    # provider in the fallback chain -- observed to blow up a 45-question eval
    # run past 70 minutes with zero progress visible. For eval runs only,
    # disable client-side retries so an exhausted/broken provider fails fast
    # (~seconds) and falls through to the next one immediately. db_chat.py
    # itself is untouched -- this only affects this eval script's process.
    from openai import OpenAI as _OpenAI
    db_chat.OpenAI = lambda **kw: _OpenAI(max_retries=0, **kw)

    questions_path = Path(__file__).parent / "questions.yaml"
    with open(questions_path, encoding="utf-8") as fh:
        cases = yaml.safe_load(fh)

    metric_ok = entity_ok = sql_ok = 0
    clarify_expected_ok = 0
    clarify_cases = 0
    n = len(cases)

    for i, case in enumerate(cases):
        session_id = f"eval-single-{i}"
        _clear_all_state([session_id])
        result = db_chat.answer(case["question"], [], session_id=session_id)

        expects_clarify = case.get("expected_metric") is None and not case.get("expected_entities")
        if expects_clarify and "no debe" not in (case.get("notes") or "").lower():
            clarify_cases += 1
            if result.get("clarify"):
                clarify_expected_ok += 1

        if not result.get("error") and (result.get("sql") is not None or result.get("clarify")):
            sql_ok += 1

        state = get_state(session_id)
        expected_metric = case.get("expected_metric")
        if expected_metric is None or state["last_metric"] == expected_metric:
            metric_ok += 1
        expected_entities = case.get("expected_entities") or {}
        if not expected_entities or all(
            state["last_entities"].get(k) == v for k, v in expected_entities.items()
        ):
            entity_ok += 1

        print(f"[{i+1}/{n}] {case['question'][:60]!r} -> metric={state['last_metric']} entities={state['last_entities']} clarify={result.get('clarify')}")

    print(f"\nSingle-turn (full pipeline, {n} questions):")
    print(f"  Metric accuracy: {metric_ok}/{n}")
    print(f"  Entity accuracy: {entity_ok}/{n}")
    print(f"  SQL-execution success (no error): {sql_ok}/{n}")
    print(f"  Clarify-when-expected: {clarify_expected_ok}/{clarify_cases}")

    conversations_path = Path(__file__).parent / "conversations.yaml"
    with open(conversations_path, encoding="utf-8") as fh:
        conversations = yaml.safe_load(fh)

    conv_turn_total = 0
    conv_turn_ok = 0
    for conv in conversations:
        session_id = f"eval-conv-{conv['name']}"
        _clear_all_state([session_id])
        history: list[dict] = []
        for turn in conv["turns"]:
            result = db_chat.answer(turn["question"], history, session_id=session_id)
            history.append({"role": "user", "content": turn["question"]})
            history.append({"role": "assistant", "content": result.get("answer_md", "")})

            state = get_state(session_id)
            conv_turn_total += 1
            expected_metric = turn.get("expected_metric")
            expected_entities = turn.get("expected_entities") or {}
            metric_match = expected_metric is None or state["last_metric"] == expected_metric
            entity_match = not expected_entities or all(
                state["last_entities"].get(k) == v for k, v in expected_entities.items()
            )
            if metric_match and entity_match:
                conv_turn_ok += 1
            print(f"  [{conv['name']}] {turn['question'][:60]!r} -> metric={state['last_metric']} entities={state['last_entities']}")

    print(f"\nMulti-turn (full pipeline, {len(conversations)} conversations, {conv_turn_total} turns):")
    print(f"  Turn accuracy: {conv_turn_ok}/{conv_turn_total}")


if __name__ == "__main__":
    if "--full" in sys.argv:
        run_full()
    else:
        run()
