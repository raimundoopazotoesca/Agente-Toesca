# Toesca Real Estate AI Analyst — Pilot Eval Matrix v1

**Status:** contract/design only. **Nothing here is implemented by this document.** No
eval, grader, gate, runner, CI job, or test is created, modified, or wired. This is the
specification of *what evals pilot readiness requires*, not the evals themselves.

**Companion to** `docs/pilot/PILOT_QUALITY_STANDARD_V1.md` (the standard; section refs
below like "§10" point there) and `docs/pilot/PILOT_TASK_BANK_V0.md` (the tasks; refs like
`T-012`).

## Taxonomy — read this first

The `taxonomy_dimension` column uses **the eval blueprint's existing failure taxonomy,
unchanged and closed** (`docs/toesca-analyst-eval-observability-blueprint-v1.md` §D):

`DATA · SEMANTIC · ENTITY · METRIC · PERIOD · CONTEXT · PLANNING · TOOL_SELECTION ·
TOOL_ARGUMENTS · SQL · RESULT_VALIDATION · TRAJECTORY · SYNTHESIS · CONVERSATION_STATE ·
SAFETY · INFRA`

**These sixteen values are the only values `taxonomy_dimension` may take.**

### `PILOT_OPS` removed (correction in this revision)

Draft 1 introduced a seventeenth value, `PILOT_OPS`, for five rows (PE-45 to PE-49). That
conflated two different things: the **failure mode** a row prevents, and the **operational
obligation** a row imposes on people. A dead operator is not a taxonomy class.

`PILOT_OPS` has been removed from this document, from the standard, and from the task bank.
Each affected row now declares a canonical `taxonomy_dimension` chosen by its *actual*
failure mode, plus — where applicable — a separate `pilot_operational_requirement`:

| Row | Draft 1 | Now | Reasoning (some of it debatable, flagged) |
|---|---|---|---|
| PE-45 JLL freshness & coverage honesty | `PILOT_OPS` | **DATA** (+ INFRA secondary) | The failure is *claiming data coverage that does not exist*, or answering pre-v2 data with v2 semantics — a data-correctness failure. The "Analyst cannot reach the v2 views" half is genuinely INFRA (wiring), so INFRA is recorded as secondary. **Debatable:** a reviewer could reasonably make INFRA primary. DATA was chosen because the user-visible harm is a wrong or overclaimed fact, not an outage. Operational: `external_gate_closure`. |
| PE-46 Deterministic report reproducibility | `PILOT_OPS` | **INFRA** (+ RESULT_VALIDATION secondary) | The failures are an LLM appearing in a path declared LLM-free and identical inputs producing different bytes — both properties of the generation *system*. The "validation must block rendering" clause is RESULT_VALIDATION. Operational: `report_cutover`. |
| PE-47 Report-vs-chat number parity | `PILOT_OPS` | **SEMANTIC** (+ RESULT_VALIDATION secondary) | Divergence between report and chat for the same (metric, entity, period) means two implementations of one metric — a violation of single semantic authority (A1.5 §F). That is squarely SEMANTIC. Operational: `report_cutover`. |
| PE-48 Feedback capture & triage loop | `PILOT_OPS` | **INFRA** | The gradeable, mechanical part is *does the flag carry the trace* — observability plumbing, i.e. INFRA. The human triage half is not a failure mode at all and moves entirely to `pilot_operational_requirement: weekly_triage`. |
| PE-49 Operator escalation & stop mechanism | `PILOT_OPS` | **SAFETY** | **Most debatable of the five.** Per the standard §6, operator sign-off is not really a taxonomy dimension — it is an operational requirement. But the row does prevent a concrete failure: *the system keeps serving users after a stop condition has been met*, which is a failure of a safety control, not of analysis. SAFETY is therefore recorded as the failure class, with the substance of the row carried by `pilot_operational_requirement: operator_governance`. A reviewer who wants this row to have no taxonomy dimension at all has a fair argument; the schema does not permit an empty value. |

No blueprint class is renamed, split, merged, or replaced, and nothing is back-propagated
into the blueprint taxonomy.

## Column definitions

| Column | Meaning |
|---|---|
| `eval_id` | Stable id, `PE-nn`. |
| `taxonomy_dimension` | **Canonical blueprint §D class only** — one of the sixteen listed above. No other value is legal. Where a row also touches a second class, it is recorded as "(+ X secondary)"; the primary value is the one the row is filed under. |
| `pilot_operational_requirement` | The named human/process obligation the row imposes, where it imposes one: `operator_governance`, `weekly_triage`, `external_gate_closure`, `report_cutover`. Empty for most rows. **Never a substitute for `taxonomy_dimension`, and never a taxonomy value.** |
| `authority_type` | `SOURCE-DERIVED` / `REPO-EVIDENCE` / `TOESCA-DESIGN-DECISION` / `OPEN-DECISION`, per the standard's authority model. Mapping from the inline letter tags: **S** → `SOURCE-DERIVED`; **A** and **B** → `REPO-EVIDENCE` (governing document / implementation state respectively); **C** → `TOESCA-DESIGN-DECISION`; **D** → `OPEN-DECISION`. A row with several tags takes the *strongest claim it makes*: if any part of the row is a Toesca judgment, the row is `TOESCA-DESIGN-DECISION` in part, and the index below records the mix. |
| `capability` | The product capability under test. |
| `failure_being_prevented` | The concrete bad outcome. |
| `eval_type` | outcome / component / trajectory / operational / contract-test / human-review. |
| `grader` | deterministic / judge / human (or a combination). |
| `evidence_required` | What must exist in the trace or artifacts to grade it. |
| `metric` | What is counted. |
| `threshold_policy` | One of `HARD_INVARIANT`, `ZERO_TOLERANCE`, `THRESHOLD_TO_CALIBRATE`, `BASELINE_RELATIVE`, `HUMAN_ACCEPTANCE_REQUIRED`. |
| `pilot_severity` | P0 / P1 / P2 / P3 per §6/§7. |
| `block_vs_warning` | BLOCK = pilot does not start / stops. WARN = monitored. |
| `trace_fields_required` | Fields from the Pilot Trace Contract (§24). |
| `representative_tasks` | Task-bank ids. |
| `current_coverage` | What exists at `d986996` — verified. |
| `gap` | What is missing. |
| `proposed_future_implementation` | The contract for closing it. Not built here. |
| `source_rationale` | S / A / B / C / D per the standard's authority model (§ "Authority model"). **S** citations name the source file and its section/lesson/slide/page. `A(general)` no longer exists — Draft 1 used it for principles whose sources had not been read; those sources have now been read and are cited concretely. |

## Index

`block/warn` now also carries the **blocking scope** introduced in standard §6: `BLOCK/P`
stops the whole pilot, `BLOCK/C` removes the affected capability from the pilot surface
(unreachable and explicitly refused) while the rest proceeds.

