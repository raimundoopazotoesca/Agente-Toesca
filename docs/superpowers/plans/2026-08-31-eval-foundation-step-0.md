# Eval Foundation Step 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Check off each step only after its stated verification command succeeds.

**Goal:** Make the existing deterministic eval foundation load-bearing: baseline-aware automated checks, F5/liveness, reproducible Track B, Track A telemetry, and a committed LLM-judge policy.

**Architecture:** Preserve grading semantics and the existing adapters. A JUnit-XML baseline verifier compares exact pytest node-ID sets; CI runs the normal suite plus the excluded eval test directories. The benchmark runner gains explicit adapter selection, declarative correction metadata, structured reports, and usage propagation.

**Tech Stack:** Python 3.11, pytest/JUnit XML, GitHub Actions, YAML/JSON, existing benchmark adapters.

**Spec:** `docs/toesca-analyst-eval-observability-blueprint-v1.md` (frozen), Section P Step 0 and Sections H/I/M.

## Global constraints

- Persist the exact failure-ID set from base `d986996baf2636ff7978314f424614c5f33afc75`; the external summary is `21 failed, 1342 passed, 6 skipped, 1 xfailed, 957.59s`.
- The PR blocker is only `current_failure_ids - baseline_failure_ids`; baseline failures remain visibly failed and may not be xfailed, skipped, removed, or treated as green.
- PR checks must make no system-under-test or judge calls.
- Deterministic-only benchmark execution omits judge calls but still can incur system-under-test LLM cost.
- Do not alter prompts, grader/rubric behavior, DB schema/data, holdout content, A2 runtime, trajectory dimensions, RESULT_VALIDATION, provenance rollout, or production feedback.
- A judge never re-scores or overrides a deterministic verdict.

## File map

| File | Change | Purpose |
|---|---|---|
| `.github/workflows/eval-foundation.yml` | Create | PR workflow: deterministic test execution, JUnit artifact, baseline-delta gate. |
| `tools/eval/pytest_baseline_gate.py` | Create | Parse JUnit XML and calculate exact node-ID deltas. |
| `eval/baselines/pytest-d986996.json` | Create from base-run evidence | Immutable base identity, summary, command, and 21 exact failure IDs. |
| `tests/eval_foundation/test_pytest_baseline_gate.py` | Create | Verifier unit tests. |
| `pytest.ini` | Modify | Collect `tests`, `eval/benchmark/tests`, and `eval/product_alpha/tests`. |
| `eval/benchmark/{runner.py,liveness.py}` | Modify/Create | F5 context, liveness, adapter choice, report output. |
| `eval/benchmark/{schema/case.schema.json,cases_loader.py,cases/tce/*.yaml}` | Modify | Narrow declarative correction metadata. |
| `eval/benchmark/tests/{test_runner.py,test_liveness.py,test_adapters.py}` | Create/Modify | F5, liveness, adapter factory, and telemetry tests. |
| `tools/db_chat.py` | Modify | Aggregate only existing provider-call usage/timings. |
| `eval/benchmark/adapters/track_a_structured.py` | Modify | Map returned telemetry to `Usage`. |
| `docs/toesca-analyst-llm-judge-policy-v1.md` | Create | Normative policy matching `judge.py`. |
| `eval/benchmark/tests/test_judge_policy_document.py` | Create | Policy/source consistency test. |

## Task 1: Establish baseline-aware automated deterministic checks

**Interfaces:** `compare_junit_to_baseline(junit_path, baseline_path) -> BaselineDelta`; CLI `python -m tools.eval.pytest_baseline_gate --junitxml <path> --baseline <path>` exits nonzero only if new IDs exist.

- [ ] Write failing tests for strict set semantics.

```python
def test_new_id_blocks_even_if_failure_count_drops(tmp_path):
    result = compare({"old_a", "new_c"}, {"old_a", "old_b"})
    assert result.new_failure_ids == {"new_c"}
    assert result.exit_code == 1

def test_resolved_baseline_is_visible_but_not_a_failure(tmp_path):
    result = compare(set(), {"old_a"})
    assert result.resolved_baseline_ids == {"old_a"}
    assert result.exit_code == 0
```

