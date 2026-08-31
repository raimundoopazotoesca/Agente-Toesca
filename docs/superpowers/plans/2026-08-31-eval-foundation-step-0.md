# Eval Foundation Step 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Check off each step only after its stated verification command succeeds.

**Goal:** Make the existing deterministic eval foundation load-bearing: baseline-aware automated checks, F5/liveness, reproducible Track B, Track A telemetry, and a committed LLM-judge policy.

**Architecture:** Preserve grading semantics and the existing adapters. A tiny pytest reporting plugin is authoritative for exact `report.nodeid` plus phase/outcome records; JUnit remains the human/GitHub artifact. CI compares the current result records to a shrinking active allowlist while retaining an immutable historical base artifact; the benchmark runner gains explicit adapter selection, declarative correction metadata, invoked liveness validation, structured reports, cleanliness evidence, and usage propagation.

**Tech Stack:** Python 3.11, pytest/JUnit XML, GitHub Actions, YAML/JSON, existing benchmark adapters.

**Spec:** `docs/toesca-analyst-eval-observability-blueprint-v1.md` (frozen), Section P Step 0 and Sections H/I/M.

## Global constraints

- **Reconciled baseline (supersedes the 21-failure figure below wherever they conflict):** at a clean checkout of `d986996baf2636ff7978314f424614c5f33afc75`, `pytest tests` alone (its own process) reproducibly produces `19 failed, 1341 passed, 9 skipped, 1 xfailed`. The 19 exact failing node IDs are enumerated in the reconciliation report; verify them again from a fresh run before freezing, do not retype from memory. An older external run reported `21 failed, 1342 passed, 6 skipped, 1 xfailed` on the identical commit; the delta is fully explained by 3 "archivo real no disponible" tests (apo3001/inmosa/sucden) that skip here for lack of local files and evidently ran in that other environment — this is environment-dependent, not code-dependent, and the 19/9/1 figures are what this repo's CI must freeze against.
- **Canonical PR structure is three separate pytest processes, never combined:** `pytest tests`, `pytest eval/benchmark/tests`, `pytest eval/product_alpha/tests`. Do not modify `pytest.ini` to co-collect them and do not add `__init__.py` package markers to make combined collection possible — co-collecting causes a duplicate-module `import file mismatch` (confirmed: `eval/benchmark/tests/test_graders.py` vs `eval/product_alpha/tests/test_graders.py`, no package markers in either directory). Every place below that references a single combined collection instead means "run these three processes independently."
- Keep `eval/baselines/pytest-d986996.json` immutable historical evidence for the `tests` suite only, pinned to `d986996baf2636ff7978314f424614c5f33afc75`, with the verified 19 exact failure IDs. It may also record the 9 skip IDs and reasons as historical context, but skip IDs are never part of the active failure allowlist.
- Initialize `eval/baselines/pytest-known-failures.json` (for `tests` only) from that verified historical result: exactly the 19 failing node IDs. It is the active allowlist and may only shrink in the same reviewed change that proves the affected test now passes.
- For every active-allowlist node ID, PASS requires removing it from the active allowlist; FAIL remains an allowed visible failure; SKIP, XFAIL, NOT-COLLECTED, setup/teardown ERROR, collection failure, and internal failure block. None of these states is "resolved."
- The PR blocker for `tests` is any new failing node ID, stale active-allowlist entry, missing/not-collected baseline ID, forbidden non-FAIL baseline state, collection/internal failure, or setup/teardown infrastructure error.
- `eval/benchmark/tests` and `eval/product_alpha/tests` carry no baseline/allowlist: both must be strictly green (zero failures) as a PR gate. The two frozen-hash benchmark failures were already reconciled and fixed on this branch (commit `d4095e7`, re-pinning `system_prompt_sha256` after the legitimate `a00d7ae` semantic-alias change) — do not reintroduce a known-failure baseline for them.
- The four migration-not-applied skips in `tests.db.test_invariantes` (085 x2, 087, 088) are recorded as known test-hermeticity debt only (DB fixture/migration state leaking into test skip conditions); do not fix them as part of Step 0.
- PR checks must make no system-under-test or judge calls.
- Deterministic-only benchmark execution omits judge calls but still can incur system-under-test LLM cost.
- Do not alter prompts, grader/rubric behavior, DB schema/data, holdout content, A2 runtime, trajectory dimensions, RESULT_VALIDATION, provenance rollout, or production feedback.
- A judge never re-scores or overrides a deterministic verdict.
- If any proposed change to this plan would require adding a new known failure to any of the three suites, stop and escalate rather than expanding an allowlist automatically.

## File map