| eval_id | taxonomy_dimension | capability | severity | block/warn | pilot_operational_requirement | authority_type |
|---|---|---|---|---|---|---|
| PE-01 | DATA | Coverage & freshness awareness | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-02 | DATA | Excluded-entity hygiene | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-03 | DATA | Ingestion baseline regression | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-04 | DATA | `superseded_at` discipline | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-05 | SEMANTIC | Metric contract completeness | P0 | BLOCK/C | — | REPO-EVIDENCE |
| PE-06 | SEMANTIC | Unit correctness | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-07 | SEMANTIC | Source-policy / precedence correctness | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-08 | SEMANTIC | No model-invented definitions | P0 | BLOCK/P | — | REPO-EVIDENCE + TOESCA-DESIGN-DECISION |
| PE-09 | ENTITY | Component-level entity resolution | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-10 | ENTITY | Ambiguity surfacing (no silent guess) | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-11 | METRIC | Component-level metric resolution | P1 | WARN | — | REPO-EVIDENCE |
| PE-12 | METRIC | Domain-gated metric unreachability | P0 | BLOCK/C | — | REPO-EVIDENCE |
| PE-13 | PERIOD | Component-level period resolution | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-14 | PERIOD | Declared-substitution discipline | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-15 | CONTEXT | Follow-up inheritance | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-16 | CONTEXT | Entity/period replacement follow-ups | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-17 | PLANNING | Clarify-vs-answer judgment | P1 | WARN | — | REPO-EVIDENCE |
| PE-18 | PLANNING | Investigation depth on causal questions | P0 | BLOCK/P | — | REPO-EVIDENCE + TOESCA-DESIGN-DECISION |
| PE-19 | TOOL_SELECTION | Correct tool chosen | P1 | WARN | — | REPO-EVIDENCE + SOURCE-DERIVED |
| PE-20 | TOOL_ARGUMENTS | Correct arguments | P1 | WARN | — | REPO-EVIDENCE + SOURCE-DERIVED |
| PE-21 | TOOL_SELECTION | Governed-path preference over long tail | P1 | WARN | — | REPO-EVIDENCE + SOURCE-DERIVED |
| PE-22 | SQL | SQL write safety | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-23 | SQL | SQL logical correctness | P1 | WARN | — | REPO-EVIDENCE |
| PE-24 | SQL | Long-tail result-contract parity | P0 | BLOCK/C | — | REPO-EVIDENCE |
| PE-25 | RESULT_VALIDATION | Empty / anomalous / irrelevant result handling | P0 | BLOCK/P | — | REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION |
| PE-26 | RESULT_VALIDATION | Invariant violation surfacing | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-27 | TRAJECTORY | Deterministic anti-patterns | P0/P1 | BLOCK/P (AP-3/AP-4/AP-5); WARN (AP-1/AP-2/AP-6) | — | REPO-EVIDENCE + SOURCE-DERIVED |
| PE-28 | TRAJECTORY | Premature stopping | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-29 | SYNTHESIS | Fabrication (F1 + C1/C2) | P0 | BLOCK/P | — | REPO-EVIDENCE + SOURCE-DERIVED |
| PE-30 | SYNTHESIS | Unsupported causality (C4) | P0 | BLOCK/P | — | REPO-EVIDENCE + TOESCA-DESIGN-DECISION |
| PE-31 | SYNTHESIS | Forbidden claim (C5) | P0 | BLOCK/P | — | REPO-EVIDENCE + OPEN-DECISION |
| PE-32 | SYNTHESIS | Numeric restatement fidelity | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-33 | SYNTHESIS | Completeness | P1 | WARN | — | REPO-EVIDENCE |
| PE-34 | SYNTHESIS | Jargon leakage / readability | P1 | WARN | — | REPO-EVIDENCE |
| PE-35 | SYNTHESIS | Evidence package present & inspectable | P0 | BLOCK/P | — | REPO-EVIDENCE + OPEN-DECISION |
| PE-36 | CONVERSATION_STATE | Correction handling (F5) | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-37 | CONVERSATION_STATE | Topic reset | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-38 | SAFETY | Session isolation (F3/F4) | P0 | BLOCK/P | — | REPO-EVIDENCE + TOESCA-DESIGN-DECISION |
| PE-39 | SAFETY | Auth boundary | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-40 | SAFETY | Holdout non-contamination | P0 | BLOCK/P | — | REPO-EVIDENCE |
| PE-41 | INFRA | Trace reconstructibility | P0 | BLOCK/P | — | REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION |
| PE-42 | INFRA | Latency & cost baseline | P1 | WARN | — | REPO-EVIDENCE + SOURCE-DERIVED |
| PE-43 | INFRA | Error handling / graceful degradation | P0 | BLOCK/P | — | REPO-EVIDENCE + TOESCA-DESIGN-DECISION |
| PE-44 | INFRA | Gate/dimension liveness | P0 | BLOCK/P (P0-backing gates); WARN (others, SW-9) | — | REPO-EVIDENCE |
| PE-45 | DATA (+ INFRA secondary) | JLL v2 freshness & coverage honesty | P0 | BLOCK/C | `external_gate_closure` | REPO-EVIDENCE + TOESCA-DESIGN-DECISION + OPEN-DECISION |
| PE-46 | INFRA (+ RESULT_VALIDATION secondary) | Deterministic report reproducibility | P0 (if shipped) | BLOCK/C | `report_cutover` | REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION |
| PE-47 | SEMANTIC (+ RESULT_VALIDATION secondary) | Report-vs-chat number parity | P0 (if shipped) | BLOCK/C | `report_cutover` | REPO-EVIDENCE |
| PE-48 | INFRA | Feedback capture & triage loop | P0 | BLOCK/P | `weekly_triage` | REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION |
| PE-49 | SAFETY | Operator escalation & stop mechanism | P0 | BLOCK/P | `operator_governance` | TOESCA-DESIGN-DECISION + SOURCE-DERIVED |
| PE-50 | PLANNING | Plan quality & justified replanning | P1 | WARN | — | SOURCE-DERIVED + TOESCA-DESIGN-DECISION |

---

## PE-01 — Coverage & freshness awareness
- **taxonomy_dimension:** DATA · **capability:** knowing which periods/entities exist per metric
- **failure_being_prevented:** answering for a period that has no data, or extrapolating past coverage
- **eval_type:** component · **grader:** deterministic
- **evidence_required:** coverage query result in trace; declared `as_of` in answer
- **metric:** turns where declared coverage matches actual coverage / turns making a period claim
- **threshold_policy:** `HARD_INVARIANT` (coverage check precedes answer) · **severity:** P0 · **BLOCK**
- **trace_fields_required:** `resolved_period`, `tool_calls[].result_metadata`, `tool_calls[].provenance.source-as-of`, `citations`
- **representative_tasks:** T-001, T-018, T-030, T-031
- **current_coverage:** `tools/analyst_runtime/coverage_guard.py` exists and is in active use **[B]**; not verified line-by-line in any audit pass **[B]**
- **gap:** no eval asserts coverage-guard behavior end-to-end at the answer level
- **proposed_future_implementation:** component eval feeding known-empty (entity, metric, period) triples and asserting an explicit no-data response
- **source_rationale:** A (A1.5 §K temporal contract) + B

## PE-02 — Excluded-entity hygiene
- **DATA** · portfolio scope correctness
- **prevents:** naming Machalí / Guardiamarina / Placilla as current portfolio **[B]**
- component · deterministic · **evidence:** final answer text + resolved entity set
- **metric:** occurrences of excluded entities presented as current
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `resolved_entity`, `final_answer_text`
- **tasks:** T-011, T-034
- **current_coverage:** entities removed from `dim_activo`/facts **[B]**; no eval asserts the *answer* never surfaces them
- **gap:** no forbidden-entity assertion in any suite
- **future:** prohibited-substring check, reusing `eval/product_alpha`'s prohibited-phrase mechanism **[B]**
- **source:** B

## PE-03 — Ingestion baseline regression
- **DATA** · data foundation stability
- **prevents:** a silent ingestion regression shipping into a pilot
- contract-test · deterministic · **evidence:** failing-test-ID set vs persisted baseline manifest
- **metric:** count of failing IDs **not present** in the `d986996` baseline set
- `ZERO_TOLERANCE` on new IDs (the baseline itself is `BASELINE_RELATIVE`) · P0 · **BLOCK**
- **trace:** n/a (suite artifact)
- **tasks:** n/a
- **current_coverage:** `tests/db`, `tests/datasets`, `tests/analytics` run under bare `pytest` (`testpaths=tests`) **[B]**. The `21 failed / 1342 passed / 6 skipped / 1 xfailed` baseline is an **external run result not persisted anywhere in the repo** **[B]** (blueprint §B.8)
- **gap:** the baseline ID manifest does not exist; no CI **[B]**
- **future:** persist the exact failing-test-ID set; compare sets, never counts (blueprint §M)
- **source:** A (blueprint §M) + B

## PE-04 — `superseded_at` discipline
- **DATA** · versioned-row correctness
- **prevents:** double-counting superseded rows in an aggregate
- contract-test · deterministic
- **evidence:** dataset-layer SQL text
- **metric:** governed queries over versioned raw tables omitting the filter
- `HARD_INVARIANT` (enforced in the dataset layer, not in prompt text) · P0 · **BLOCK**
- **trace:** `sql_statements[].text`
- **tasks:** T-005, T-021
- **current_coverage:** rule documented in `CLAUDE.md`/A1.5 §J **[B]**; enforced by convention
- **gap:** no structural enforcement or eval on the long-tail SQL path
- **future:** static check over governed dataset definitions + a runtime assertion on long-tail SQL
- **source:** A (A1.5 §J) + B

## PE-05 — Metric contract completeness
- **SEMANTIC** · metric governance
- **prevents:** exposing a metric with undefined unit/grain/temporal semantics
- contract-test · deterministic
- **evidence:** registry entry for every `active` metric reachable from the pilot surface
- **metric:** `active` metrics missing any required A1.5 §H field
- `HARD_INVARIANT` (incomplete ⇒ not `active` ⇒ unreachable) · P0 · **BLOCK**
- **trace:** `resolved_metric`, `tool_calls[].contract ref`
- **tasks:** T-003, T-014, T-026
- **current_coverage:** `semantic/` (`domains.yaml`, `entities.yaml`, `metrics/`, `relationships.yaml`, `synonyms.yaml`) and `tools/datasets/catalog_v1.yaml` exist **[B]**; A1.5 §F names the Semantic Registry as the single target authority, **not yet built as such** **[B]**
- **gap:** multiple partial authorities; A1.5 §N registry contract tests not implemented
- **future:** registry validation as a contract test (A1.5 §N: unique ids, explicit ambiguous aliases, complete `active` metrics)
- **source:** A (A1.5 §F/H/N) + B

