# Toesca Analyst — Eval & Observability Blueprint v1

Scope: audit + design only. No runtime, prompt, grader, or DB changes made as part of this document. Base commit `d986996`, worktree `audit/analyst-eval-blueprint-v1`. Does not touch or block JLL v2 Production Readiness or A1.5 Data Foundation Target Contract, which are in-flight in parallel worktrees.

---

## A. Executive verdict

Toesca already has more real eval infrastructure than most agent projects at this stage: a genuinely double-guarded read-only sandbox shared between benchmark and production, a hash-pinned snapshot, a 10-dimension hybrid deterministic+judge rubric with documented calibration rounds, a physically-isolated holdout repo with an anti-leak test suite, and evidence of multiple real runs against real models with human-vs-judge comparison reports. This is not vaporware — it is unusually disciplined for a project this size.

But almost none of it is *load-bearing* today, for three structural reasons:

1. **Nothing runs automatically.** There is no CI. `eval/benchmark/tests/` and `eval/product_alpha/tests/` sit outside `pytest.ini`'s `testpaths` and require a human to remember the exact invocation. A regression in a gate, the judge, or the sandbox authorizer can land and stay silent indefinitely.
2. **The benchmark measures the wrong architecture almost by default.** The only wired entrypoint (`runner.py`) drives Track A (the current structured intent-extraction production path), which the benchmark's own `FINDINGS.md` documents as returning generic non-answers on 8/8 harder pilot cases. Track B adapters (a plausible A2 direction) exist and are transport-tested but are not reachable from the CLI — they were only ever run by hand.
3. **The three most "judgment-heavy" gates (F1 fabrication, C4 unsupported causality, C5 forbidden claim) and 6 of 10 quality dimensions depend on an LLM judge that has real calibration history but no CI-attached regression protection, no variance measurement in the current runner output, and no policy document constraining when it may be trusted versus overridden by ground truth.**

Separately, there is at least one component (F5 — ignored correction) that is implemented, has cases written for it, and is silently never invoked (`runner.py` hardcodes `correction_ctx = None`). This is the clearest single example of the exact problem this blueprint exists to prevent: infrastructure that *looks* covered in a design doc but is not exercised end-to-end.

**This blueprint does not throw any of the existing work away.** Sections E–N below explicitly reuse `SnapshotSandbox`, `sqlite_guard.make_authorizer`, the gate/dimension split, the holdout isolation pattern, and the rubric-calibration discipline already present. The redesign is about *wiring, taxonomy, and governance* — making the existing pieces trustworthy and connected — not about rebuilding the scoring engine.

**EVAL FOUNDATION VERDICT: READY TO GUIDE A2 DESIGN — NOT READY TO GATE A2 IMPLEMENTATION**

The scoring design, taxonomy, and existing infrastructure (Sections D–N) are sound enough today to inform how A2 should be architected — they tell you what to measure and why. They are not yet sound enough to serve as a release gate on an actual A2 implementation, because the measurement pipeline itself has unresolved wiring gaps, in priority order:

1. No CI / scheduled execution of any of the eval suites (Section M).
2. Track B is not reachable from the one wired runner, so a reproducible Track A vs. Track B comparison does not exist yet — the pilot evidence that does exist is directional, not gating (Section P, step 0).
3. F5 is dead in the runner despite having cases (Section B/C).
4. No LLM-judge policy document exists — judge model pinning, disagreement handling, and permitted-vs-forbidden-use boundaries are implicit in code comments, not governed (Section I).
5. No failure taxonomy connects a bad answer to an owning component deterministically — today "wrong number" could mean six different upstream causes with no forced classification step (Section D).
6. No production→eval feedback loop exists; `eval/alpha_eval_v1` and the holdout report are one-shot, hand-graded snapshots, not renewable pipelines (Section J, K).

Section P gives the sequencing to close these. Until they're closed, use this blueprint to shape A2's design decisions, but do not treat any current eval number as a hard implementation gate.

---

## B. Existing eval inventory

Ground-truthed against the repository at commit `d986996` (worktree `audit/analyst-eval-blueprint-v1`), not against historical docs. Where a doc and the code disagree, the code wins and the divergence is flagged.

### B.1 `eval/benchmark/` — Toesca Analyst Benchmark v1 (TAE + TCE)

This is the primary, most mature suite, and the one referred to historically as "benchmark v1" / "F4" / "Track A".

| Property | Value |
|---|---|
| What it measures | Single/multi-turn analyst correctness (TAE, L1–L8 difficulty tiers) and multi-turn conversational robustness (TCE — ambiguity, corrections, hallucination, investigation, topic reset) |
| Level | Outcome (10 dims) + some component signal folded in (tool_correctness) |
| Method | Hybrid: 7 gates (F2/F3/F4/F5/C1/C2/C3) always deterministic; `factual_correctness`, `completeness`, `conversational_quality` always deterministic (the last never falls back to judge even when unscored — see Section I); `tool_correctness` deterministic when a case declares `tool_requirements`, judge-scored (with a deterministic override guard) otherwise; 3 gates (F1, C4, C5) + 6 dims (`analytical_quality, grounding, hallucination, clarification_judgment, investigation_quality, output_usefulness`) always LLM-judge only — see Section I for the reconciled, code-verified split |
| Dataset | 34 TAE + 17 TCE dev cases (51 cases / 79 evaluable turns), frozen per `DEV_SET_V1_FREEZE.md`; 21 holdout cases (14 TAE + 7 TCE) whose content lives in a **separate private repo**, not in this worktree |
| Ground truth | Yes — every case resolves numeric facts via SQL (`ground_truth_refs`) against the trusted (unguarded) snapshot connection, never hand-typed |
| Connected to runtime? | Partially. `runner.py` drives Track A (`tools.db_chat.answer`) against a pinned snapshot. Track B adapters exist and pass transport-parity tests but have **no CLI path** — they were exercised only via one-off scripts whose invocation is not preserved as a runnable command. |
| Failure modes caught | Wrong entity/period/number (deterministic), unsafe SQL/session leak (deterministic), fabrication/unsupported causality/forbidden claims (judge, when it runs) |
| Failure modes NOT caught | Ignored corrections (F5 implemented but dead — `runner.py` hardcodes `correction_ctx=None`); anything Track B would surface, since it can't be run through the CLI; latency/cost regressions (fields exist in `Usage` but Track A adapter leaves token fields `None`) |
| Reliability | High for the deterministic layer (fail-closed ground truth resolution, fail-closed snapshot hash verification, no silent judge fallback — `judge_failed=True` with zero score on judge failure rather than a guess). Judge layer has documented calibration rounds (v1.1→v1.2, human-vs-judge comparison reports) but no automated regression protection going forward. |
| Cost | Deterministic layer: cheap, no LLM calls. Full run (Track A, dev split, with judge): one LLM call per turn for the system-under-test plus one judge call per turn where gates don't zero it out — real but bounded (51 cases). |
| Wired? | **No.** `eval/benchmark/tests/` (21 files) sits outside `pytest.ini`'s `testpaths=tests`; must be invoked as `pytest eval/benchmark/tests -q` by hand. `runner.py` itself is a standalone script, not in CI. |

### B.2 `eval/product_alpha/` — governed-analytics deterministic eval