| File | Change | Purpose |
|---|---|---|
| `.github/workflows/eval-foundation.yml` | Create | PR workflow: deterministic test execution, JUnit artifact, baseline-delta gate. |
| `tools/eval/pytest_nodeid_reporter.py` | Create | Pytest plugin writing exact `report.nodeid`, phase, and outcome JSON records. |
| `tools/eval/pytest_baseline_gate.py` | Create | Compare exact report records to historical evidence and active allowlist. |
| `eval/baselines/pytest-d986996.json` | Create from base-run evidence | Immutable base identity, summary, and 19 exact failure IDs for the `tests` suite alone. |
| `eval/baselines/pytest-known-failures.json` | Create from the same base-run evidence | Active, shrinking set of the 19 allowed failing IDs for the `tests` suite alone. |
| `tests/eval_foundation/test_pytest_baseline_gate.py` | Create | Plugin and verifier tests, including phases and forbidden state transitions. |
| `eval/benchmark/{runner.py,liveness.py}` | Modify/Create | F5 context, liveness, adapter choice, report output. |
| `eval/benchmark/adapters/provider_factory.py` | Create | Neutral provider/transport factory extracted from historical Round B ownership. |
| `eval/benchmark/{schema/case.schema.json,cases_loader.py,cases/tce/*.yaml}` | Modify | Narrow declarative correction metadata. |
| `eval/benchmark/tests/{test_runner.py,test_liveness.py,test_adapters.py}` | Create/Modify | F5, liveness, adapter factory, and telemetry tests. |
| `tools/db_chat.py` | Modify | Aggregate every observable existing LLM-call usage/timing and fallback provider/model. |
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
- [ ] At a clean checkout of `d986996`, run `python -X utf8 -m pytest tests --junitxml=artifacts/pytest-d986996.xml` (the `tests` suite only, its own process); generate the manifest only from that artifact; verify the recorded summary and exactly 19 IDs. Do not synthesize IDs from counts.
- [ ] Do not change `pytest.ini`'s collection scope and do not add `__init__.py` package markers to `eval/benchmark/tests` or `eval/product_alpha/tests` — the three suites stay three separate pytest processes (see Global constraints). Create the workflow with three separate steps: `pytest tests --junitxml=... --nodeid-report=...` gated by the baseline/allowlist verifier; `pytest eval/benchmark/tests` and `pytest eval/product_alpha/tests` each required to exit 0 with no baseline file. Upload the `tests` XML/JSON even on failure, then run the verifier so only a new ID in `tests` fails the PR.
- [ ] Verify with `python -X utf8 -m pytest --collect-only -q` and the focused verifier tests; inject a fixture with a new node ID and confirm it blocks.
- [ ] Commit: `git commit -m "test: gate deterministic checks against baseline deltas"`.

### Task 1 execution amendments

These amendments supersede Task 1's JUnit-only interface and baseline semantics.

**Authoritative interface:** pytest plugin option `--nodeid-report <path>` writes JSON records from exact `report.nodeid`, with `phase` (`setup|call|teardown`), `outcome`, and `wasxfail`, plus the full collected-node-ID list and collection/internal errors. `evaluate_run(records, historical, active_allowlist, collected_ids) -> BaselineGateResult` is authoritative; JUnit remains the human/GitHub artifact only.

- [ ] Add fixtures covering parametrized and class-method node IDs, setup/teardown errors, skip, xfail, collection failure, and internal failure. Prove plugin round-trip identity for every fixture before using it for gating.
- [ ] Keep `eval/baselines/pytest-d986996.json` immutable historical evidence for the `tests` suite alone (its own process, never combined with the other two — see Global constraints). Establish it from a clean `d986996` run: `--junitxml=artifacts/pytest-d986996.xml` and `--nodeid-report=artifacts/pytest-d986996-nodeids.json`. Verify rather than assume; the reconciled figure for `tests` alone is `19 failed, 1341 passed, 9 skipped, 1 xfailed`, not the older external `21 failed, 1342 passed, 6 skipped, 1 xfailed` (see Global constraints for why). The artifact may also record the 9 skip node IDs and reasons as historical context.
- [ ] Create `eval/baselines/pytest-known-failures.json` from only the verified base IDs in allowed `call/failed` state — exactly the 19 IDs. Never add newly discovered failures silently. Skip/xfail IDs are never added to this allowlist. The active allowlist may only shrink when the same reviewed change proves the ID now passes.
- [ ] Gate each active ID as follows: `call/failed` is visible but allowed; PASS is a stale allowlist entry and blocks until removed; SKIP, XFAIL, NOT-COLLECTED, setup/teardown ERROR, collection failure, and internal failure block and are never called resolved. New `call/failed` IDs block.
- [ ] In GitHub Actions, permit pytest exit `1` solely to upload JUnit/node-ID artifacts and run the gate. Exit codes `2–5`, collection/internal failure, and setup/teardown infrastructure error hard-fail independently of the active allowlist.
- [ ] Add fixture assertions for every classification above, including “allowed failure passes but allowlist unchanged” and “allowed failure regresses to xfail/skip/error/not-collected.”