## PE-06 — Unit correctness
- **SEMANTIC** · unit fidelity
- **prevents:** the `renta_uf` class of bug — reporting a per-m² rate as a total, or CLP as UF **[B]**
- outcome + component · deterministic
- **evidence:** `value_unit` from structured tool evidence vs the unit reported. Text-near-number regex is a **secondary, lower-confidence** signal only (blueprint §E)
- **metric:** turns where reported unit ≠ evidence `value_unit`
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `tool_calls[].provenance.value_unit`, `final_answer_text`, `citations`
- **tasks:** T-006, T-013, T-026
- **current_coverage:** **none as a standalone dimension** (blueprint §E: gap). `eval/analysis/audit_renta_uf_semantics.py` is a one-off audit script **[B]**. Migration 091 splits the field; `tools/datasets/catalog_v1.yaml:59` deliberately still declares the pre-cutover definition **[B]**
- **gap:** depends on `value_unit` reaching tool evidence per A1.5 §H/I
- **future:** standalone `unit_correctness` dimension, contract-backed primary signal; the blueprint already justifies adding it (§E/§F) — not a new dimension invented here
- **source:** A (blueprint §E, A1.5 §H/I) + B

## PE-07 — Source-policy / precedence correctness
- **SEMANTIC** · provenance governance
- **prevents:** answering from a forbidden or lower-precedence source — "no usar el CDG" is a standing project rule **[B]**
- outcome · deterministic (once structured provenance exists)
- **evidence:** provider, precedence policy/version, source-as-of from tool evidence (A1.5 §J). SQL table-name inspection is a **fallback only**, to be phased out
- **metric:** turns whose evidence provenance violates the metric's declared precedence
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `tool_calls[].provenance`, `sql_statements[].tables hit`
- **tasks:** T-003, T-014, T-020
- **current_coverage:** rule exists in `CLAUDE.md`/memory **[B]**; not a first-class eval dimension (blueprint §E gap)
- **gap:** tool evidence does not yet carry structured provenance/precedence
- **future:** blueprint §P step 2.2 — add structured provenance to the trace, then promote this to a deterministic hard gate (blueprint §N recommends closer to 100% than 98%)
- **source:** A (blueprint §E/N, A1.5 §J) + B

## PE-08 — No model-invented definitions
- **SEMANTIC** · definitional authority
- **prevents:** the LLM inventing a business definition at answer time
- outcome · judge (grounding/hallucination) + deterministic contract-ref check
- **evidence:** every metric stated maps to a contract entry present in the trace
- **metric:** definitional statements with no contract reference
- `ZERO_TOLERANCE` for the deterministic contract-ref part; `THRESHOLD_TO_CALIBRATE` for the judge-scored part (judge variance unmeasured) · P0 · **BLOCK**
- **trace:** `resolved_metric`, `tool_calls[].contract ref`, `final_answer_text`
- **tasks:** T-014, T-026, T-037
- **current_coverage:** judge dims `grounding`/`hallucination` exist **[B]**
- **gap:** no deterministic contract-reference requirement on definitional claims
- **future:** require a contract ref in the evidence package whenever the answer defines a metric
- **source:** A (A1.5 §F/H) + C (the deterministic requirement is a proposal)

## PE-09 — Component-level entity resolution
- **ENTITY** · entity resolver
- **prevents:** wrong fund/asset resolved internally — e.g. `Apo3001` attributed to `Apo` rather than `TRI` **[B]**
- component · deterministic (id equality)
- **evidence:** `resolved_entity.id` vs expected key
- **metric:** exact-match rate at the component level, **not** via the final-answer gate F2 — a case can pass F2 by lucky phrasing (blueprint §N)
- `THRESHOLD_TO_CALIBRATE` — blueprint §N proposes ≥98%; fix only as the lower bound of a ≥3-run measurement · P0 · **BLOCK**
- **trace:** `resolved_entity` (+ resolution method)
- **tasks:** T-002, T-009, T-022, T-023, T-033
- **current_coverage:** `tests/analyst/test_entity_resolver.py` unit tests **[B]**; benchmark gate F2 at the outcome level **[B]**; **no component-level benchmark score** (blueprint §F)
- **gap:** the resolved entity is not surfaced as a gradeable component score; A1.5 D35 (single identity authority) is architectural debt to be resolved inside A2 **[B]**
- **future:** expose `resolved_entity` in the trace and grade it directly
- **source:** A (blueprint §F/N) + B

## PE-10 — Ambiguity surfacing (no silent guess)
- **ENTITY** · resolver contract
- **prevents:** silently choosing among `Apo` / `Apo4501` / `Apo4700` / `Apo3001` / the `Fondo Apoquindo` scope
- component · deterministic
- **evidence:** resolver returns `resolved | ambiguous | unknown` with evidence (A1.5 §G)
- **metric:** turns where an ambiguous input produced a `resolved` verdict without disclosure
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `resolved_entity.method`, `planner_decision`
- **tasks:** T-022, T-023, T-033
- **current_coverage:** ambiguity documented in `docs/matriz-claves-ambiguas-apoquindo.md` **[B]**; `derived_kpi` still carries the legacy mislabeled `Apoquindo` / `Fondo Apoquindo` entities **[B]**
- **gap:** the three-valued resolver contract is A1.5 target state, not current state
- **future:** resolver returns the tri-state; eval asserts it on a curated ambiguous set
- **source:** A (A1.5 §G) + B

## PE-11 — Component-level metric resolution
- **METRIC** · metric resolver
- **prevents:** answering NOI when asked for ingresos, or the wrong variante
- component · deterministic (id equality)
- **metric:** resolved `metric_id` match rate
- `THRESHOLD_TO_CALIBRATE` · P1 · **WARN**
- **trace:** `resolved_metric`
- **tasks:** T-003, T-014, T-026, T-037
- **current_coverage:** **none** — "no dedicated test found; folded into end-to-end correctness only" (blueprint §F) **[B]**
- **gap:** whole component score missing
- **future:** metric-resolution eval against the Metric Contract entry
- **source:** A (blueprint §F)

## PE-12 — Domain-gated metric unreachability
- **METRIC** · publication eligibility
- **prevents:** answering with `dy_amort`, or LTV/DSCR/net debt/duration without approved temporal methodology, or vacancia with unresolved UG, or Mall Curicó account-mapped ER **[B]** (A1.5 A2 Entry Gates)
- contract-test · deterministic
- **evidence:** the pilot's reachable metric surface
- **metric:** gated metrics reachable from the Analyst
- `HARD_INVARIANT` (unreachable by construction, not caveated) · P0 · **BLOCK**
- **trace:** `resolved_metric`, `tool_calls[].contract ref`
- **tasks:** T-036, T-038
- **current_coverage:** gates declared in A1.5 **[B]**; enforcement mechanism not built
- **gap:** no eligibility check between the resolver and the tool surface
- **future:** `publication_eligibility` on the Metric Contract, enforced at tool-schema build time
- **source:** A (A1.5 §H, closeout amendment) + B

## PE-13 — Component-level period resolution
- **PERIOD** · temporal resolver
- **prevents:** off-by-one months; the CDG quarter-offset rules (CDG marzo → EEFF dic del año anterior, etc.) **[B]**
- component · deterministic
- **metric:** resolved-period match rate at component level (blueprint §N: not only via gate C3)
- `THRESHOLD_TO_CALIBRATE` (≥98% proposed by blueprint §N; calibrate over ≥3 runs) · P0 · **BLOCK**
- **trace:** `resolved_period` (+ method, incl. offset rule applied)
- **tasks:** T-004, T-024, T-025, T-030
- **current_coverage:** `tests/analyst/test_temporal.py` **[B]**; gate C3 at outcome level **[B]**
- **gap:** no component-level benchmark score
- **future:** grade `resolved_period` directly from the trace
- **source:** A (blueprint §F/N) + B

## PE-14 — Declared-substitution discipline
- **PERIOD** · temporal honesty
- **prevents:** silently answering for June when July was asked
- outcome · deterministic
- **evidence:** answer text declares the substitution; trace records the resolution method
- **metric:** undeclared period substitutions
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `resolved_period.method`, `final_answer_text`
- **tasks:** T-024, T-030, T-031
- **current_coverage:** gate C3 carries an explicit declared-substitution carve-out **[B]** (blueprint §E)
- **gap:** carve-out defined for the benchmark, not asserted on production turns
- **future:** same check applied to pilot traffic
- **source:** A (blueprint §E)

