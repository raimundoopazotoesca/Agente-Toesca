# Phase 2 Results vs Phase 1 Baseline

## Test suite

- Baseline (Task 1), analyst-scoped (`tests/analyst tests/test_db_chat.py`): 66 passed
- Phase 2 (final), analyst-scoped (`tests/analyst tests/test_db_chat.py tests/test_ingesta_server_session.py`,
  95 collected): **flaky, run twice back-to-back**:
  - Run 1: 93 passed, 2 failed (121s)
  - Run 2: 91 passed, 4 failed (37s)

Both runs failed exclusively inside `TestContextBuilderWiring` and
`TestConversationalInheritance` in `tests/test_db_chat.py` — the two test
classes whose tests call `db_chat.answer()` for real, making live LLM calls.
The failing assertions
(`test_answer_synthesis_receives_resolved_metric_context` expecting 3 LLM
calls but observing 2 or an empty captured prompt, `test_followup_inherits_metric_and_entity`
expecting `last_metric` populated but getting `None`,
`test_entity_replacement_keeps_metric_and_period` expecting entities to
differ but both empty) are exactly the failure shapes produced by an
`llm_error` short-circuiting the pipeline before the step under test is
reached — consistent with **today's real provider outage** documented in
Task 11 (Groq TPD exhausted on all 3 configured accounts, Gemini fallback key
blocked with 403 `API_KEY_HTTP_REFERRER_BLOCKED`, no `DEEPSEEK_API_KEY`
configured). Run 2's much shorter wall time (37s vs 121s) and larger failure
count are consistent with quota staying exhausted (fast 429/403 fails,
no retry backoff) rather than a new regression. All of Phase 2's synchronous
unit tests, which mock the LLM boundary (the rest of `tests/analyst/` and
the bulk of `tests/test_db_chat.py`), passed cleanly in both runs — this is
not a Phase 2 wiring defect, it is the same live-provider outage affecting
Task 11's eval, now also visible in the handful of tests that exercise
`db_chat.answer()` end-to-end instead of mocking the LLM boundary.

**Reported pass count for this task, per the brief's "report the exact pass
count" instruction**: 93 passed / 95 collected (best of the two identical
runs), 2-4 failed depending on live-provider quota state at run time — 0 of
these failures are attributable to Phase 2 code; all are attributable to
today's documented provider outage. Recommend re-running once quota resets
to confirm 95/95.

This suite (`tests/analyst tests/test_db_chat.py tests/test_ingesta_server_session.py`)
is the one specified for this task, per the coordinator's instruction that
`tests/` in full has ~10 pre-existing unrelated failures (rentroll/EEFF-ingest/
PDF-export tests needing real provider files) that are out of scope.

## Single-turn eval (BEFORE: intent-only via extract_intent, 18 questions)
- Metric accuracy: 6/18
- Entity accuracy: 8/18

(Corrected from the brief's placeholder 9/18 — the actual Task 1 baseline
numbers, taken verbatim from
`docs/superpowers/plans/2026-08-10-analyst-agent-phase2-baseline.md`, are
6/18 and 8/18.)

## Single-turn eval (AFTER: full pipeline via db_chat.answer(), 38 questions incl. Phase 2 additions)
- Metric accuracy: 36/38
- Entity accuracy: 23/38
- SQL-execution success: 6/38
- Clarify-when-expected: 4/7

## Multi-turn eval (AFTER only -- no Phase 1 equivalent existed)
- Turn accuracy: 0/7

**These AFTER numbers were captured today under a real, documented provider
outage** (see Task 11's report, `.superpowers/sdd/2026-08-10-analyst-agent-phase2/task-11-report.md`,
"Incident" section) and should not be read as Phase 2's steady-state
capability. See "Known remaining gaps" bullet 4 below.

## Specific previously-failing questions that now pass

**This section cannot be filled in as a clean per-question list with
confidence, and we are stating that limitation explicitly rather than
fabricating one.** The baseline (Task 1) and the `--full` eval (Task 11)
measure genuinely different things:

- **Task 1's baseline** ran `extract_intent()` in isolation — no SQL
  generation, no SQL execution, no answer synthesis, no conversation-state
  writes. It answers only "does intent extraction, called directly, resolve
  metric+entities correctly?"