## Task 2: Wire F5 and make routing liveness testable

**Interfaces:** an optional per-turn `correction_context: {previous_entities: {...}, corrected_entities: {...}}`; `correction_context_for_turn(case, index) -> tuple[dict, dict] | None`; `assert_liveness(reports) -> None`.

- [ ] Write fake-adapter tests that capture the `score_turn` argument and require turn 2 of `tce-entitycorrection-001` to receive `({"fondo": "PT"}, {"fondo": "Apo"})`; make a report with F5 `None` fail liveness.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_runner.py eval/benchmark/tests/test_liveness.py -q`; current `correction_ctx = None` must fail.
- [ ] Extend the case schema only with the declared metadata shape. In `cases_loader.py`, reject it on turn zero, reject empty mappings, and require `corrected_entities == expected_entities`. Add it only to the corrected turns in `tce-entitycorrection-001.yaml` and `tce-entityswap-001.yaml`.
- [ ] Replace the runner hard-code with the declared context. Include all named gate checks in turn reports. Liveness must assert a deterministic dimension is either scored or explicitly unscored, each deterministic gate has a boolean verdict when applicable, and correction cases have a boolean F5 verdict. Judge-owned `None` remains pending, not pass.
- [ ] Verify: `python -X utf8 -m pytest eval/benchmark/tests/test_cases_loader.py eval/benchmark/tests/test_graders.py eval/benchmark/tests/test_runner.py eval/benchmark/tests/test_liveness.py eval/benchmark/tests/test_holdout_not_leaked.py -q`.
- [ ] Commit: `git commit -m "test: wire benchmark correction gate and liveness checks"`.

### Task 2 execution amendments

- [ ] Invoke `assert_liveness()` in the real `runner.py` benchmark path after all turn reports are assembled and before reporting success/output completion; unit coverage alone is insufficient.
- [ ] Make applicability metadata-driven. A judge-owned `None` remains pending; do not require irrelevant gates to become boolean. Require F5 to be boolean only on turns declaring `correction_context`; fail liveness if any such turn lacks an F5 verdict.

## Task 3: Expose reproducible Track B benchmark execution

**Interfaces:** `--track {track_a_structured,track_b_frontier,track_b_openai_responses,track_b_anthropic}`, `--provider`, `--model`, `--split`, `--case`, and `--output`; output record has Git SHA, snapshot hash, requested/resolved track/provider/model, turn, answer, observed SQL, `Usage`, deterministic results, and gate results.

- [ ] Write tests that `build_adapter("track_b_frontier", sandbox, provider=config)` selects Track B and that a Track B choice without explicit provider/model errors; retain Track A as the default only when explicitly selected/defaulted.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_runner.py -q`; confirm current Track-A-only runner fails.
- [ ] Implement one adapter factory in `runner.py`, reusing `eval.round_b.runner.live_adapter_factory` provider mapping rather than duplicating transport/credential behavior. Never silently fall back between Track B providers or to Track A. Write JSONL using the exact requested command/model and `snapshot.lock` identity.
- [ ] Support this manual/system-under-test command without enabling judge calls: `python -X utf8 -m eval.benchmark.runner --track track_b_frontier --provider <provider> --model <model> --split dev --output artifacts/benchmark-track-b.jsonl`.
- [ ] Verify no-network checks: `python -X utf8 -m pytest eval/benchmark/tests/test_adapters.py eval/benchmark/tests/test_track_b.py eval/benchmark/tests/test_track_b_native_providers.py eval/benchmark/tests/test_runner.py -q`; then `python -X utf8 -m eval.benchmark.runner --help`.
- [ ] Commit: `git commit -m "feat: expose reproducible Track B benchmark runs"`.

### Task 3 execution amendments

- [ ] Before implementation, inspect `eval.round_b.runner.live_adapter_factory` ownership. It is currently an ad-hoc historical Round B helper, so do not import it from the stable runner. Extract its minimal provider-name, credential-environment, base-URL, and transport selection logic into neutral `eval/benchmark/adapters/provider_factory.py`, covered by direct unit tests.
- [ ] Native tracks derive and validate their provider: `track_b_openai_responses` derives `openai`; `track_b_anthropic` derives `anthropic`. They require a model but do not redundantly require `--provider`. `track_b_frontier` requires explicit `--provider` plus `--model` because it supports multiple OpenAI-compatible transports. All invalid combinations fail before execution; none silently falls back.
- [ ] Record `git rev-parse HEAD`, `git status --porcelain`, and a boolean `worktree_clean` in every benchmark output. A Track A/B architecture-comparison run is comparable only when `worktree_clean=true`; otherwise write `comparison_eligible=false` and a dirty-path list.