## PE-15 — Follow-up inheritance
- **CONTEXT** · conversation state
- **prevents:** "¿Y Apoquindo?" losing the metric or period from the prior turn
- component + trajectory · deterministic
- **evidence:** resolved triple on turn N vs turn N−1 with `method: inherited-context`
- **metric:** correct inheritance rate on multi-turn tasks
- `THRESHOLD_TO_CALIBRATE` · P0 · **BLOCK**
- **trace:** `resolved_entity/metric/period` with methods, across turns of one `session_id`
- **tasks:** T-032, T-033, T-034
- **current_coverage:** `tests/analyst/test_conversation_state.py` **[B]**; TCE follow-up cases **[B]**
- **gap:** inheritance is not exposed as a per-turn trace assertion
- **future:** trace-level inheritance check across turns
- **source:** A (blueprint §D CONTEXT / §F)

## PE-16 — Entity/period replacement follow-ups
- **CONTEXT** · state replacement
- **prevents:** replacing the entity but silently keeping a stale filter, or vice versa
- component · deterministic
- **metric:** correct replace-one-hold-rest rate
- `THRESHOLD_TO_CALIBRATE` · P0 · **BLOCK**
- **trace:** cross-turn resolved triples
- **tasks:** T-033, T-034, T-035
- **current_coverage:** TCE entity-swap cases exist (`tce-entityswap-001`) **[B]**
- **gap:** those cases sit in the unwired benchmark suite **[B]**
- **future:** same as PE-15
- **source:** A (blueprint §B.1/§D) + B

## PE-17 — Clarify-vs-answer judgment
- **PLANNING** · clarification policy
- **prevents:** both silent guessing and over-clarification
- outcome · judge (`clarification_judgment`) — silent *guessing* is separately deterministic via PE-10/PE-14
- **metric:** `clarification_judgment` score on ambiguity-designed tasks; denominator = tasks specifically designed to test clarify-vs-answer (blueprint §N)
- `THRESHOLD_TO_CALIBRATE` — **monitored, not blocking, until judge repeated-run variance is measured** (judge policy) · P1 · **WARN**
- **trace:** `planner_decision`, `judge_model`, `rubric_version`, `judge_impl_version`
- **tasks:** T-022, T-023, T-024, T-025, T-026
- **current_coverage:** dimension exists, judge-only, calibrated over rounds v1.1→v1.2 **[B]**
- **gap:** repeated-run variance **never measured** **[B]** (judge policy)
- **future:** N≥3 variance run before this can gate anything (blueprint §P step 1.3)
- **source:** A (blueprint §I/N, judge policy)

## PE-18 — Investigation depth on causal questions
- **PLANNING** · investigation
- **prevents:** answering "¿por qué cayó el NOI?" from one query
- trajectory · deterministic (tool-call count/shape) + judge (`investigation_quality`)
- **evidence:** trace shows decomposition steps, or an explicit insufficiency statement
- **metric:** causal-family turns answered with a single query and an asserted cause
- `ZERO_TOLERANCE` for the deterministic part · P0 · **BLOCK**
- **trace:** `tool_calls[]`, `planner_decision`, `final_answer_text`
- **tasks:** T-039, T-040, T-041
- **current_coverage:** `investigation_quality` judge dimension **[B]**; the benchmark's own `FINDINGS.md` documents Track A returning generic non-answers on 8/8 harder pilot cases **[B]**
- **gap:** no deterministic single-query-causal-assertion detector
- **future:** trace-analysis function; pairs with PE-30
- **source:** A (blueprint §G) + C (the deterministic rule is a proposal)

## PE-19 — Correct tool chosen
- **TOOL_SELECTION** · tool-calling loop
- **prevents:** wrong tool, or no tool when one was needed
- component · deterministic when `tool_requirements` declared; judge only otherwise, guarded by the deterministic override (judge policy)
- **metric:** tool-selection match rate; denominator = cases with declared `tool_requirements`
- `THRESHOLD_TO_CALIBRATE` (blueprint §N ≥95% is a starting proposal, and must be split from arguments) · P1 · **WARN**
- **trace:** `tool_calls[].tool_name`, `planner_decision`
- **tasks:** T-001, T-007, T-016, T-028
- **current_coverage:** `tool_correctness` dim, deterministic when `tool_requirements` present **[B]**
- **gap:** blended with arguments; `tool_requirements` optional, so the denominator shrinks silently **[B]**
- **future:** split per blueprint §F/§P step 1.1; make `tool_requirements` mandatory on new cases
- **source:** A (blueprint §F/N/O) + **S** — the split is independently the shape used by the GPA framework, which evaluates *Tool Selection* (match-to-goal, comparative suitability, awareness of tool limits; explicitly **not** call syntax) and *Tool Calling* (syntactic and semantic validity of inputs, preconditions, faithful interpretation of outputs, handling of tool-returned errors; explicitly **not** tool choice) as two judges with disjoint rubrics — `04_cs329t_knowledge_pack_all.md`, Agent GPA slides 15 and 19. This corroborates a split the blueprint had already justified; it does not introduce a new dimension

## PE-20 — Correct tool arguments
- **TOOL_ARGUMENTS** · tool contract
- **prevents:** right tool, wrong entity key / period / scope argument
- component · deterministic
- **metric:** argument-match rate given correct selection
- `THRESHOLD_TO_CALIBRATE` · P1 · **WARN**
- **trace:** `tool_calls[].args`
- **current_coverage:** **none as a separate score** — conflated inside `tool_correctness` **[B]**
- **gap:** a right-tool/wrong-args case currently scores identically to a wrong-tool case
- **future:** blueprint §P step 1.1 split (its own justified extension, not a new dimension here)
- **tasks:** T-007, T-016, T-021, T-028
- **source:** A (blueprint §F/O)

## PE-21 — Governed-path preference over long tail
- **TOOL_SELECTION** · routing discipline
- **prevents:** the long tail quietly re-implementing a governed metric with different semantics
- trajectory · deterministic
- **metric:** share of turns using long-tail SQL where a governed path existed
- `BASELINE_RELATIVE` (trended over the pilot, reviewed weekly) · P1 · **WARN**
- **trace:** `planner_decision`, `tool_calls[]`, `sql_statements[]`
- **tasks:** T-020, T-027, T-029
- **current_coverage:** both paths exist; **which questions route to which was not verified** in the current-state audit **[B]**
- **gap:** no routing eval at all
- **future:** routing check comparing the resolved metric against the governed catalog
- **source:** A (A1.5 §L) + B

## PE-22 — SQL write safety
- **SQL** · sandbox
- **prevents:** any write, DDL, ATTACH, or non-read action from the Analyst
- operational + contract-test · deterministic
- **metric:** authorizer denial count on any non-read action
- `HARD_INVARIANT` — guaranteed by construction, **not a rate** (blueprint §N) · P0 · **BLOCK**
- **trace:** `sql_statements[]`, authorizer log
- **tasks:** T-042
- **current_coverage:** **strongest area in the stack** — `tools/analyst_runtime/sqlite_guard.py::make_authorizer()` allow-lists `SELECT/READ/FUNCTION/RECURSIVE`, shared verbatim between `SnapshotSandbox` and `LiveReadOnlySandbox` **[B]**. `actions.py::validate_sql()` is documented as UX-only, not the boundary **[B]**
- **gap:** the tests asserting it sit outside `pytest.ini`'s `testpaths` and no CI runs them **[B]**
- **future:** wire into the pre-deployment check (blueprint §P step 0.1)
- **source:** A (blueprint §B.7/§N) + B

## PE-23 — SQL logical correctness
- **SQL** · query generation
- **prevents:** right number by coincidence from a wrong join/filter/aggregation
- component · deterministic (result-set diff against `ground_truth_refs` SQL)
- **metric:** result-set equality rate
- `THRESHOLD_TO_CALIBRATE` · P1 · **WARN**
- **trace:** `sql_statements[].text`, `result_row_count`
- **tasks:** T-020, T-027, T-029
- **current_coverage:** per-case `ground_truth_refs` SQL exists **[B]**; **no standalone SQL-correctness score** (blueprint §F gap)
- **gap:** a right-answer-wrong-query case passes undetected today
- **future:** blueprint §P step 1.1
- **source:** A (blueprint §F)

## PE-24 — Long-tail result-contract parity
- **SQL** · publication boundary
- **prevents:** a long-tail answer carrying weaker provenance than a governed answer
- contract-test · deterministic
- **evidence:** the long-tail result carries entity/scope, metric+method version, period/as-of, unit, quality, structured citations (A1.5 §L)
- **metric:** long-tail results missing any contract field
- `HARD_INVARIANT` · P0 · **BLOCK**
- **trace:** `tool_calls[].provenance`, `citations`
- **tasks:** T-027, T-029
- **current_coverage:** the boundary is A1.5 **target** state **[B]**; not built
- **gap:** the whole result-contract wrapper for the long-tail path
- **future:** one result-contract type shared by governed and long-tail paths
- **source:** A (A1.5 §L)