- [ ] Run `python -X utf8 -m pytest tests/eval_foundation/test_pytest_baseline_gate.py -q`; confirm it fails before the verifier exists.
- [ ] Implement strict manifest/JUnit parsing. Manifest fields are `base_commit`, `command`, `summary`, and sorted `failure_ids`; reject duplicate/non-string IDs, empty IDs, and a base other than `d986996…`. Report sorted new, retained-baseline, and resolved-baseline IDs.
- [ ] At a clean checkout of `d986996`, run `python -X utf8 -m pytest --junitxml=artifacts/pytest-d986996.xml`; generate the manifest only from that artifact; verify the recorded summary and exactly 21 IDs. Do not synthesize IDs from counts.
- [ ] Change `pytest.ini` to `testpaths = tests eval/benchmark/tests eval/product_alpha/tests`. Create the workflow to run pytest with JUnit output, upload that XML even on test failure, then run the verifier so only a new ID fails the PR.
- [ ] Verify with `python -X utf8 -m pytest --collect-only -q` and the focused verifier tests; inject a fixture with a new node ID and confirm it blocks.
- [ ] Commit: `git commit -m "test: gate deterministic checks against baseline deltas"`.

## Task 2: Wire F5 and make routing liveness testable

**Interfaces:** an optional per-turn `correction_context: {previous_entities: {...}, corrected_entities: {...}}`; `correction_context_for_turn(case, index) -> tuple[dict, dict] | None`; `assert_liveness(reports) -> None`.

- [ ] Write fake-adapter tests that capture the `score_turn` argument and require turn 2 of `tce-entitycorrection-001` to receive `({"fondo": "PT"}, {"fondo": "Apo"})`; make a report with F5 `None` fail liveness.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_runner.py eval/benchmark/tests/test_liveness.py -q`; current `correction_ctx = None` must fail.
- [ ] Extend the case schema only with the declared metadata shape. In `cases_loader.py`, reject it on turn zero, reject empty mappings, and require `corrected_entities == expected_entities`. Add it only to the corrected turns in `tce-entitycorrection-001.yaml` and `tce-entityswap-001.yaml`.
- [ ] Replace the runner hard-code with the declared context. Include all named gate checks in turn reports. Liveness must assert a deterministic dimension is either scored or explicitly unscored, each deterministic gate has a boolean verdict when applicable, and correction cases have a boolean F5 verdict. Judge-owned `None` remains pending, not pass.
- [ ] Verify: `python -X utf8 -m pytest eval/benchmark/tests/test_cases_loader.py eval/benchmark/tests/test_graders.py eval/benchmark/tests/test_runner.py eval/benchmark/tests/test_liveness.py eval/benchmark/tests/test_holdout_not_leaked.py -q`.
- [ ] Commit: `git commit -m "test: wire benchmark correction gate and liveness checks"`.

## Task 3: Expose reproducible Track B benchmark execution

**Interfaces:** `--track {track_a_structured,track_b_frontier,track_b_openai_responses,track_b_anthropic}`, `--provider`, `--model`, `--split`, `--case`, and `--output`; output record has Git SHA, snapshot hash, requested/resolved track/provider/model, turn, answer, observed SQL, `Usage`, deterministic results, and gate results.

- [ ] Write tests that `build_adapter("track_b_frontier", sandbox, provider=config)` selects Track B and that a Track B choice without explicit provider/model errors; retain Track A as the default only when explicitly selected/defaulted.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_runner.py -q`; confirm current Track-A-only runner fails.
- [ ] Implement one adapter factory in `runner.py`, reusing `eval.round_b.runner.live_adapter_factory` provider mapping rather than duplicating transport/credential behavior. Never silently fall back between Track B providers or to Track A. Write JSONL using the exact requested command/model and `snapshot.lock` identity.
- [ ] Support this manual/system-under-test command without enabling judge calls: `python -X utf8 -m eval.benchmark.runner --track track_b_frontier --provider <provider> --model <model> --split dev --output artifacts/benchmark-track-b.jsonl`.
- [ ] Verify no-network checks: `python -X utf8 -m pytest eval/benchmark/tests/test_adapters.py eval/benchmark/tests/test_track_b.py eval/benchmark/tests/test_track_b_native_providers.py eval/benchmark/tests/test_runner.py -q`; then `python -X utf8 -m eval.benchmark.runner --help`.
- [ ] Commit: `git commit -m "feat: expose reproducible Track B benchmark runs"`.