| Property | Value |
|---|---|
| What it measures | Canonical KPI lookup / entity ambiguity / ranking drivers / raw exploration / presentation correctness for the "governed analytics" surface |
| Level | Component |
| Method | Pure deterministic pattern-matching: required numbers present (regex boundary), prohibited numbers absent, required entity substrings present, prohibited phrases absent, required capabilities exercised. No judge. |
| Dataset | 8 case YAML files |
| Ground truth | Implicit in each case's required/prohibited literals — no separate answer-key file |
| Connected to runtime? | Yes, structurally (built after `docs/superpowers/plans/2026-08-20-f4-governed-analytics.md` called for it as a TDD red step) |
| Failure modes caught | Simple presence/absence errors on a narrow, well-specified surface |
| Failure modes NOT caught | Anything requiring numeric tolerance, entity resolution nuance, or multi-turn state; no judge means no coverage of grounding/causality quality |
| Reliability | Simple mechanism, low surface area for flakiness, but shallow — passes are easy to game superficially |
| Cost | Free (no LLM calls in the grader itself; case execution presumably still calls an LLM) |
| Wired? | **No** — same `testpaths` exclusion as `eval/benchmark/tests/`. Not verified to currently pass (not executed as part of this audit, per the no-runtime-calls constraint). |

### B.3 `eval/alpha_eval_v1/` — Alpha Product Validation v1

| Property | Value |
|---|---|
| What it measures | Full real-flow round trip: `ConversationService → OpenAIResponsesAnalystSessionFactory → model`, exactly as production wiring, including the presentation layer |
| Level | Outcome/trajectory (captures tool calls, SQL, token usage, latency, termination reason, presentation pre/post text) |
| Method | **No grading code at all.** Captures artifacts only; a human compares captured output against free-text `ground_truth`/`expected_behavior` fields in `cases.json`. Pure human-in-the-loop. |
| Dataset | 15 cases, free-text expectations (not machine-checkable) |
| Ground truth | Free text, not resolvable by SQL — cannot be diffed automatically |
| Connected to runtime? | Yes, most faithfully of any eval here — real session factory, real presenter |
| Failure modes caught | Whatever a human reader happens to notice when reading the JSON output |
| Failure modes NOT caught | Everything not manually re-checked on every run; there is no regression signal here at all — it's a snapshot tool, not a test |
| Reliability | Depends entirely on the human grading it each time; no repeatability guarantee |
| Cost | Real LLM calls (15 cases × multi-turn), no judge calls |
| Wired? | No. Manual script, no CI, no grading automation. |

### B.4 `eval/human_presentation_holdout_v1/holdout_v1.md`

One frozen markdown report, 13 cases, human-graded (by Claude reading live server output) on 4 presentation-layer dimensions (Factual Integrity, Human Readability, Internal-Jargon Leakage, Appropriate Brevity). Explicitly scoped to exclude entity resolution/formulas. One-shot, non-re-runnable, no schema. Level: component (presentation only). Not wired to anything — it is a report, not a test.

### B.5 `tests/eval/` — older deprecated eval (questions.yaml / conversations.yaml)