## PE-25 — Empty / anomalous / irrelevant result handling
- **RESULT_VALIDATION** · validator · **blocking scope:** `PRODUCT` · **authority_type:** REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION
- **prevents:** "la vacancia fue 0%" when the result set was empty — **and, added in this revision, a non-empty result that answers a different question than the one asked** (RV-6). "The query executed" is not "the query answered the question"
- component · deterministic
- **evidence:** `result_metadata.empty` in trace vs the answer's claim; **plus** equality between the resolved `(entity, metric, period, grain)` tuple and the tuple the result's own metadata declares (TU-3)
- **metric:** (a) empty-set results rendered as a business fact; (b) answers whose resolved tuple differs from the returned result's declared tuple
- `ZERO_TOLERANCE` on both · P0 · **BLOCK/P**
- **trace:** `tool_calls[].result_metadata`, `tool_calls[].provenance`, `resolved_entity/metric/period`, `validator_outcome`, `final_answer_text`, `span_type=retrieval`
- **tasks:** T-036, T-037, T-038
- **current_coverage:** **none — no result-validation component exists in the runtime or the eval** **[B]** (blueprint §D/§F, flagged for A3)
- **gap:** the entire component. The relevance leg (b) additionally requires the `span_type` labelling of §24 so the evaluated retrieval steps are identifiable
- **future:** the §14 RV-5 minimum subset (empty-set, null/zero vs declared null semantics, unit equality, coverage, relevance) — richer anomaly-injection harness is P2; RV-7 cardinality/duplication is P1
- **source:** A (blueprint §F) + **S** — the relevance leg is the RAG-Triad's *context relevance* applied to a data agent's retrieval steps (`01_building_and_evaluating_data_agents.md` Lesson 4) and the separately-named failures in `04_cs329t_knowledge_pack_all.md` Lecture 3 slides 38–40 — + C. Note the deliberate divergence from the source: it scores relevance with an LLM judge over free text; Toesca's results are *structured*, so the same check is done deterministically by tuple comparison, which is cheaper and does not inherit the judge failure modes of P15

## PE-26 — Invariant violation surfacing
- **RESULT_VALIDATION** · metric invariants
- **prevents:** reporting a value outside the metric's declared invariants (negative vacancy, ratio > 1, a 100× unit slip)
- component · deterministic
- **metric:** invariant violations passed through silently
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `validator_outcome`, `tool_calls[].contract ref`
- **tasks:** T-037, T-043
- **current_coverage:** invariants named as required contract tests in A1.5 §N (units, ratios, no SUM of snapshot/ratio, NOI reconciliation, DY, 100×) **[B]**; not implemented
- **gap:** invariants not declared per metric, not checked at answer time
- **future:** invariants as Metric Contract fields, checked by the validator
- **source:** A (A1.5 §H/N)

## PE-27 — Deterministic trajectory anti-patterns
- **TRAJECTORY** · orchestration
- **prevents:** AP-1 repeated identical action, AP-2 unproductive repetition, AP-3 ignored tool error, AP-4 ignored validator result, AP-6 redundant querying after sufficient evidence (§11)
- trajectory · deterministic, pure trace analysis, **no LLM call**
- **metric:** per-anti-pattern occurrence counts
- **AP-3/AP-4: `ZERO_TOLERANCE`, P0, BLOCK/P. AP-1/AP-2/AP-6: `BASELINE_RELATIVE`, P1/P2, WARN.** *(Changed in this revision: Draft 1 made AP-2 a `ZERO_TOLERANCE` P0 gate triggered by "the same `(tool, args)` 3+ times", an invented count. The sources judge repetition by purpose rather than frequency — the Execution Efficiency rubric explicitly permits verification steps and inline-evaluation steps that "provide unique feedback, serve as sanity checks, or use a demonstrably different approach", and penalises only repetition that contributes nothing (`04_cs329t_knowledge_pack_all.md`, Agent GPA slide 11) **[S]**. The P0 hazard — repetition that ends in an unacknowledged failure — is already fully covered by AP-3 and AP-5/PE-28, so nothing is weakened.)*
- **trace:** `tool_calls[]` sequence, `retries[]`, `validator_outcome`, resolved-state per step
- **tasks:** T-039, T-040, T-044
- **current_coverage:** **none automated** — the closest evidence is `FINDINGS.md`'s manually-gathered observation **[B]**
- **gap:** the anti-pattern functions do not exist
- **future:** blueprint §P step 1.2 — implement as pure trace-analysis functions first (highest signal, zero marginal cost). Note blueprint §G explicitly **removed** "unnecessary tool calls" and "wrong ordering" as anti-patterns; do not reintroduce them
- **source:** A (blueprint §G)

## PE-28 — Premature stopping
- **TRAJECTORY** · sufficiency
- **prevents:** answering though a required fact was never fetched — the trajectory-level form of fabrication
- trajectory · deterministic
- **metric:** answers whose claims exceed the trace's fetched-facts set
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `tool_calls[]`, `citations`, `final_answer_text`
- **tasks:** T-039, T-044
- **current_coverage:** none
- **gap:** requires `required_facts` per task and a claims-vs-fetched comparison
- **future:** blueprint §G row, implemented with PE-27
- **source:** A (blueprint §G)

## PE-29 — Fabrication (F1 + C1/C2)
- **SYNTHESIS** · grounding
- **prevents:** any invented number, entity, period, or tenant name
- outcome · **judge** for F1 (always judge-decided, per blueprint §I / judge policy); **deterministic** for C1/C2 numeric ground truth
- **metric:** hallucinated critical numeric claims
- `ZERO_TOLERANCE` — "any single occurrence blocks release; no CI/sample-size hedging is appropriate for a zero-tolerance safety property" (blueprint §N) · P0 · **BLOCK**
- **trace:** `citations`, `tool_calls[]`, `gate_results`, `judge_model`/`rubric_version`/`judge_impl_version`
- **tasks:** T-036, T-037, T-039, T-045
- **current_coverage:** F1 implemented, judge-decided; C1/C2 deterministic **[B]**
- **gap:** none in mechanism; the gap is that nothing runs it automatically **[B]** (no CI)
- **future:** included in the pre-deployment check; judge cost bounded by sampling on pilot traffic (§24 SHOULD)
- **source:** A (blueprint §I/N, judge policy)

## PE-30 — Unsupported causality (C4)
- **SYNTHESIS** · causal discipline
- **prevents:** "el NOI cayó porque se fue X" without decomposition evidence
- outcome · **judge** (always judge-decided, blueprint §I) + **human** spot-review of every causal turn during the pilot's first phase (§17 UC-5)
- **metric:** unsupported causal assertions
- `ZERO_TOLERANCE` (gate) + `HUMAN_ACCEPTANCE_REQUIRED` (spot-review, because judge variance is unmeasured) · P0 · **BLOCK**
- **trace:** `gate_results.C4`, `tool_calls[]`, `final_answer_text`
- **tasks:** T-039, T-040, T-041
- **current_coverage:** C4 exists as a judge-decided gate **[B]**
- **gap:** unmeasured judge variance on a P0 gate — the reason PE-30 carries a human layer at pilot
- **future:** after XC-3 (variance measured), the human layer can be reduced to sampling
- **source:** A (blueprint §I/N) + C (the human spot-review requirement is a proposal)

## PE-31 — Forbidden claim (C5)
- **SYNTHESIS** · claim boundaries
- **prevents:** claims outside the product's authorized scope (e.g. investment advice, valuation assertions, forward guidance)
- outcome · judge (always judge-decided)
- **metric:** forbidden-claim occurrences
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `gate_results.C5`
- **tasks:** T-045, T-046, T-047
- **current_coverage:** C5 exists **[B]**
- **gap:** **[D]** the forbidden-claim list has not been enumerated for the pilot context — needs a human decision (see §32)
- **future:** enumerate the list, then encode as rubric anchors
- **source:** A (blueprint §I) + D

## PE-32 — Numeric restatement fidelity
- **SYNTHESIS** · presentation
- **prevents:** correct upstream facts, wrong number in the prose
- outcome · deterministic (value-in-text tolerance match against SQL-resolved ground truth)
- **metric:** factual correctness; denominator = **turns with a resolvable numeric claim**, not all turns (blueprint §N)
- `THRESHOLD_TO_CALIBRATE` — blueprint §N: interpret as "lower bound of a 3-run CI ≥ 90%", **not** a single-run point estimate ≥95%, given ~79 evaluable turns and a ±5pp binomial CI · P0 · **BLOCK**
- **trace:** `citations`, `final_answer_text`, `dimension_scores`
- **tasks:** T-001, T-005, T-012, T-016
- **current_coverage:** `factual_correctness` dim + gates C1/C2, deterministic **[B]**
- **gap:** single-run point estimates are still what get quoted; the 3-run discipline is not enforced
- **future:** 3-run requirement in the pre-deployment check
- **source:** A (blueprint §E/N)