## Task 4: Populate Track A token and latency instrumentation

**Interfaces:** `db_chat.answer()` adds `usage: {calls, input_tokens, output_tokens, reasoning_tokens, cached_tokens, llm_latency_ms}`; `TrackAStructured.ask()` maps it into `Usage` while preserving its independent wall-clock `latency_ms`.

- [ ] Write a mocked `db_chat.answer()` adapter test returning two calls and concrete token values; assert `Turn.usage` preserves them and still records wall-clock latency.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests/test_adapters.py -q`; confirm token values are currently `None`.
- [ ] Add a provider-neutral response-usage extractor in `tools/db_chat.py`; aggregate only the SQL-generation/synthesis calls already made, including existing fallback attempts. Time those calls. Do not alter prompts, temperatures, max tokens, fallback order, or SQL behavior. Shortcut/clarify/error paths expose honest zero/unknown values, never invented tokens.
- [ ] Map those fields in `track_a_structured.py`.
- [ ] Verify: `python -X utf8 -m pytest eval/benchmark/tests/test_adapters.py eval/benchmark/tests/test_actions.py tests/analyst_runtime -q`.
- [ ] Commit: `git commit -m "feat: record Track A benchmark usage telemetry"`.

### Task 4 execution amendments

- [ ] Instrument every observable LLM call made by `db_chat.answer()`: intent/context or planning calls, SQL generation, synthesis, and every fallback/retry attempt where observable. Aggregate calls and timing, preserve `null` for unavailable token fields, and record per-attempt actual provider/model when observable. Never fabricate `0` tokens.
- [ ] Extend mocked tests to cover a planning/intent call, SQL call, synthesis call, fallback to a second provider, and a provider response without usage metadata.

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

- [ ] Run the three suites as three separate processes (never combined — see Global constraints): `python -X utf8 -m pytest tests --junitxml=artifacts/pytest-step0-tests.xml --nodeid-report=artifacts/pytest-step0-tests-nodeids.json`, then `python -X utf8 -m tools.eval.pytest_baseline_gate --nodeid-report artifacts/pytest-step0-tests-nodeids.json --baseline eval/baselines/pytest-d986996.json --known-failures eval/baselines/pytest-known-failures.json`. Retained baseline failures must be visible; any new node ID must fail the gate.
- [ ] Run `python -X utf8 -m pytest eval/benchmark/tests -q` and `python -X utf8 -m pytest eval/product_alpha/tests -q` as their own separate processes; both must be 100% green with zero known failures.
- [ ] Run `python -X utf8 -m pytest tests --collect-only -q`, `python -X utf8 -m pytest eval/benchmark/tests --collect-only -q`, and `python -X utf8 -m pytest eval/product_alpha/tests --collect-only -q` (each its own process; do not attempt a combined `--collect-only`, which reproduces the `test_graders.py` import-file-mismatch documented in Global constraints).
- [ ] Scope-review `git diff --name-only d986996...HEAD`: no prompts, rubric/grader redesign, DB migrations/data, A2 runtime work, RESULT_VALIDATION, production feedback, structured provenance implementation, or new trajectory dimensions.

### Final verification execution amendments

- [ ] Run the `tests` suite through the exact-node-ID plugin and retain both JSON and JUnit artifacts. The gate must show: new failures, allowed visible failures, stale active-allowlist PASS IDs, prohibited baseline states, not-collected IDs, and infrastructure/collection failures as separate categories.
- [ ] Verify the historical artifact remains byte-for-byte unchanged after initialization. Verify the active allowlist is a subset of its allowed historical failure IDs and any removed ID has a same-change passing-test proof.
- [ ] Verify real runner invocation executes liveness and fails a synthetic declared-correction report with missing/`None` F5, while judge-owned pending gates remain valid when metadata says they are judge-owned.
- [ ] Verify native Track B argument matrices and benchmark output cleanliness fields without provider calls; mark a deliberately dirty run `comparison_eligible=false`.
- [ ] Verify Track A telemetry reports all observable calls and preserves `null` where provider token usage is absent.
- [ ] Step 0 is not load-bearing until the workflow status check is configured as required by the repository’s GitHub branch protection/ruleset. If repository credentials/API permissions cannot configure that rule automatically, perform this exact manual post-merge step: GitHub repository → **Settings** → **Rules** → applicable branch ruleset (or **Branches** → branch protection rule) → enable **Require status checks to pass before merging** → select the `Eval Foundation` workflow job/check → save. Until verified on a pull request, report **“CI implemented but not required.”**

Explicit non-goals: no judge run in PR CI; no holdout run on PR; no change to the 19 `tests` baseline failures except real, separately reviewed fixes; no fix for the 4 migration-dependent skips (recorded as test-hermeticity debt only); no Track B architecture decision; and no Step 1+ work from the blueprint.