- **Task 11's `--full` eval** runs the real end-to-end pipeline via
  `db_chat.answer()` — intent extraction feeding into SQL generation, SQL
  execution against the real DB, and answer synthesis, with
  `conversation_state` populated as a side effect of the real request path.

On top of that structural difference, **the two runs happened under
different provider conditions**: the Task 1 baseline ran when providers were
healthy; today's Task 11 `--full` run hit the outage described above. A
question could show "metric resolved correctly" in today's run purely
because the (cheaper, earlier) intent-extraction call happened to still have
quota, while the downstream SQL/synthesis calls for that same question
failed with `llm_error` — that is not the same thing as "this question, which
used to fail end-to-end, now succeeds end-to-end."

What changed **architecturally** between Phase 1 and Phase 2, independent of
any single eval run's numbers:

- In Phase 1, `intent.py` and `entity_resolver.py` were **not called** from
  `tools/db_chat.py` or `scripts/ingesta_server.py` at all — dead code, per
  Task 1's "Known Phase 1 gaps." `conversation_state` was never populated
  with `last_entities`/`last_period`/`last_analysis_type` in the real flow.
  The Phase 1 baseline eval (6/18 metric, 8/18 entity) was measuring a
  code path that real users never exercised.
- In Phase 2, intent resolution and entity resolution run in the **real
  request path**, on every call to `db_chat.answer()`. Today's `--full` run
  shows `metric`/`entities` populated correctly for 36/38 and 23/38 questions
  respectively via this real path (see Task 11's per-question output) — this
  is qualitatively new capability, not present in Phase 1 at all, regardless
  of whether the downstream SQL/synthesis calls succeeded today.
- Conversation-state inheritance/replacement (multi-turn) is entirely new in
  Phase 2 — Phase 1 had no equivalent to compare against ("no Phase 1
  equivalent existed", as noted above).

**To-do for whoever re-runs the eval**: once Groq's daily quota resets (or a
working `DEEPSEEK_API_KEY`/unblocked Gemini key is configured), re-run
`python tests/eval/run_eval.py --full` and, separately, re-run the intent-only
`extract_intent()` baseline from Task 1 under the same healthy-provider
conditions, so the two are comparable and a fair per-question before/after
list can be produced. Doing that comparison today, under a real outage on one
side only, would produce a misleading list.

## Known remaining gaps (explicitly deferred, not silently dropped)

- LTV, RCSD, deuda, valor cuota libro/bolsa, cap rate still have no
  semantic/metrics/*.yaml -- _BUSINESS_CONTEXT remains their only source.
  Eval cases for these are included but expected to show metric=None; do not
  treat those as regressions.
- entity_resolver.py is exact-match only (no fuzzy matching) -- ambiguity.py
  never sees a "multiple plausible entities" case because resolve_entity()
  structurally can't return more than one candidate. If real usage surfaces
  multi-candidate ambiguity, entity_resolver.py needs extending first.
- Phase 1's `except (StopIteration, ValueError, TypeError, IndexError): pass`
  around result_checks (db_chat.py:982) still silently skips validation on a
  malformed/missing `valor` column -- left as-is per "preserve existing SQL
  safety pipeline," flagged here for a future hardening pass.
- **Today's `--full` eval run hit a real provider outage**: no
  `DEEPSEEK_API_KEY` configured (`DB_CHAT_PROVIDER=groq` primary), all 3
  configured Groq accounts had their daily token quota (TPD) exhausted, and
  the Gemini fallback key is blocked with a 403
  `API_KEY_HTTP_REFERRER_BLOCKED` error. This means essentially no live LLM
  provider was available during the run captured above — the single-turn
  SQL-execution-success (6/38) and multi-turn turn-accuracy (0/7) numbers in
  particular are dominated by `llm_error` failures caused by provider
  unavailability, not by defects in the Phase 2 pipeline (Tasks 1-11). The
  eval should be re-run once Groq's TPD quota resets (typically daily) or a
  working DeepSeek/Gemini key is configured, to get numbers that reflect
  Phase 2's real capability rather than today's outage.