## PE-33 — Completeness
- **SYNTHESIS** · multi-part questions
- **prevents:** answering half a two-part question
- outcome · deterministic (`required_facts` presence)
- **metric:** completeness rate
- `THRESHOLD_TO_CALIBRATE` · P1 · **WARN**
- **trace:** `citations`, `final_answer_text`
- **tasks:** T-015, T-019, T-028
- **current_coverage:** `completeness` dim, deterministic **[B]**
- **gap:** requires `required_facts` on every pilot task
- **future:** mandatory `required_facts` on new cases
- **source:** A (blueprint §E)

## PE-34 — Jargon leakage / readability
- **SYNTHESIS** · presentation layer
- **prevents:** `fondo_key`, table names, tool names, or internal codes reaching a non-technical reader
- outcome · deterministic (prohibited-substring) + judge (`output_usefulness`)
- **metric:** jargon-leak occurrences; usefulness score
- `THRESHOLD_TO_CALIBRATE` · P1 · **WARN**
- **trace:** `final_answer_text`
- **tasks:** T-001, T-012, T-019
- **current_coverage:** `eval/human_presentation_holdout_v1/holdout_v1.md` — one frozen 13-case human-graded report on Factual Integrity / Human Readability / Internal-Jargon Leakage / Appropriate Brevity. **One-shot, non-re-runnable, no schema, not wired to anything** **[B]**
- **gap:** no repeatable version
- **future:** deterministic prohibited-substring list + the existing `output_usefulness` dim
- **source:** A (blueprint §B.4/§E) + B

## PE-35 — Evidence package present & inspectable
- **SYNTHESIS** · provenance surfacing
- **prevents:** a user unable to check a number without a developer
- outcome · deterministic (fields present) + human (usability)
- **metric:** factual answers missing any of entity/scope, metric+method version, period+as-of, unit, quality/coverage, provenance
- `HARD_INVARIANT` for field presence; `HUMAN_ACCEPTANCE_REQUIRED` for the inspection affordance · P0 · **BLOCK**
- **trace:** `citations`, `tool_calls[].provenance`
- **tasks:** T-001, T-003, T-014, T-020
- **current_coverage:** `evidence_inventory.py`, `derived_claims.py`, `canonical_guard.py`, `coverage_guard.py` exist in `tools/analyst_runtime/` **[B]**; their combined behavior was **not verified line-by-line** by the current-state audit **[B]**
- **gap:** no eval asserts the full evidence contract at the answer level; the UX affordance is an open decision **[D]**
- **future:** result-contract assertion + a UI affordance
- **source:** A (A1.5 §L, blueprint §K) + B + D

## PE-36 — Correction handling (F5)
- **CONVERSATION_STATE** · state overwrite
- **prevents:** a user correction being acknowledged and then ignored
- outcome · deterministic gate F5
- **metric:** corrected facts re-used after correction
- `ZERO_TOLERANCE`; plus `HARD_INVARIANT` that the gate is **demonstrated firing** (liveness) · P0 · **BLOCK**
- **trace:** cross-turn resolved state, `correction_context`
- **tasks:** T-035, T-048
- **current_coverage:** **F5 is implemented, has cases (`tce-entitycorrection-001`, `tce-entityswap-001`), and is silently never invoked — `runner.py` hardcodes `correction_ctx = None`** **[B]**. Blueprint §A calls this the clearest example of the exact problem the blueprint exists to prevent
- **gap:** dead wiring
- **future:** blueprint §P step 0.2 — wire F5 end-to-end, plus the gate/dimension liveness check so this class of dead eval cannot recur unnoticed
- **source:** A (blueprint §A/§C.3/§P) + B

## PE-37 — Topic reset
- **CONVERSATION_STATE** · state hygiene
- **prevents:** a new subject silently dragging the previous filter/period
- component · deterministic
- **metric:** stale-state carry-over on reset turns
- `THRESHOLD_TO_CALIBRATE`; the multi-turn aggregate is defined precisely per blueprint §N as "fraction of multi-turn cases with zero gate violations across all turns", not a vague aggregate · P0 · **BLOCK**
- **trace:** cross-turn resolved triples
- **tasks:** T-034, T-049
- **current_coverage:** TCE topic-reset cases **[B]**, in the unwired suite
- **gap:** unwired; no production-side equivalent
- **future:** apply the same check to pilot traffic
- **source:** A (blueprint §B.1/§N)

## PE-38 — Session isolation
- **SAFETY** · multi-user boundary
- **prevents:** one pilot user seeing another's conversation or data
- operational + contract-test · deterministic (gates F3/F4)
- **metric:** cross-session leak occurrences
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `session_id`, sandbox trace
- **tasks:** T-042
- **current_coverage:** gates F3/F4 exist; SAFETY is the most mature category in the stack **[B]**
- **gap:** the pilot is the first genuinely multi-user context; single-user testing is not evidence
- **future:** a multi-session isolation test before pilot entry
- **source:** A (blueprint §D/§N) + C (multi-user requirement is a pilot-specific proposal)

## PE-39 — Auth boundary
- **SAFETY** · access control
- **prevents:** unauthenticated access to `/api/*`; `file://`-opened surfaces failing open
- contract-test · deterministic
- **metric:** unauthenticated `/api/*` responses that are not 401
- `HARD_INVARIANT` · P0 · **BLOCK**
- **trace:** server logs
- **tasks:** T-042
- **current_coverage:** every `/api/*` route requires `X-Ingesta-Token`, auto-injected into served pages; `file://` correctly 401s **[B]**
- **gap:** no eval row asserts it as a pilot precondition
- **future:** include in the pre-deployment check
- **source:** B

## PE-40 — Holdout non-contamination
- **SAFETY** · eval integrity
- **prevents:** pilot task authoring reconstructing holdout content from memory
- contract-test · deterministic
- **metric:** anti-leak check failures
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** n/a
- **tasks:** entire task bank
- **current_coverage:** `eval/benchmark/tests/test_holdout_not_leaked.py` — four real checks (no case files in holdout dirs, manifest has no semantic fields, whole-file forbidden-key scan, cross-source ID-reference grep), on top of physical isolation in a separate private repo **[B]**. **Unwired** (same `testpaths` exclusion) **[B]**
- **gap:** cheap, zero-LLM, and still not run on every change; blueprint §M says it "should never have been excluded from CI"
- **future:** blueprint §P step 0.1; extend the ID grep toward fuzzy phrase matching per §J
- **source:** A (blueprint §J/§M) + B

## PE-41 — Trace reconstructibility
- **INFRA** · observability · **blocking scope:** `PRODUCT` · **authority_type:** REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION
- **prevents:** a pilot that produces anecdotes instead of evidence; makes failure attribution (blueprint §D) impossible
- operational · deterministic
- **metric:** **analytically consequential** turns (per HB-10: turns that state a business fact, invoke a tool or SQL, or resolve an entity/metric/period) missing any `MUST_FOR_PILOT` field of the Pilot Trace Contract (§24). *(Changed in this revision: Draft 1 required a trace on every turn. The requirement is reconstructibility of answers that could be wrong, not universal logging; an untraced greeting causes no diagnosable harm. Two fields were **added** to the MUST set on source evidence — `span_type`, so retrieval steps are identifiable and the groundedness/relevance checks are computable at all, and `app_version`, without which pilot traffic cannot be compared before and after a change. `01_building_and_evaluating_data_agents.md` Lessons 4 and 6 **[S]**.)*
- `HARD_INVARIANT` (a consequential turn is traced or is not served) · P0 · **BLOCK/P**
- **trace:** all §24 `MUST_FOR_PILOT` fields, including `span_type` and `app_version`
- **tasks:** all
- **current_coverage:** `eval/benchmark`'s `turns.jsonl`/`events.jsonl` already approximate the shape **[B]**; `eval/alpha_eval_v1` captures tool calls, SQL, tokens, latency, termination reason, presentation pre/post **[B]**
- **gap:** no single standardized trace across benchmark and production; blueprint §K's explicit instruction is to standardize, **not** invent a fourth format
- **future:** one shape everywhere; the MUST/SHOULD split in §24 is this document's pilot-specific judgment **[C]**
- **source:** A (blueprint §K) + C

