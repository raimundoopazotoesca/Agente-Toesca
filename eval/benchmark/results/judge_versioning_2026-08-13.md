# Judge versioning — three independent axes

A calibration result is only reproducible, and only comparable to another
result, if all three of the following are pinned and reported together.
They vary independently and must never be collapsed into a single
"judge version" label.

1. **Rubric content version** — `rubric_version` in
   `eval/benchmark/graders/rubric.yaml`. What the scoring criteria,
   anchors, and gate definitions actually say. Changing wording, adding a
   carve-out, narrowing a gate — all of that bumps this.
2. **Judge implementation version** — `JUDGE_IMPL_VERSION` in
   `eval/benchmark/graders/judge.py`. How the rubric gets turned into a
   prompt, how output is validated, the retry policy, and any
   deterministic code-level safety nets (e.g.
   `_enforce_tool_correctness_policy`). This can change with the rubric
   held constant (e.g. the empty-justification tolerance fix), or stay
   fixed while the rubric changes.
3. **Judge model/provider** — never hardcoded anywhere in `judge.py`;
   always passed as the `model` argument to `run_judge()`, paired with
   whatever `chat_fn` the caller constructs for a given provider. Two runs
   with identical rubric + implementation but a different model are
   **not** the same judge, and their scores are not directly comparable
   without re-establishing calibration.

`JudgeResult` now stamps all three (`rubric_version`, `judge_impl_version`,
`judge_model`) on every result, success or failure, so a persisted run
self-identifies what produced it without relying on file naming or memory.

## Calibration history, pinned per axis

| Round | Rubric version | Judge impl version | Model/provider | Result file |
|---|---|---|---|---|
| 1 | 1.0 (initial) | 1.0 (initial `judge.py`) | mistral-large-latest / Mistral | `judge_v1_l3l5_pilot_2026-08-13.jsonl` |
| 2 | 1.1 (not_applicable policy, F1 patterns a/b, analytical_quality cap, grounding/hallucination non-evidence rule) | 1.1 | mistral-large-latest / Mistral | *(Codex's round, referenced in `human_vs_judge_v1_1_comparison_2026-08-13.md`; raw judge output not separately persisted from that round)* |
| 3 | 1.2 (F1 retrieval-failure carve-out, C4 rewrite v1, clarification_judgment scope, tool_correctness N/A rule) | 1.2.0 (added `_enforce_tool_correctness_policy`, empty-justification tolerance) | mistral-large-latest / Mistral | `judge_run_v1_2_calibration_2026-08-13.jsonl` |
| 4 (this pass) | 1.2, **C4 narrowed** (requires BOTH conditional framing AND explicit evidence-gap acknowledgment for the hedge exception; everything else from round 3 unchanged) | 1.2.0 (unchanged) | mistral-large-latest / Mistral | not yet re-run — see below |

Round 4's rubric change was verified with synthetic unit tests only
(`test_rubric_c4_requires_both_conditional_framing_and_evidence_gap_for_exception`,
`test_rubric_c4_still_fires_on_unqualified_causal_conclusion`), per
explicit instruction not to iterate live calibration against the same 10
responses again after confirming the regression. **The rubric_version
string in `rubric.yaml` was not bumped past "1.2" for this narrowing** —
it's a fix to the same 1.2 content, not a new content version; if this
becomes confusing in practice, promote it to "1.2.1" at the next commit
that touches the rubric.

## Known residual gap: classified as judge-model limitation, not rubric gap

`tae-l4-001`/track_b (Strip Machalí divestment diagnosis) has produced an
F1 false negative across all three live calibration rounds — it
transforms a confirmed `vigente_hasta` date into an unestablished "the
lease ended and wasn't renewed" claim, which is the exact
fact-transformation pattern F1 has described in detail (with a
near-identical conceptual example) since rubric v1.1. The rule exists;
`mistral-large-latest` isn't applying it consistently to this response's
specific phrasing.

Per instruction, this is recorded as a **judge-model limitation
candidate**, not a new rubric gap — no case-specific rule was added for
it. The proposed next step (not executed) is re-running this same
calibration with a different frontier judge model to see whether the
miss is model-specific or a genuine rubric-clarity problem that would
recur regardless of which model judges it.