Component-level, deterministic (metric/entity equality against internal `conversation_state` fields), real LLM calls. **The benchmark's own design doc explicitly states this eval was superseded because it is architecture-coupled** — a correct answer that doesn't expose `last_metric`/`last_entities` internals scores zero. Not part of pytest CI even though it lives under `tests/`, because it is `run_eval.py` (not `test_*.py`, so pytest's own collection pattern skips it). Doc claims 45 questions; the file itself parses to 38 — a live doc/code drift, not resolved here.

### B.6 `tests/` — Analyst runtime pytest suite (the one thing that IS wired)

142 files, collected by a bare `pytest` invocation (`pytest.ini` sets `testpaths=tests`). This is genuine unit/component coverage for: structured intent extraction (`tests/analyst/`), the production tool-calling runtime including sandboxing/governed-analytics/presentation (`tests/analyst_runtime/`, 25 files), workspace/conversation-service/pilot infrastructure (`tests/analyst_workspace/`), data ingestion (`tests/analytics/`, `tests/datasets/`, `tests/db/` — the largest group), and a scoped-down "Round B" mini version of the benchmark harness (`tests/round_b/` — notably, this one benchmark-adjacent piece IS wired, unlike the rest of `eval/benchmark/`).

None of this constitutes an LLM-behavior/conversational eval. It verifies that code does what code is supposed to do given fixture inputs — necessary, not sufficient, and already the healthiest part of the stack because it already runs on every `pytest` invocation.

### B.7 Shared safety infrastructure (not itself an eval, but load-bearing for all of the above)

- `tools/analyst_runtime/sqlite_guard.py::make_authorizer()` — single-source-of-truth SQLite authorizer allow-listing `SELECT/READ/FUNCTION/RECURSIVE`, shared verbatim between `SnapshotSandbox` (benchmark) and `LiveReadOnlySandbox` (production). This is a genuine single point of enforcement, not duplicated/drifted logic — worth preserving exactly as-is in any redesign.
- `tools/analyst_runtime/actions.py::validate_sql()` — a regex pre-filter that is explicitly documented as UX only; the authorizer is the real boundary.
- `eval/benchmark/snapshot.py::SnapshotSandbox` — hash-pinned snapshot (`snapshot.lock`: git commit + blob sha + sha256 + row-count tripwire), read-only+immutable SQLite URI flags, and query tracing the system-under-test cannot spoof (`set_trace_callback` on the sandbox side, not self-reported).
- `eval/benchmark/tests/test_holdout_not_leaked.py` — four real deterministic checks (no case files in holdout dirs, manifest has no semantic fields, whole-file forbidden-key scan, cross-source ID-reference grep) layered on top of physical isolation (holdout content lives outside this repo entirely). Real, well-designed, but itself unwired (same `testpaths` exclusion).

### B.8 The "21 preexisting failures" the task brief references

Correction to the original audit: these are **not** the 21 holdout cases — that reading has been ruled out. Per the user's externally-verified baseline, a full test run at commit `d986996` produced:

```
21 failed, 1342 passed, 6 skipped, 1 xfailed, in 957.59s
```

No artifact reproducing this figure (a report file, a CI log, an xfail list) exists inside the audited worktree — this is **an external run result, not something persisted anywhere in the repository at the time of the audit.** That gap is itself a finding: a known-bad baseline that a human had to run and remember by hand is exactly the kind of state that CI should be capturing automatically (Section M), and its absence from the repo is consistent with Gap C.1 (no CI) rather than contradicting it. This blueprint does not attempt to identify, reproduce, or fix which 21 tests these are — that is explicitly out of scope (Section Q) — but the Eval Foundation Step 0 package (Section P) commits to persisting the *exact failing-test-ID set* (not just the summary counts) as a baseline manifest, and gating every PR on no new IDs being added to it (Section M) — the counts alone are not sufficient for a baseline-delta gate, the ID set is what must be captured.

---

## C. Gaps

Ranked by how directly they block "evaluation-driven" A2/A3/A4 development, not by effort to fix.

1. **No CI at all.** Zero `.github/workflows`, no Makefile eval target. Every suite above is a manual incantation. This is the single largest gap — nothing here can catch a regression unless a human remembers to run it, and "remembering to run the benchmark" does not scale past the person who wrote it.
2. **The wired path only produces evidence for one side of the A2 question.** `runner.py` only drives Track A. A Track A vs. Track B comparison is not itself an architecture-selection mechanism — it is one input, alongside cost, latency, and maintainability, into an A2 decision that remains a human/architectural call. Today even that one input is missing a reproducible form: it exists only as hand-run, non-reproduced pilot results in `FINDINGS.md`.
3. **F5 is a documented illusion of coverage.** Cases exist (`tce-entitycorrection-001`, `tce-entityswap-001`), the gate function exists and is presumably unit-tested in isolation, but the runner never passes `correction_context`, so the correction-handling failure mode this gate exists to catch cannot currently surface in a benchmark run. This exact pattern — "we wrote the eval, it doesn't actually fire" — is the highest-risk failure mode for the whole blueprint and needs a structural safeguard (Section C recommendation: a gate/dimension "liveness" check that asserts every gate/dim exercised by at least one case actually fires a non-`None` verdict at least once across the dev set; run this as its own CI check).
4. **No judge governance.** The judge is well-built (bounded retries, no silent fallback, versioned) but there is no written policy for: when judge output may override a human, what to do on repeated disagreement, how model version pinning is enforced across runs, or what variance is acceptable turn-over-turn for the same input. Section H closes this.
5. **No taxonomy connecting failure → owner → eval.** A wrong number today could stem from wrong entity resolution, wrong period resolution, wrong SQL, a stale semantic mapping, or a synthesis error — and nothing in the current stack forces a run to classify which one happened. Section D closes this.
6. **No production feedback loop.** `eval/alpha_eval_v1` and the presentation holdout are one-shot artifacts. There is no mechanism today by which a real user-reported bad answer becomes a new eval case. Section J/K close this.
7. **Dataset lifecycle is under-specified in practice.** The manifest/freeze scheme (`HOLDOUT_MANIFEST.yaml`, `HOLDOUT_FREEZE_MANIFEST.yaml`, `EVALUATION_RUN_MANIFEST_SPEC.md`) is well-designed on paper but several of the manifest files are governance stubs rather than populated records, and `holdout_runs.md` contains a live internal contradiction (header says "no runs yet," body lists two dated runs) — evidence that manual manifest upkeep already drifts within weeks.
8. **No cost/latency baseline.** The `Usage` dataclass has the right fields, but Track A's adapter doesn't populate token counts, and there is no cost-per-query computation anywhere. Per the sourced principle ("latency/cost after quality"), this is correctly *not* a current blocker, but it must exist before A2 architecture tradeoffs (e.g., multi-agent overhead) can be judged honestly.
9. **Two overlapping "deterministic eval" systems** (`eval/benchmark` and `eval/product_alpha`) with no documented relationship — risk of both drifting independently or of contributors not knowing which to extend.

---

## D. Failure taxonomy

Design goal from the brief: any bad answer → exactly one primary failure class → one component owner → one eval layer that should have caught it → one fix target. Categories are collapsed where the existing benchmark gates already cover them cleanly, to avoid inventing parallel machinery.

| Class | Definition | Component owner | Eval layer that should catch it | Existing infra it maps to |
|---|---|---|---|---|
| **DATA** | Underlying raw/derived data is wrong, stale, or missing at the source (ingestion bug, DB drift, missing period) | Ingestion / `tools/db/*` | `tests/analytics`, `tests/datasets`, `tests/db` (already wired) | existing ingestion test suite |
| **SEMANTIC** | Data exists and is correct, but its meaning was misunderstood (e.g. `renta_uf` treated as total vs. per-m², the exact class of bug `eval/analysis/audit_renta_uf_semantics.py` was written to catch) | Semantic layer / schema documentation | Component eval: semantic-mapping eval (new, Section E) | none dedicated today — closest is one-off audit scripts |
| **ENTITY** | Wrong fund/asset/company resolved from natural language (e.g. Apo3001 attributed to Apo instead of TRI) | Entity resolver (`tools/analyst/entity_resolver.py`) | Component: entity resolution eval; Outcome: gate F2 | `tests/analyst/test_entity_resolver.py`, benchmark gate F2 |
| **METRIC** | Wrong KPI/metric selected or formula misapplied | Metric resolver / formula layer | Component: metric resolution eval (new) | partially: benchmark's `tool_correctness` dim touches this indirectly |
| **PERIOD** | Wrong month/quarter/year resolved, including off-by-one and CDG-vs-calendar-quarter offsets | Temporal resolver (`tools/analyst/temporal.py`) | Component: period resolution eval; Outcome: gate C3 | `tests/analyst/test_temporal.py`, benchmark gate C3 |
| **CONTEXT** | Correct entity/metric/period individually, but wrong resolution of conversational context (pronoun reference, "same period as before", carried-over filter) | Conversation state (`tools/analyst/conversation_state.py`) | Trajectory + component: conversation-state eval | `tests/analyst/test_conversation_state.py`; TCE follow-up/topic-reset cases |
| **PLANNING** | Right facts needed identified, wrong overall approach chosen (e.g. tries to answer with one query when the question needs a multi-step investigation) | Agent orchestration layer (A2 target) | Trajectory eval | none today — new for A2 |
| **TOOL_SELECTION** | Right plan, wrong tool invoked (or no tool invoked when one was needed) | Tool-calling loop | Component: tool selection eval | benchmark `tool_correctness` dim (deterministic when `tool_requirements` present) |
| **TOOL_ARGUMENTS** | Right tool, wrong/malformed arguments | Tool-calling loop / tool contract | Component: tool arguments eval | not currently isolated — folded into `tool_correctness`, should be split (see E.5) |
| **SQL** | Query executes but is logically wrong (wrong join, wrong aggregation, wrong filter) — distinct from TOOL_ARGUMENTS because the tool call itself may be syntactically valid | SQL generation | Component: SQL correctness eval | ground-truth SQL comparison exists per-case but is not a standalone gradeable dimension today |
| **RESULT_VALIDATION** | Tool/SQL returned data, but the agent failed to sanity-check it (didn't notice an empty result set, a suspicious zero, a unit mismatch) before using it | Result validator (does not appear to exist as a distinct component today) | Component: result validation eval | none — genuine gap, flagged for A3 |
| **TRAJECTORY** | The sequence of steps taken was inefficient or looped, even if the final answer was correct | Agent orchestration | Trajectory eval | none automated — `FINDINGS.md`'s "0/8 non-answers" observation is the closest existing evidence, gathered manually |
| **SYNTHESIS** | All upstream facts correct, final natural-language answer misstates or drops them | Presentation/synthesis layer | Outcome: `factual_correctness`, `completeness` dims; Component: synthesis eval | benchmark dims; `tests/analyst_runtime/test_structured_presentation.py`, `test_synthesis_schema_provider.py`; presentation holdout report |
| **CONVERSATION_STATE** | Multi-turn bookkeeping itself is wrong (state not updated, corrected fact not overwritten) | `conversation_state.py` | Outcome: TCE correction cases + gate F5 (once wired); Component: conversation-state unit tests | currently the F5 dead-wiring gap lives exactly here |
| **SAFETY** | Attempted or executed write, cross-session leak, unsafe SQL | `sqlite_guard`, session isolation | Outcome: gates F3, F4; Operational: production monitoring | `sqlite_guard.make_authorizer`, gates F3/F4 — this is the most mature category in the whole stack |
| **INFRA** | Timeout, provider error, malformed API response, retry exhaustion — not a correctness failure at all | Runtime/transport | Operational eval | `Usage`/`latency_ms` fields exist; no dedicated infra eval today |

Deliberately **not** kept as separate top-level classes, to avoid redundant categories: "hallucination" is not its own class — it is SYNTHESIS (fabricating from nothing) or SQL/RESULT_VALIDATION (fabricating from a bad query) depending on where it originates, and should be tagged with the upstream cause once diagnosed, not left as an undifferentiated bucket. "Clarification judgment" is not its own class — a wrong clarify/don't-clarify decision is a PLANNING failure. This keeps the case→class→owner→eval→fix chain from forking at the taxonomy step itself.

Every real production failure must be assigned exactly one primary class (the earliest point in the pipeline where things went wrong) plus optionally secondary classes if the fix genuinely touches more than one component. This is enforced by the trace schema (Section J) capturing enough intermediate state (resolved entity, resolved metric, resolved period, tool decision, SQL, validator outcome) that classification does not require re-running the model.

---

## E. Outcome evals

| Metric | Deterministic or Judge | Definition | Existing coverage |
|---|---|---|---|
| Factual correctness | **Deterministic when ground truth is numeric** (value-in-text tolerance match against SQL-resolved fact); judge only for facts that cannot be reduced to a single resolvable number | Primary/secondary numeric claims match ground truth within tolerance | Benchmark `factual_correctness` dim + gates C1/C2 |
| Groundedness | **Judge**, calibrated against ground-truth SQL results as the reference the judge is shown | Every claim in the answer traces to a tool/SQL result actually returned in this turn | Benchmark `grounding` dim (currently judge-only, unscored by deterministic layer) |
| Completeness | **Deterministic** — checks all `required_facts` for the case appear in the answer | All parts of a multi-part question are addressed | Benchmark `completeness` dim |
| Entity correctness | **Deterministic** — string/ID match against expected entity set | The fund/asset/company the answer is about matches what was asked | Benchmark gate F2 + `conversational_quality` entity-matching |
| Period correctness | **Deterministic** — resolved period matches expected period, with an explicit "declared substitution" carve-out for legitimately ambiguous cases | The month/quarter/year in the answer matches what was asked or explicitly declared as a substitution | Benchmark gate C3 |
| Unit correctness | **Deterministic, currently missing as a standalone check.** Primary signal must come from the Metric/Dataset Contract (A1.5, Section H/I) plus structured tool evidence — the tool call's declared `value_unit`/dataset unit field compared against the unit the answer is required to report, not from scanning prose. A text-near-number regex check is a **secondary synthesis-layer check only** (catches the answer text itself drifting from the unit the structured evidence already established), never the primary signal | The unit the structured tool/dataset evidence declares (CLP vs UF vs % vs per-m²) is the one actually reported, and the answer text doesn't silently relabel it (this is exactly the `renta_uf` class of bug) | **Gap** — depends on Metric/Dataset Contract fields (`value_unit`, display conversion) becoming available in tool evidence per A1.5; until then this can only be checked at the secondary/text level, which should be flagged in results as a lower-confidence signal, not treated as equivalent to a contract-backed check |
| Source-policy correctness | **Deterministic** — evaluated from structured tool evidence: the canonical source/provenance identifier and precedence policy/version the tool call actually resolved and returned (per A1.5's Source/provenance contract, Section J: provider, source-as-of, precedence policy, `superseded_at`), compared against the project's required precedence (e.g. "no usar el CDG"). SQL table-name inspection is **not required as the primary mechanism** — it is at best a fallback signal for tool paths that don't yet emit structured provenance, and should be phased out as those paths adopt the contract | The source/provenance and precedence-policy version the answer's evidence declares match what policy requires for this metric/entity, not merely "which table happened to get queried" | **Gap** — should be a first-class dimension given how central this rule is to the project (per CLAUDE.md, "no usar el CDG" is a standing rule, not a preference); requires tool evidence to expose provenance/precedence fields structurally, which is exactly what A1.5's Source/provenance contract is meant to provide |
| Conversational usefulness | **Judge** — inherently a quality-of-communication judgment | Is the answer usable by a non-technical reader without jargon leakage, appropriate brevity | Benchmark `conversational_quality` + `output_usefulness` dims; presentation holdout report covered this manually |

Deterministic-vs-judge boundary rule, stated once and applied consistently: **if the correct value can be resolved by a SQL query against the snapshot, it must be graded deterministically — a judge is never allowed to be the sole arbiter of a fact that has ground truth.** This is already the design principle behind the gate/dimension split (`judge.py`'s own rule: never re-litigate what layers A–C already decided) and should be stated explicitly as policy so future dimension additions don't quietly regress it.

---

## F. Component evals

A correct final answer must not be allowed to mask a wrong component. Each of these should independently gradeable, ideally against the same trace object the outcome eval consumes (Section J), so component and outcome evals are two views of one run rather than two separate re-executions.

| Component | What to check | Deterministic feasibility | Current state |
|---|---|---|---|
| Entity resolution | Resolved entity/fund/asset key matches expected key, independent of whether the final answer text happens to mention it correctly | Fully deterministic (ID equality) | Unit-tested (`test_entity_resolver.py`); not exposed as a benchmark-level component score today — only visible indirectly via gate F2 on the final text |
| Metric resolution | Resolved metric/formula identifier matches expected metric | Fully deterministic | **Gap** — no dedicated test found; folded into end-to-end correctness only |
| Period resolution | Resolved period (including CDG quarter-offset rules) matches expected period | Fully deterministic | Unit-tested (`test_temporal.py`); benchmark gate C3 covers the final-text side |
| Tool selection | Tool(s) actually invoked match the tool(s) the case's `tool_requirements` calls for | Fully deterministic given `tool_requirements` is present | Partially — benchmark `tool_correctness` dim, but only fires when `tool_requirements` present in the case; should be required on every case going forward, not optional |
| Tool arguments | Arguments passed to a correctly-selected tool are correct (not just that the tool was called) | Fully deterministic once tool selection is confirmed correct | **Gap** — currently conflated with tool selection inside the single `tool_correctness` dimension; recommend splitting into two dims so a right-tool/wrong-args case doesn't get the same score as a wrong-tool case |
| SQL correctness | Generated SQL, when executed, returns the same result set as the case's `ground_truth_refs` SQL (not just that the final number happened to match) | Fully deterministic (result-set diff) | **Gap** — ground truth SQL exists per case, but there's no standalone SQL-correctness component score; today a right-answer-wrong-query case (e.g. right number by coincidence) would pass undetected |
| Result validation | Given a tool/SQL result, did the agent notice an anomaly it should have (empty set, suspicious zero, sign flip) before using it | Needs both a deterministic anomaly-injection harness and judge review of the agent's reaction | **Gap** — no result-validation component exists in the runtime or the eval today; flagged for A3 |
| Source precedence | When multiple sources could answer a question, was the project-mandated source used (e.g. raw EEFF over CDG) | Deterministic once tool evidence carries structured provenance/precedence fields (A1.5 Source/provenance contract: provider, precedence policy/version, `superseded_at`) — SQL table-name inspection is a fallback only, not the target mechanism | **Gap** — maps to the SOURCE-POLICY outcome metric in Section E; needs the trace to record the tool-reported provenance/precedence, not just which table a query happened to hit |
| Synthesis | Given a correct, complete set of facts, does the final text state them correctly | Deterministic for numeric restatement, judge for phrasing/framing quality | Partially covered by `factual_correctness`/`completeness` outcome dims — should also be checked in isolation by feeding a synthesis-only harness a fixed, known-correct fact set and grading the write-up alone, so synthesis bugs aren't hidden behind an upstream fact error |

---

## G. Trajectory evals

Definition of a "valid" trajectory, stated up front per the brief's explicit instruction: **there is no single gold path, and none is imposed here.** A trajectory is valid if it (a) reaches a correct, complete, properly-sourced answer, (b) does not violate any safety gate, and (c) does not exhibit one of the specific anti-patterns below. Multiple tool orderings, multiple valid SQL formulations, differing numbers of tool calls, and different numbers of clarifying turns can all be equally valid — deterministic trajectory gates must only fire on unambiguous anti-patterns, never on "this doesn't match a reference path."

Two rows from the original draft are dropped as a direct result of this amendment: **"unnecessary tool calls," defined as absent-from-final-prose, is removed** — a tool call whose result isn't quoted verbatim in the answer is not evidence of anything; the agent may have used it to check, rule out, or corroborate without needing to cite it, and penalizing that would punish reasonable defensive verification. **"Wrong ordering" against a declared dependency graph is removed** — that is a gold-ordering constraint by another name, and multiple valid orderings can resolve the same question. Anything genuinely wasteful from either of those categories is still caught by the anti-patterns below (repeated identical calls, ignored errors, redundant calls after sufficient evidence already exists) without requiring a canonical path or a citation requirement.

Deterministic trajectory gates, focused strictly on clear anti-patterns, all measurable from the trace schema in Section J without a judge:

| Anti-pattern | Definition | How measured |
|---|---|---|
| Repeated identical action without new state | Same (tool, args) pair invoked again with no intervening change in conversation/entity/period state that would justify re-running it | Deterministic — exact (tool, args, state) match |
| Loops | Same (tool, args) pair appears 3+ times in one turn | Deterministic |
| Ignored tool error | A tool call returns an error/empty result and the very next action neither retries with different arguments, reformulates, nor surfaces the issue to the user | Deterministic (error in trace, no adaptation in next step) |
| Ignored validator feedback | Result-validation flags a concern (once RESULT_VALIDATION exists per Section F) and the agent proceeds unchanged | Deterministic once the validator component exists |
| Premature stopping | Agent returns an answer despite a required fact never having been fetched by any tool call in the trace | Deterministic — cross-check final answer's claims against trace's fetched facts |
| Redundant calls after sufficient evidence | Additional tool calls made after all facts required to answer the question are already present in the trace, with no new question or ambiguity introduced | Deterministic — compare fetched-facts set against `required_facts` at each step |

Judge-assisted signals (not deterministic, and not gating trajectory validity on their own — see Section I for when judge use is appropriate):

| Signal | Why it needs a judge |
|---|---|
| Excessive clarification | Requires judging "was this genuinely ambiguous" — this is exactly the `clarification_judgment` dimension the benchmark already carries as judge-only |
| Tool switching quality | When a tool fails or returns nothing, whether the next chosen tool is a sensible alternative (not a random retry) is a qualitative judgment |

Recommendation: implement the deterministic anti-pattern table first, as pure trace-analysis functions with no LLM call — high signal, zero marginal cost per run, and immediately reusable across every existing case without new judge calls.

---

## H. Operational evals

These run against production or near-production traffic, not the frozen benchmark, and are about the system staying healthy rather than about correctness per se.

| Metric | Definition | Grader | Frequency |
|---|---|---|---|
| Runtime error rate | Fraction of turns ending in an unhandled exception, provider error, or retry exhaustion | Deterministic (trace outcome field) | Continuous / production monitoring |
| Latency (p50/p95) | Per-turn wall-clock time, split by whether it involved tool calls | Deterministic (already has `latency_ms` in `Usage`) | Continuous |
| Token / cost | Per-turn token counts, converted to cost via a pricing table (does not exist yet) | Deterministic once populated (Track A adapter currently leaves this `None` — must be fixed as an infra task before this metric means anything) | Continuous |
| SQL safety violations | Any authorizer denial in production (`sqlite_guard` already logs violations) | Deterministic | Continuous, alerting on any nonzero count |
| Gate/dimension liveness | Every gate and dimension that has at least one case exercising it actually returns a non-`None` verdict at least once per benchmark run | Deterministic — this is the direct fix for the F5-dead-wiring problem (Section C.3) | Every benchmark run (PR/nightly/release, not production) |
| Holdout leak check | `test_holdout_not_leaked.py`'s four checks | Deterministic | Every PR (cheap, no LLM calls, should never have been excluded from CI) |

---

## I. Judge policy

**When judge use is permitted:** second correction to this list, now reconciled directly against `judge.py`'s own `DIMENSION_NAMES` constant and `GATE_NAMES` constant (not against a paraphrase). The actual split is:

- **6 dimensions the judge is always asked about, never computed any other way:** `analytical_quality, grounding, hallucination, clarification_judgment, investigation_quality, output_usefulness`. These never appear in `deterministic.py`'s explicit scoring branches — they fall out of its catch-all "everything else is judge territory" loop every time.
- **1 dimension the judge is asked about only conditionally:** `tool_correctness`. Per `deterministic.py`, this is scored deterministically whenever a case declares `tool_requirements`; only when a case has no `tool_requirements` does it fall through to `unscored_dimensions`, at which point it — uniquely among the "unscored" set — is still in `judge.py`'s `DIMENSION_NAMES`, so the judge scores it, guarded afterward by the deterministic `_enforce_tool_correctness_policy` override (which hard-zeros a judge `not_applicable` verdict when ground truth data existed but no tool was used). **An earlier draft of this section undercounted this as a flat "6 dimensions," dropping `tool_correctness`'s conditional membership — corrected here.**
- **3 hook-only gates:** `F1 (fabrication), C4 (unsupported causality), C5 (forbidden claim)` — per `judge.py`'s `GATE_NAMES`, always `triggered=None` deterministically, always judge-decided.
- **`conversational_quality` is not judge territory in any case**, conditional or otherwise — it is not in `DIMENSION_NAMES` at all. When the deterministic layer cannot compute it (no `expected_entities`/`expected_period` on a turn), it lands in `unscored_dimensions` and **stays unscored permanently** — the judge is never asked to fill that gap. This is a real, narrow coverage gap in the current design (not a bug to fix under this Step 0 scope), and should not be mistaken for a case where the judge silently covers for the deterministic layer.

This split is already the de facto rule in `judge.py` and `gates.py`; this section makes it an explicit, auditable policy rather than an implementation detail scattered across two modules' docstrings.

**When judge use is forbidden:** any dimension where a case's `ground_truth_refs` resolves the answer via SQL, and any dimension the deterministic layer has already scored — including `conversational_quality`, `completeness`, `factual_correctness`, and `tool_correctness` when computed. **A judge must never re-score or override a verdict the deterministic layer has already produced for a given turn.** This is not merely "should be avoided" — it is a hard rule: if a dimension has a deterministic score for this turn, the judge does not see that dimension at all for that turn (per `judge.py`'s existing rule of never re-litigating what layers A–C already decided). If a future dimension addition would let the judge override a deterministically-resolvable fact, that is a policy violation and should fail review. `judge.py`'s existing `_enforce_tool_correctness_policy` override (hard-zeroing a judge's `not_applicable` verdict when ground truth data existed but no tool was used) is a good precedent for this pattern — the judge is corrected/constrained by deterministic evidence, never the reverse — and should be the template for any similar future guard, not a one-off hack.

**Rubric structure:** keep the existing 0–4 anchor scale with `not_applicable_policy` (`rubric.yaml`) — it is simple and atomic per the brief's stated preference for rubrics over vague scores. Do not add a second scoring scale; if a new dimension is added, it must use the same 0–4 anchors so scores remain comparable across dimensions and over rubric versions.

**Calibration:** the existing human-vs-judge comparison discipline (`human_vs_judge_v1_comparison_2026-08-13.md` and its v1.1/v1.2 successors) is exactly right and should be formalized as a required step before any judge-model or rubric-version bump ships — not run informally when someone happens to think of it. Concretely: **no judge-model version change or rubric-version bump may land without a fresh human-vs-judge comparison run on at least the dev set**, gated the same way a release gate would be (Section M).

**Judge-model version pinning:** every judge result must record `rubric_version`, `judge_impl_version` (already does — `JUDGE_IMPL_VERSION`), and the specific model string used (already a required param, never hardcoded — good). The gap is that nothing currently prevents two runs in the same comparison from silently using different pinned models; add a manifest-level check (Section J/K) that a benchmark comparison run refuses to proceed if the two runs being compared used different judge model strings, unless that is the explicit variable under test.

**Repeated-run variance:** not currently measured anywhere. Before the judge is trusted for any release gate, run the same case set through the judge N≥3 times with temperature/sampling held at production settings and report the score variance per dimension. If variance on a dimension exceeds a to-be-set threshold (recommend starting at ±0.5 on the 0–4 scale, tightened once real data exists), that dimension should not gate releases until either the rubric is sharpened or N-sample averaging is adopted for that dimension specifically.

**Disagreement handling:** when human and judge disagree on a dev-set case beyond the calibration tolerance, the case (not the judge) is the default suspect first — check whether the rubric anchor for that dimension is actually unambiguous for this case. Only after ruling out an ambiguous rubric should the disagreement be attributed to judge miscalibration and used to adjust rubric wording (exactly the process the `rubric.yaml` changelog already documents having gone through twice — keep doing this, just make it a required gate rather than an ad hoc improvement).

**Audit of current judges against this policy:** `judge.py` already complies with the "never re-litigate deterministic decisions" rule and the "no silent fallback" rule. It does **not** currently comply with: repeated-run variance measurement (never done), or CI-gated re-calibration on version bump (no CI exists at all, so trivially not done). No policy violation found in what the judge *decides*, only in what *governs whether it's allowed to keep deciding it*.

---

## J. Dataset lifecycle

Four sets, matching the brief's requested structure, mapped onto what already exists:

- **DEV SET** = `eval/benchmark/cases/{tae,tce}/*.yaml`, 51 cases, frozen per `DEV_SET_V1_FREEZE.md`/`DEV_SET_V1_1_FREEZE.md`. Used for iteration, rubric calibration, and PR-level regression. Freely inspectable by anyone working on the agent.
- **REGRESSION SET** = does not exist as a distinct concept today; recommend it be a strict superset mechanism, not a new artifact: every real production failure that gets classified (Section D) and reproduced becomes a new dev-set case tagged `origin: production_failure`, and the regression set *is* "all dev-set cases run on every PR," not a separate file. This avoids the two-systems-drift risk already visible between `eval/benchmark` and `eval/product_alpha`.
- **HOLDOUT** = the 21 cases in the separate private repo, governed by `HOLDOUT_MANIFEST.yaml` + the anti-leak test suite. This isolation pattern is correct and should not be weakened. The only change recommended: `test_holdout_not_leaked.py` must run in CI (Section M), not just at manual freeze time, since the pattern only protects against leaks that are checked for.
- **PRODUCTION FAILURE SET** = does not exist today (`eval/alpha_eval_v1` is the closest analogue but is hand-graded and one-shot, not a persistent growing set). This is the biggest lifecycle gap. Recommend: any user-flagged bad answer, or any answer failing a production-side deterministic check (Section H), gets its trace captured (Section J trace schema) and enters a triage queue; once classified (Section D) and confirmed reproducible against the snapshot, it is promoted into the dev set as a new case with real `ground_truth_refs`, never left as a free-text expectation the way `eval/alpha_eval_v1` cases are today.

**How a real case enters the benchmark (the loop the brief asks for):** production failure → capture trace → classify failure class (Section D) → write `ground_truth_refs` (SQL only, never a hand-typed literal, matching the existing dev-set convention) → add as new dev-set case → run full dev set to confirm it fails as expected pre-fix and passes post-fix → freeze into dev set with a version bump.

**Avoiding holdout contamination:** the existing physical-separation-plus-anti-leak-test design already does this well. Add one more discipline point: nobody who has seen a specific production failure that resembles a holdout case's question shape may write the fix without first checking (via the anti-leak test's ID-reference grep, extended to fuzzy phrase matching) that they are not inadvertently reconstructing holdout content from memory of "the kind of question that gets asked."

**Versioning/manifests:** keep `snapshot.lock`'s (commit+blob+sha256+row-count) pattern — it is a genuinely good tripwire design. Extend `EVALUATION_RUN_MANIFEST_SPEC.md` to be populated automatically by the runner on every run (code commit, model, judge version, rubric version, snapshot hash), not hand-maintained, since hand-maintained manifests are exactly what already drifted in `holdout_runs.md`.

---

## K. Trace contract

Minimum fields to reconstruct and classify any single turn, per the brief's explicit "no private chain-of-thought" constraint — this is an event/decision log, not a reasoning transcript:

```
turn_id, session_id, timestamp
user_turn_text
resolved_entity        (id + resolution method: explicit | inherited-context | inferred)
resolved_metric        (id + resolution method)
resolved_period         (value + resolution method, incl. any quarter-offset rule applied)
planner_decision        (tool chosen, or "clarify", or "direct answer" — with a short structured reason code, not free-text rationale)
tool_calls[]             { tool_name, args, result_metadata (row count, empty?, error?), latency_ms, provenance (per A1.5: provider, precedence policy/version, source-as-of, value_unit), dataset/metric contract ref }
sql_statements[]         { text, result_row_count, source_table(s) hit } — secondary/fallback signal only, not the primary provenance source once tool evidence carries structured provenance
validator_outcome        (pass | flagged: <reason_code> | not_run) — once Section F's result-validation component exists
retries[]                 { reason, outcome }
model, provider, judge_model (if applicable)
latency_ms_total
tokens                    { input, output, reasoning, cached } — must actually be populated (current Track A gap)
final_answer_text
citations / evidence      (which resolved facts the final answer is claiming to state)
gate_results               (F1–F5, C1–C5 verdicts, where applicable)
dimension_scores           (per-dimension, with a flag for deterministic vs judge-sourced)
```

This is deliberately closer to what `eval/benchmark`'s existing `turns.jsonl`/`events.jsonl` outputs already approximate than to a new format — the recommendation is to standardize and mandate this shape everywhere (benchmark runs, `eval/alpha_eval_v1`, and eventually production logging), not invent a fourth trace format.

---

## L. Error-analysis workflow

```
real failure (production flag OR benchmark run regression)
  → classify (Section D taxonomy; exactly one primary class, forced choice)
  → add eval case if none exists that would have caught it (new dev-set case, ground truth via SQL only)
  → reproduce against the pinned snapshot (must reproduce deterministically before proceeding — if it doesn't reproduce, the bug is in something not captured by the trace schema, and Section K needs to expand first)
  → root cause (attributed to exactly one component owner per Section D's table)
  → smallest change (component-level fix, not a prompt-wide rewrite for a single-component bug)
  → targeted eval (does the new/existing component eval for that owner now pass)
  → regression (full dev set, not just the new case — a component fix must not newly fail unrelated cases)
  → compare baseline (dev set score before/after, judge-dimension variance checked if the judge was touched)
  → merge / reject
  → production feedback (once merged, the new case is now part of what continuously guards against this class recurring)
```

**Definition of Done, per change type:**

- **Metric change** (new KPI, formula edit): the metric's entry in the A1.5 Metric Contract (`metric_id`, semantic/method version, formula reference, entity grain, `value_unit`, aggregation, temporal contract, valid entities/scopes, precedence/eligibility, lineage expectations, null semantics/invariants — per `docs/toesca-data-foundation-target-contract-v1.md` Section H) is complete and versioned; component eval for metric resolution passes against that contract entry; at least one outcome case exercising that metric passes. This replaces any prior DoD wording tied to ad hoc formula-documentation style (e.g. `real_estate_finance_expert`-style notes) — the Metric Contract is now the single authoritative definition a metric change must satisfy, not a documentation convention.
- **Tool change** (new tool, changed contract): component evals for both tool_selection and tool_arguments pass for every case referencing that tool; no regression in cases using adjacent tools (contract changes are a common source of silent cross-tool breakage).
- **Semantic source change** (e.g. a `renta_uf` type fix): the specific SEMANTIC-class regression case exists and passes; a full ingestion test pass (`tests/db`, `tests/datasets`) confirms no downstream numeric drift.
- **Agent behavior change** (prompt, planning logic, A2 architecture change): full dev-set outcome run (both TAE and TCE) with no regression on any previously-passing case, trajectory-eval anti-pattern counts not worse than baseline, and — specifically for anything touching Track A/B choice — a side-by-side comparison run of both tracks, since that comparison is the whole point of having two adapters.

---

## M. CI / release gates

Principle from the brief, applied literally: **cheap and deterministic runs on every commit; LLM-judge and full outcome runs are reserved for points where they actually change a decision.**

| Gate | What runs | Cost profile | Blocking? |
|---|---|---|---|
| **EVERY PR** | Full `pytest` (already wired, 142 files) + `eval/benchmark/tests` + `eval/product_alpha/tests` (currently unwired — this is the single highest-value, lowest-cost fix available: these are pure code tests of gates/judge-plumbing/sandbox, zero LLM calls, and should never have been left out of default collection) + holdout-leak test + gate/dimension liveness check (Section H) | Seconds, no LLM calls | **Yes, hard blocker — baseline-aware.** The externally-verified baseline at `d986996` (21 failed / 1342 passed / 6 skipped / 1 xfailed, Section B.8) must first be persisted as an exact failing-test-ID manifest (e.g. `known_failures_d986996.json`, one ID per line/entry). The PR gate then compares the current run's failing-test-ID set against that manifest: **the hard-blocking condition is any failing ID not already in the baseline set (a new regression)**. Baseline failures already in the manifest do not block a PR that doesn't touch them, but they must remain visibly red in the run output — **no baseline failure may be silently marked `xfail`, skipped, or otherwise turned green** without an explicit, reviewed manifest update removing that ID (i.e. fixing it for real, not suppressing it). Shrinking the manifest requires evidence the underlying test now passes; growing it (a newly accepted, reviewed regression) requires the same review rigor as any other baseline change. |
| **NIGHTLY / PERIODIC** | Full dev-set benchmark run (TAE+TCE) on Track A, deterministic layer only (no judge) — catches entity/period/number/safety regressions fast; separately, a lower-frequency (e.g. every 3 nights) full run including the judge layer | "Deterministic-only" describes the *grading* method, not the total run cost: even a deterministic-layer-only run still executes the system-under-test model once per turn (Track A makes a real LLM call to produce the answer being graded), so real inference cost is incurred regardless of whether a judge call happens afterward. What "deterministic-only" saves is exactly one judge call per turn, not the system-under-test call. Judge-included runs add that bounded judge cost on top (51 cases × 1 judge call each). | No (informational, but a sustained multi-night regression should page someone) |
| **PRE-RELEASE** | Full dev-set benchmark run including judge, on every track that is release-relevant (today: Track A only, until A2 makes Track B release-relevant); human-vs-judge spot-check on any dimension whose score moved meaningfully since the last release; holdout run against the private repo (still never committing holdout content itself) | Real cost, acceptable at release cadence | Yes, against the Reliability Core thresholds (Section N) |
| **PRODUCTION MONITORING** | Runtime error rate, latency, SQL safety violations, gate-triggered incidents, token/cost once populated — all from live traffic, no re-run of the benchmark | Continuous, near-zero marginal cost (already-emitted data) | Alerting, not blocking |

Explicitly avoided: no LLM-judge call on every commit; no full holdout run on every PR (holdout is precious specifically because it is rarely touched); no re-running `eval/alpha_eval_v1` as a gate at all until it has actual grading code (Section C) — until then it stays a manual/periodic sanity tool, not a gate.

---

## N. Reliability Core

The preliminary thresholds are directionally reasonable but under-specified. Each is assessed here for meaning, denominator, grader, and blocker status — none are accepted unmodified.

| Threshold as given | Assessment |
|---|---|
| factual ≥95% | **Keep, but define denominator as "per-turn, over all dev-set turns with a resolvable numeric claim"** (not all turns — many turns have no numeric claim to be factually wrong about). Grader: deterministic value-in-text match. Needs a confidence-interval caveat: at 79 evaluable turns, a single-run 95% pass rate has wide binomial CI (roughly ±5pp at n=79) — treat 90–100% as a noisy band until the dev set is larger, and do not release-block on a single point estimate without at least 3 runs. **Release blocker: yes**, but interpreted as "lower bound of a 3-run CI ≥ 90%," not a single-run point estimate ≥95%. |
| grounded ≥95% | Grader is the judge — this threshold inherits all of Section I's variance concerns. **Do not treat this as a hard release blocker until repeated-run judge variance has actually been measured** (currently unmeasured, per Section I). Until then, track it as a monitored metric, not a gate. |
| source policy ≥98% | **This should be deterministic, not judge-based**, since source provenance is a traceable fact — the structured provenance/precedence a tool call reports (A1.5 Source/provenance contract), not merely which table a query happened to hit. Once the trace schema captures that structured provenance per tool call (Section K), this becomes fully deterministic and can legitimately be a hard blocker at a high bar — recommend even tighter than 98% (closer to 100%) given how explicit the "no usar el CDG" project rule already is. **Release blocker: yes, deterministic.** |
| tool correctness ≥95% | Denominator should be "cases with declared `tool_requirements`" — today that's optional per case; recommend making it mandatory for all new dev-set cases going forward so this denominator stops shrinking silently. **Release blocker: yes**, but split per Section F into tool_selection and tool_arguments sub-thresholds rather than one blended number, since a wrong-tool failure and a right-tool-wrong-args failure have very different severities and fixes. |
| entity/period ≥98% | Both deterministic, both should be measured at the *component* level (Section F), not just via the final-answer gates F2/C3 — a case can pass F2/C3 by accident (right entity mentioned despite wrong entity resolved internally, e.g. via lucky phrasing). **Release blocker: yes, component-level version specifically**, not just the outcome-gate version. |
| hallucinated critical numeric claims = 0 | Correct as a hard zero-tolerance gate — this is exactly what fatal gates (F1 combined with C1/C2) are for. Keep as absolute; **any single occurrence blocks release**, no CI/sample-size hedging appropriate for a zero-tolerance safety property. |
| runtime errors ≤2% | This is an **operational**, not outcome, metric — denominator should be production turns over a rolling window, not benchmark turns. Grader: deterministic (trace outcome field). **Release blocker: no** (it's a monitoring metric with its own alert, not a pre-release gate, since pre-release traffic volume is too low for 2% to be statistically meaningful). |
| ambiguous handling ≥95% | This is the `clarification_judgment` dimension — **judge-based, same variance caveat as "grounded" applies.** Also needs a clearer denominator: "over TCE cases specifically designed to test clarify-vs-answer judgment," not all cases. **Release blocker: monitored, not hard-blocking, until judge variance is measured.** |
| multi-turn ≥90% | Ambiguous as stated — needs to specify *which* multi-turn dimensions this aggregates (conversational_quality? full-conversation-level pass rate across all TCE cases?). Recommend defining it explicitly as "fraction of TCE cases with zero gate violations across all turns in the conversation," which is deterministic and unambiguous. **Release blocker: yes, once redefined precisely; not usable as stated.** |
| SQL writes = 0 | Already enforced at the strongest possible layer — the SQLite authorizer denies non-SELECT statements outright, this isn't even a "rate," it's a hard invariant. **Release blocker: yes, trivially — should really be phrased as "authorizer denial count on any non-read action = 0," which the current sandbox already guarantees by construction, not just by measurement.** |

---

## O. Metrics we should stop using or reinterpret

- **"Tool correctness" as a single blended metric** — stop using as-is; split into `tool_selection` and `tool_arguments` (Section F). A blended score hides which failure mode is actually occurring.
- **`eval/alpha_eval_v1`'s free-text `ground_truth`/`expected_behavior` fields** — stop treating these as if they were gradeable; they are not machine-checkable and give a false sense that this suite provides regression protection. Either give them real `ground_truth_refs` (promoting qualifying cases into the real dev set) or explicitly relabel this suite as "manual sanity check tool," not "eval."
- **`tests/eval/`'s metric/entity accuracy against internal `conversation_state` fields** — stop using for any Track B or A2 comparison; it is architecture-coupled by the codebase's own admission and would unfairly zero out a correct answer from a differently-shaped architecture. Keep only as a Track-A-specific regression check if at all, clearly labeled as such.
- **Holdout-run cadence claims in `holdout_runs.md`** — the file's own header ("no runs yet") is stale and contradicted by its body; stop trusting hand-maintained prose logs for anything that gates a release decision. Replace with the auto-populated run manifest from Section J.
- **Any read of "F4 stage 1 results" findings about Track B grounding gaps as current** — `FINDINGS.md`'s note that a specific grounding failure is "uncaught because the judge isn't built" is now stale; the judge exists. Re-run that specific comparison before citing it as evidence of anything about current Track B quality.
- **Treating the 45-question count in the benchmark design doc as authoritative** — the actual `questions.yaml` has 38; use the file, not the doc, until reconciled.

---

## P. Implementation sequence for A2–A5

This blueprint's job is to make evaluation-driven development possible, not to build A2 itself. The sequence below is what should happen *before and alongside* A2, not a substitute for it.

### Eval Foundation Step 0 — minimal implementation package

This is a deliberately narrow, five-item package — wiring and governance only, **no other eval redesign** bundled in. It is the one piece of this blueprint approved to become concrete work before or alongside A2 design:

1. Wire `eval/benchmark/tests`, `eval/product_alpha/tests`, and the holdout-leak test into normal automated checks (cheap, no LLM calls, highest ROI available today).
2. Wire F5 end-to-end in `runner.py` (pass real `correction_context` for TCE correction cases) and add the gate/dimension liveness check (Section H) so this class of silent-dead-eval can never recur unnoticed.
3. Expose Track B through the reproducible benchmark runner (a CLI path in `runner.py`), so a real Track A vs Track B comparison on the full dev set becomes possible in place of the 8-case pilot in `FINDINGS.md`. **This comparison is evidence to inform A2's architecture direction, not a binary switch that selects it** — it sits alongside cost, latency, and maintainability considerations this eval stack does not itself weigh, and step 3 only produces the evidence, not the decision.
4. Populate Track A token/latency usage so cost/latency comparisons enabled by item 3 are honest.
5. Commit the judge policy (Section I) as an actual reviewed document, not implicit code-comment behavior.

Nothing else — no new dimensions, no taxonomy rollout, no dataset-lifecycle automation — belongs in this package. Those follow in Steps 1–3 below, once this minimal package is in place.

**Step 1 (alongside early A2 work):**
6. Split `tool_correctness` into `tool_selection`/`tool_arguments` component scores; add standalone `SQL correctness` and `unit correctness` dimensions (Sections E/F).
7. Stand up the deterministic trajectory-eval functions (Section G's anti-pattern table) as pure trace-analysis, run in the nightly gate.
8. Run a repeated-run judge variance measurement (per the now-committed Section I policy) before treating any judge-based Reliability Core metric as a hard release blocker.

**Step 2 (A3 — Tools/SQL/Safety):**
9. Build the RESULT_VALIDATION component (Section F) — this is a genuine gap the current runtime doesn't have at all, and A3 is the natural place to introduce it alongside its own eval.
10. Add **structured tool/dataset provenance and precedence-policy/version tracing** to the trace schema (per A1.5's Source/provenance contract: provider, precedence policy/version, source-as-of, `superseded_at`), and promote source-policy correctness to a deterministic, hard-blocking Reliability Core metric on that basis. **SQL table-hit inspection is not the target mechanism here** — it remains a fallback/diagnostic signal only, for tool paths that haven't yet adopted structured provenance, consistent with Sections E/F/K's framing.

**Step 3 (A4 — Context/Conversation):**
11. Build the production-failure-set pipeline (Section J) — real user-flagged failures become new dev-set cases with SQL ground truth, closing the production→eval loop the brief calls for.
12. Only after steps 0–11 are in place, evaluate (not implement) the reflection/evaluator-optimizer question (Section G above already frames the eval; do not build the reflection loop itself until an A/B on the existing infrastructure justifies it).

**A5 and beyond:** out of scope for this blueprint; revisit once A2–A4 are evaluation-driven in practice, not just on paper.

---

## Q. Explicit non-goals

- This document does not fix or identify which specific tests make up the externally-verified `21 failed, 1342 passed, 6 skipped, 1 xfailed` baseline at `d986996` (Section B.8), or any bug found during the audit (e.g. the `renta_uf` semantic question, the `questions.yaml` count drift, the `holdout_runs.md` stale header).
- No prompts, graders, gate logic, judge implementation, or rubric content were modified.
- No LLM API calls were made during this audit beyond what the dispatched inventory subagent needed for read-only file inspection (no model was queried, no benchmark run was executed).
- No DB was modified; no snapshot was re-materialized.
- Track B is not made release-relevant by this document — it is made *comparable*, which is a prerequisite to an A2 decision, not the decision itself.
- This blueprint does not resolve the `eval/benchmark` vs `eval/product_alpha` overlap by merging them — it flags the overlap (Section C.9) and recommends the regression-set model (Section J) as the long-term convergence path, but actual consolidation is implementation work outside this audit's scope.
- Does not interfere with, block, or require changes to JLL v2 Production Readiness or A1.5 Data Foundation Target Contract.

---

**EVAL FOUNDATION VERDICT: READY TO GUIDE A2 DESIGN — NOT READY TO GATE A2 IMPLEMENTATION**

The underlying scoring design, taxonomy, sandbox safety, and holdout discipline are sound enough to inform how A2 should be shaped today — this document can be used for that now. What is missing is wiring, not architecture or design substance: CI attachment, a reproducible Track A/B comparison, and a committed judge policy are the three items standing between "we have good eval components to design against" and "we can honestly gate an A2 implementation on these numbers." The Eval Foundation Step 0 package in Section P is achievable without touching any prompt or runtime behavior, and should be completed before any A2 implementation is treated as release-gateable by this eval stack.