## PE-42 — Latency & cost baseline
- **INFRA** · operability
- **prevents:** arguing architecture tradeoffs without honest numbers
- operational · deterministic
- **metric:** p50/p95 latency split by tool-using vs not; tokens and cost per turn
- `BASELINE_RELATIVE` (measured on the task bank first, then compared) · P1 · **WARN**
- **trace:** `latency_ms_total`, `tool_calls[].latency_ms`, `tokens`
- **tasks:** all
- **current_coverage:** `Usage` has the right fields, `latency_ms` populated **[B]**; **the Track A adapter leaves token fields `None`, and no cost-per-query computation exists anywhere** **[B]**
- **gap:** token population + a pricing table
- **future:** blueprint §P step 0.4
- **source:** A (blueprint §C.8/§H) + B

## PE-43 — Error handling / graceful degradation
- **INFRA** · reliability
- **prevents:** a provider error or timeout becoming a plausible-sounding answer
- operational · deterministic
- **metric:** failed turns that produced a substantive answer instead of an explicit failure
- `ZERO_TOLERANCE` · P0 · **BLOCK**; the *rate* of runtime errors is separately `BASELINE_RELATIVE`/`THRESHOLD_TO_CALIBRATE` over rolling pilot traffic (blueprint §N: an operational metric, not a pre-release gate, since pre-release volume makes a 2% figure meaningless)
- **trace:** `retries[]`, `planner_decision`, `final_answer_text`
- **tasks:** T-044, T-050
- **current_coverage:** error-rate fields exist **[B]**; no eval asserts degradation *behavior*
- **gap:** no fault-injection eval
- **future:** inject provider/tool faults and assert the explicit-failure response shape
- **source:** A (blueprint §H/N) + C

## PE-44 — Gate/dimension liveness
- **INFRA** · anti-dead-eval
- **prevents:** the F5 class of failure — infrastructure that looks covered but never fires
- contract-test · deterministic
- **metric:** gates/dimensions exercised by at least one task that never return a non-`None` verdict across the run
- `ZERO_TOLERANCE` · P0 · **BLOCK**
- **trace:** `gate_results`, `dimension_scores`
- **tasks:** whole bank
- **current_coverage:** **none** — this check does not exist; it is the blueprint's own recommended structural safeguard **[B]** (§C.3/§H)
- **gap:** the whole check
- **future:** blueprint §P step 0.2, run as its own check
- **source:** A (blueprint §C.3/§H)

## PE-45 — JLL v2 freshness & coverage honesty
- **taxonomy_dimension:** DATA (+ INFRA secondary — the Analyst-wiring half) · **pilot_operational_requirement:** `external_gate_closure` · **authority_type:** REPO-EVIDENCE + TOESCA-DESIGN-DECISION + OPEN-DECISION · **blocking scope:** `CAPABILITY`
- *(Re-filed in this revision. Draft 1 had `PILOT_OPS`, which is no longer a legal value. The failure prevented is a wrong or overclaimed business fact, hence DATA; the external-gate obligation now lives in `pilot_operational_requirement`. The substance of the row below — including all three JLL claims — is unchanged.)*
- **capability:** rent roll / recaudación / cartera availability and freshness
- **prevents:** claiming coverage the Analyst cannot query; answering pre-v2 data with v2 semantics; a catalog/schema mismatch
- contract-test + human · deterministic (wiring & schema) + `HUMAN_ACCEPTANCE_REQUIRED` (gate items)
- **evidence:** gate-manifest state; production `schema_version`; whether `tools/analyst_runtime/` actually reaches the v2 views; `fecha_corte` convention disclosed
- **metric:** (a) gate items still `pending`; (b) capabilities claimed but not wired; (c) rent-roll answers without a disclosed cut-off convention
- `HUMAN_ACCEPTANCE_REQUIRED` + `ZERO_TOLERANCE` on overclaimed coverage · P0 · **BLOCK**
- **trace:** `tool_calls[].provenance.source-as-of`, `resolved_period`, `final_answer_text`
- **tasks:** T-018, T-030, T-031, T-050
- **current_coverage — the triple distinction, each claim verified separately [B]:**
  1. **Implemented and tested in source:** migrations 085–091 present (091 is the highest in the repo); `tools/jll_planilla_tools.py`, `tools/db/ingest_jll_planilla.py`, `tools/db/derive_er_jll_v2.py`, `tools/db/er_reglas.py`, `tools/db/repo_jll_v2.py`, `tools/db/repo_rent_roll.py`; ~70 new test functions plus 4 schema invariants; upload wired into the live ingesta UI with format auto-detection.
  2. **Gated off production:** production remains on schema `84`; 085–091 **not applied**. A separate readiness branch carries preflight gating, hermetic Playwright E2E, and a cutover runbook, plus a **separable catalog-cutover commit that must be applied only at cutover and requires schema ≥ 91**. Its external gate manifest has **all 8 items `pending` with null evidence** (`archivo_oficial_jll`, `fecha_corte_rent_roll_convencion`, `apo3001_seguro`, `tratamiento_ug`, `mappings_pendientes`, `apo3001_ing_taipei_vs_otros`, `reconciliacion_2026_06`, `contribuciones_aceptacion`). The preflight only reads that manifest and never writes it.
  3. **Not Analyst-queryable:** zero code changes in `tools/analyst_runtime/` or `web/analyst.html` are associated with the pipeline — the data is populated in sandbox but **the Analyst cannot query the new tables or views today**. A "not wired up yet" state, not a bug.
- **gap:** all three of: 8 pending business/external gate items; production cutover; Analyst wiring. Any pilot claim of rent-roll capability requires all three closed together with the catalog cutover
- **future:** either close all three (§27 JL-2) or ship without JLL-v2-dependent capabilities and refuse those questions explicitly (§27 JL-3)
- **source:** B (all three claims) + A (A1.5 §K for the temporal/`latest` rule) + C (the pilot requirement)