## Task 4: Populate Track A token and latency instrumentation

**Interfaces:** `db_chat.answer()` adds `usage: {calls, input_tokens, output_tokens, reasoning_tokens, cached_tokens, llm_latency_ms}`; `TrackAStructured.ask()` maps it into `Usage` while preserving its independent wall-clock `latency_ms`.

- [ ] Write a mocked `db_chat.answer()` adapter test returning two calls and concrete token values; assert `Turn.usage` preserves them and still records wall-clock latency.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_adapters.py -q`; confirm token values are currently `None`.
- [ ] Add a provider-neutral response-usage extractor in `tools/db_chat.py`; aggregate only the SQL-generation/synthesis calls already made, including existing fallback attempts. Time those calls. Do not alter prompts, temperatures, max tokens, fallback order, or SQL behavior. Shortcut/clarify/error paths expose honest zero/unknown values, never invented tokens.
- [ ] Map those fields in `track_a_structured.py`.
- [ ] Verify: `python -X utf8 -m pytest eval/benchmark/tests/test_adapters.py eval/benchmark/tests/test_actions.py tests/analyst_runtime -q`.
- [ ] Commit: `git commit -m "feat: record Track A benchmark usage telemetry"`.

## Task 5: Commit and protect the LLM-judge policy

**Interfaces:** `docs/toesca-analyst-llm-judge-policy-v1.md` names every member of `judge.DIMENSION_NAMES` and `judge.GATE_NAMES`; a policy test imports source and checks that text.

- [ ] Write the failing policy-document test:

```python
for name in judge.DIMENSION_NAMES + judge.GATE_NAMES:
    assert f"`{name}`" in policy
assert "must never re-score or override a deterministic verdict" in policy
```

- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_judge_policy_document.py -q`; confirm missing policy fails.
- [ ] Author the policy, with no judge-code change: six always-judge dimensions plus conditional `tool_correctness`; three judge gates; deterministic authority; no silent fallback; model/rubric/implementation version recording; calibration for judge/rubric changes; repeated-run variance before release gating; disagreement triage.
- [ ] Verify: `python -X utf8 -m pytest eval/benchmark/tests/test_judge.py eval/benchmark/tests/test_judge_policy_document.py -q`.
- [ ] Commit: `git commit -m "docs: commit LLM judge policy v1"`.

## Final verification and non-goals

- [ ] Run `python -X utf8 -m pytest --junitxml=artifacts/pytest-step0.xml`, then `python -X utf8 -m tools.eval.pytest_baseline_gate --junitxml artifacts/pytest-step0.xml --baseline eval/baselines/pytest-d986996.json`. Retained baseline failures must be visible; any new node ID must fail the gate.
- [ ] Run `python -X utf8 -m pytest --collect-only -q` and `python -X utf8 -m pytest eval/benchmark/tests eval/product_alpha/tests tests/eval_foundation -q`.
- [ ] Scope-review `git diff --name-only d986996...HEAD`: no prompts, rubric/grader redesign, DB migrations/data, A2 runtime work, RESULT_VALIDATION, production feedback, structured provenance implementation, or new trajectory dimensions.

Explicit non-goals: no judge run in PR CI; no holdout run on PR; no change to the 21 failures except real, separately reviewed fixes; no Track B architecture decision; and no Step 1+ work from the blueprint.
