# Toesca Analyst LLM Judge Policy v1

Status: normative policy for the existing benchmark judge. This document
governs judge use; it does not change the rubric, judge prompt, grader,
runtime, benchmark cases, gates, or database.

## Authority and score ownership

The deterministic grader and gates are authoritative for every verdict they
produce. **The judge must never re-score or override a deterministic verdict
already produced for a turn.** Deterministic evidence may constrain or correct
judge output; judge output must never constrain or correct deterministic
evidence. This includes the existing deterministic
`_enforce_tool_correctness_policy` guard.

Facts that can be resolved deterministically from the pinned snapshot or SQL
ground truth must never rely solely on judge scoring. In particular, the judge
must not be used to re-litigate a deterministic factual score, completeness,
or a deterministic gate verdict.

The judge owns these dimensions on every eligible turn:

- `analytical_quality`
- `grounding`
- `hallucination`
- `clarification_judgment`
- `investigation_quality`
- `output_usefulness`

`tool_correctness` is conditionally judge-owned. When a case declares
`tool_requirements`, the deterministic grader scores `tool_correctness`; the
judge must not score it. Only when the case has no `tool_requirements` may
`tool_correctness` reach the judge, and then it remains subject to the existing
deterministic enforcement/override guard. That guard may correct the judge from
structural evidence; the judge may not reverse it.

The judge owns these gates:

- `F1_fabrication` (fabrication)
- `C4_unsupported_causality` (unsupported causality)
- `C5_forbidden_claim` (forbidden claim)

`conversational_quality` is not judge territory. When deterministic scoring
cannot compute it, it remains unscored; the judge must not silently fill it.
This is the current narrow coverage boundary, not an invitation to expand judge
scope.

## Failure handling and audit record

There is no silent judge fallback or default score. Missing, malformed, or
invalid judge output must remain an explicit judge failure with the affected
judge verdicts unscored, rather than being guessed, passed, or default-scored.

Every persisted judge result must record all three independent version axes:

- the judge model string;
- the rubric version; and
- the judge implementation version.

Benchmark comparisons must not silently compare runs with different judge
models. A differing judge model is allowed only when judge-model change is the
explicit comparison variable; otherwise the comparison must be rejected or
reported as non-comparable.

## Calibration, variance, and disagreement

Any judge-model change or rubric-version change requires fresh human-vs-judge
calibration before release use. Calibration is a release prerequisite, not an
informal follow-up.

Repeated-run variance has not yet been measured by this policy. Before any
judge-based Reliability Core metric becomes a hard release gate, run the same
set at least N>=3 times under the intended settings and measure variance by
dimension. A suggested starting tolerance of +/-0.5 on the 0--4 scale is
provisional only; it is not an established or measured threshold.

When human and judge disagree, triage case or rubric ambiguity first. Only
after ambiguity is ruled out should the disagreement be treated as a judge
calibration problem and used to adjust calibration or rubric wording.

## Scope control

This policy preserves the current hybrid split: deterministic mechanisms decide
deterministically resolvable facts and already-scored verdicts; the judge
evaluates only its declared residual dimensions and gates. Any future change to
that split requires explicit review, updated policy coverage, and calibration;
it must not be introduced as a silent judge fallback.