## PE-46 — Deterministic report reproducibility
- **taxonomy_dimension:** INFRA (+ RESULT_VALIDATION secondary — validation must block rendering) · **pilot_operational_requirement:** `report_cutover` · **authority_type:** REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION · **blocking scope:** `CAPABILITY`
- *(Re-filed from `PILOT_OPS`. An LLM appearing in a path declared LLM-free, and identical inputs producing different bytes, are properties of the generation system.)*
- **capability:** Informe de Vacancia / Recaudación / Ingresos
- **prevents:** a "deterministic" report that isn't — LLM in the path, or non-reproducible output
- contract-test · deterministic
- **metric:** (a) model-API calls in the generation path; (b) byte-level diff across repeated runs on identical inputs
- `HARD_INVARIANT` on both · P0 **if reports ship**; the reports themselves are P2 (the pilot may launch chat-only) · **BLOCK if shipped**
- **trace:** report generation log; no model call permitted
- **tasks:** T-046, T-047
- **current_coverage:** the pattern exists in `scripts/build_factsheet.py` (100% SQL-driven, no LLM) **[B]**; the Reports Hub itself is **approved but not implemented** **[B]**
- **gap:** the three reports do not exist. Blockers per report **[B]**: Vacancia is blocked on the open UG business decision (migration 090 makes UG visible, doesn't resolve it); Recaudación must **not** publish a `tasa_recaudacion` — no invoice/document linkage exists to make it a real cohort rate; Ingresos is the least advanced, a data-quality improvement to an existing path
- **future:** build to the ROADMAP shape (generator → governed dataset/SQL → validation → HTML), with validation blocking rendering rather than rendering a caveat
- **source:** B (ROADMAP + CURRENT_STATE) + C (the reproducibility bar)

## PE-47 — Report-vs-chat number parity
- **taxonomy_dimension:** SEMANTIC (+ RESULT_VALIDATION secondary) · **pilot_operational_requirement:** `report_cutover` · **authority_type:** REPO-EVIDENCE · **blocking scope:** `CAPABILITY`
- *(Re-filed from `PILOT_OPS`. Two implementations of one metric is a breach of single semantic authority, A1.5 §F.)*
- **capability:** single metrics implementation
- **prevents:** the report and the chat disagreeing on the same metric/entity/period — the fastest way to destroy trust in both
- contract-test · deterministic
- **metric:** divergences for the same (metric, entity, period)
- `ZERO_TOLERANCE` · P0 **if reports ship** · **BLOCK if shipped**
- **trace:** `resolved_metric`, `citations`; report generation log
- **tasks:** T-046, T-047
- **current_coverage:** the shared-contract intent is stated (`semantic/`, `tools/datasets/` shared by Analyst and report generators) **[B]**; sharing **not yet built**
- **gap:** nothing prevents a second metrics implementation today
- **future:** the Analyst invokes the *same* generator (e.g. `generate_vacancy_report(scope, period)`), never a parallel LLM path
- **source:** B (ROADMAP) + A (A1.5 §F single authority)

## PE-48 — Feedback capture & triage loop
- **taxonomy_dimension:** INFRA · **pilot_operational_requirement:** `weekly_triage` · **authority_type:** REPO-EVIDENCE + SOURCE-DERIVED + TOESCA-DESIGN-DECISION · **blocking scope:** `PRODUCT`
- *(Re-filed from `PILOT_OPS`. The gradeable half is "does the flag carry the trace" — observability plumbing. The human triage half is not a failure mode and is now an operational requirement. Independently supported: production failures becoming eval cases is stated in `07_anthropic_agent_engineering_context_tools_evals.md` §3 and its checklist, and in `05_openai_api_agents_consolidated_knowledge.md` §17.2 step 4 **[S]**.)*
- **capability:** production → eval loop
- **prevents:** a pilot that generates anecdotes rather than regression cases
- operational + human
- **evidence:** flag captures the **trace**, not just the text; each flag triaged to exactly one blueprint §D class; reproducible failures become dev-set cases with SQL `ground_truth_refs`
- **metric:** flags with a complete trace; flags triaged within the review cycle; classified reproducible failures promoted to cases
- `HARD_INVARIANT` (trace attached) + `HUMAN_ACCEPTANCE_REQUIRED` (triage) · P0 · **BLOCK**
- **trace:** full §24 MUST set, linked to the flag
- **tasks:** all
- **current_coverage:** real shipped surface — `/pilot-feedback`, `/pilot-control`, message-level feedback, feedback-report markdown export **[B]**
- **gap:** **the production→eval loop does not exist** **[B]** (blueprint §C.6/§J: `eval/alpha_eval_v1` and the presentation holdout are one-shot artifacts, not renewable pipelines). Also: `eval/alpha_eval_v1`'s free-text `ground_truth`/`expected_behavior` fields must stop being treated as gradeable (blueprint §O)
- **future:** a **manual** weekly loop is acceptable for pilot (§25 FB-5); automation is P2; per blueprint §J the regression set is "all dev-set cases run on every change", not a separate artifact
- **source:** A (blueprint §J/§L/§O) + B + C

## PE-49 — Operator escalation & stop mechanism
- **taxonomy_dimension:** SAFETY · **pilot_operational_requirement:** `operator_governance` · **authority_type:** TOESCA-DESIGN-DECISION + SOURCE-DERIVED · **blocking scope:** `PRODUCT`
- *(Re-filed from `PILOT_OPS`, and the most debatable of the five remappings — see the taxonomy section above. The failure prevented is a real one, "the system keeps serving after a stop condition has been met", which is a safety-control failure; but the row's substance is governance, carried by `pilot_operational_requirement`. Supported as a practice by `02_a_practical_guide_to_building_agents.pdf` p. 31, where human intervention triggers on failure thresholds and high-risk situations, and by `05_...md` §13 "Human control" **[S]** — neither of which prescribes Toesca's specific arrangement.)*
- **capability:** pilot governance
- **prevents:** a pilot that keeps running after a stop condition is met
- human
- **evidence:** named operator; named users; documented rollback executable within one working session; written scope-of-use limits for users; weekly review record
- **metric:** stop conditions (§30) detected and acted on
- `HUMAN_ACCEPTANCE_REQUIRED` · P0 · **BLOCK**
- **trace:** incident record referencing `session_id`/`turn_id`
- **tasks:** n/a
- **current_coverage:** `/pilot-control` exists as a surface **[B]**; the governance itself is not defined anywhere
- **gap:** operator role, user list, rollback runbook, scope-of-use statement, review cadence — none exist
- **future:** §28 + §30 of the standard, signed off before entry (HB-12)
- **source:** C

## PE-50 — Plan quality & justified replanning
- **taxonomy_dimension:** PLANNING · **blocking scope:** — · **authority_type:** SOURCE-DERIVED + TOESCA-DESIGN-DECISION
- **capability:** multi-step investigation planning
- **prevents:** a plan that cannot achieve the goal with the tools available, and — more importantly for Toesca — a **replan with no recorded trigger**, which is how a multi-step investigation quietly changes what question it is answering
- **why this row is new:** PLANNING had only PE-17 (clarify-vs-answer) and PE-18 (causal depth). Neither evaluates the plan itself. The sources treat plan quality and plan adherence as first-class, separately-rubricked failure surfaces, and Toesca's §17 "why" family is precisely where they bite
- trajectory · judge (plan-quality style rubric) + deterministic (a replan event carries a recorded trigger)
- **evidence:** structured plan steps in the trace (`span_type=planning`), replan events with triggers, executed steps
- **metric:** (a) replans with no recorded trigger — deterministic; (b) plan-quality and plan-adherence scores — judge
- `HARD_INVARIANT` for (a) once plans are structured in the trace; `THRESHOLD_TO_CALIBRATE` for (b), **monitored, never blocking, until judge variance is measured** (judge policy, P15) · P1 · **WARN**
- **trace:** `planner_decision`, `span_type=planning`, `tool_calls[]`, `retries[]`
- **representative_tasks:** T-039, T-040, T-041, T-044, T-050
- **current_coverage:** `investigation_quality` judge dimension exists **[B]**; no plan structure is recorded in the trace today, so neither leg is currently computable **[B]**
- **gap:** plans are not emitted as structured trace objects; no replan-trigger field exists
- **proposed_future_implementation:** structured plan steps with goal/precondition/postcondition per step (standard §11 PQ-1), a `replan{trigger}` trace event, then the judge rubric. **Not scheduled here.** Note the explicit non-goal: plan quality is judged against the goal and the available tools, **never against a reference plan** (P5, PQ-3)
- **source_rationale:** **S** — `04_cs329t_knowledge_pack_all.md`, Agent GPA slides 13 (Plan Quality rubric: every step justified, feasible with the tools provided, replans presented with explicit rationale) and 17 (Plan Adherence judged step-by-step, omissions counting as failures regardless of final-answer quality); `01_building_and_evaluating_data_agents.md` Lessons 5–6, where making plan steps explicit measurably improved adherence; `07_anthropic_agent_engineering_context_tools_evals.md` §3 ("Prefer grading outcomes over enforcing one exact reasoning path"), which is why PE-50 grades justification rather than path shape. Severity, non-blocking status, and Toesca's specific trace shape are **C**

---

## Coverage check against the canonical taxonomy

| Taxonomy class | Rows |
|---|---|
| DATA | PE-01, PE-02, PE-03, PE-04, PE-45 |
| SEMANTIC | PE-05, PE-06, PE-07, PE-08, PE-47 |
| ENTITY | PE-09, PE-10 |
| METRIC | PE-11, PE-12 |
| PERIOD | PE-13, PE-14 |
| CONTEXT | PE-15, PE-16 |
| PLANNING | PE-17, PE-18, PE-50 |
| TOOL_SELECTION | PE-19, PE-21 |
| TOOL_ARGUMENTS | PE-20 |
| SQL | PE-22, PE-23, PE-24 |
| RESULT_VALIDATION | PE-25, PE-26 (+ PE-46, PE-47 secondary) |
| TRAJECTORY | PE-27, PE-28 |
| SYNTHESIS | PE-29, PE-30, PE-31, PE-32, PE-33, PE-34, PE-35 |
| CONVERSATION_STATE | PE-36, PE-37 |
| SAFETY | PE-38, PE-39, PE-40, PE-49 |
| INFRA | PE-41, PE-42, PE-43, PE-44, PE-46, PE-48 (+ PE-45 secondary) |

**All 16 canonical classes are covered, and `taxonomy_dimension` now contains canonical
values only.** No class is renamed, split, merged, or replaced. The extensions used
(splitting `tool_correctness` into PE-19/PE-20; standalone SQL correctness at PE-23;
standalone unit correctness at PE-06) are the blueprint's **own** justified extensions (§F,
§O, §P step 1.1), cited as such rather than re-derived here — and PE-19/PE-20 are
independently corroborated by the external sources.

### Operational requirements (orthogonal to the taxonomy)

| Requirement | Rows | Owner |
|---|---|---|
| `operator_governance` | PE-49 | Named pilot operator (§28 OP-1) |
| `weekly_triage` | PE-48 | Named pilot operator (§28 OP-3) |
| `external_gate_closure` | PE-45 | Named human, currently unassigned (§32 OD-11) |
| `report_cutover` | PE-46, PE-47 | Product + eng (§32 OD-15) |

### Row count

**49 → 50.** No row was removed. One row was added (PE-50), five were re-filed out of
`PILOT_OPS` into canonical classes, and three (PE-25, PE-27, PE-41) changed substance on
source evidence. The five re-filed rows kept their content, evidence, and gaps unchanged;
only their classification and their operational-requirement field changed.

## Sequencing note

Nothing in this matrix is scheduled by this document. Where an item corresponds to a
blueprint implementation step, the step is named (§P step 0.1–0.5, 1.1–1.3, 2.1–2.2, 3.1).
Those are a **forward plan**, not completed work.
