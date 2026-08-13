# Human vs. Rubric Judge v1 — calibration comparison

Date: 2026-08-13. Judge version: v1 (pre-calibration, commit `63ddd21`).
Reviewer: human, blind (`eval/benchmark/results/blind_calibration_form_2026-08-13.html`).
Source data: `human_calibration_answers_v1_2026-08-13.json` (this reviewer's raw
answers) x `blind_answer_key_v1_2026-08-13.json` (judge's hidden scores for
the same 10 turns, unblinded now that this round is complete).

This is a **record of one calibration round**, not a specification. It is
never read by `judge.py` or embedded in the judge's prompt as a few-shot —
see `graders/judge.py` and `graders/rubric.yaml` for the actual rubric that
resulted from acting on these findings (dated after this file).

## Headline finding: systematic grade inflation

| Response | Case/track | Human `overall_trust` | Judge dim. avg | Gap |
|---|---|---|---|---|
| 2 | tae-l4-001/B | 2 | 4.00 | **+2.0** |
| 9 | tae-l4-002/B | 0 | 1.33 | +1.3 |
| 8 | tae-l5-003/B | 2 | 3.14 | +1.1 |
| 3 | tae-l5-002/B | 3 | 3.86 | +0.9 |
| 10 | tae-l4-003/B | 2 | 2.83 | +0.8 |
| 6 | tae-l4-001/A | 1 | 1.50 | +0.5 |
| 1, 5 | tae-l3-001/A, tae-l4-002/A | 0 | 0.00 | 0 |

Every comparable case has judge ≥ human; never the reverse across 7 non-tied
cases.

## Per-dimension agreement

| Dimension | n | mean \|diff\| | exact | ±1 | N/A mismatches (human scored, judge N/A) |
|---|---|---|---|---|---|
| clarification_judgment | 8 | 0.12 | 88% | 100% | 0 |
| output_usefulness | 8 | 0.50 | 50% | 100% | 0 |
| analytical_quality | 5 | 1.00 | 20% | 80% | 3 |
| investigation_quality | 5 | 0.80 | 40% | 80% | 3 |
| hallucination | 5 | 1.20 | 20% | 60% | 3 |
| grounding | 5 | 1.20 | 0% | 80% | 0 |
| tool_correctness | 2 | 1.00 | 0% | 100% | 6 |

## F1 / C4 gate agreement — 6/8 exact, both disagreements are under-triggers

| Response | F1 | C4 |
|---|---|---|
| 1, 3, 5, 6, 10 | match (false/false) | match (false/false) |
| 2 | **disagree** — human true, judge false | **disagree** — human true, judge false |
| 8 | **disagree** — human true, judge false | match (false/false) |
| 9 | match (true/true) | match (true/true) |

## Structural classifications

Both `model_non_answer` (Respuesta 4) and `infra_failure` (Respuesta 7)
confirmed correct by the human reviewer.

## Root causes identified

1. **`not_applicable` used as an escape hatch on clarified/declined
   responses.** All 3 Track A clarify turns had `analytical_quality`,
   `hallucination`, `investigation_quality`, `tool_correctness` marked N/A by
   the judge; the human scored them anyway (0 for the quality dimensions, 4
   for hallucination), reasoning that declining to analyze is itself an
   analytical-quality failure, not an inapplicable dimension.
2. **Grounding/hallucination read fluency as evidence.** The worst-inflated
   case (Respuesta 2) is confident, well-organized prose containing an
   unsupported causal leap and a category error (querying an *activo* as if
   it were an *arrendatario*) — the judge scored it near-perfect.
3. **F1 under-fires on two patterns**: (a) an unsourced external citation
   presented as fact, (b) a supported fact transformed into a more specific,
   unsupported fact (the general shape: "asset stopped being active" →
   "lease ended, wasn't renewed" — a claim the queried field never made).
4. **`tool_correctness` has too few comparable pairs (n=2)** to draw a firm
   conclusion beyond "the N/A-gating problem is the same root cause as #1."

## Recommendations acted on in the v1.1 rubric pass

See `graders/rubric.yaml` and `graders/judge.py` for the actual changes.
Summary: not_applicable semantics now specified per-dimension rather than
following response_mode; explicit "fluency is not evidence" rule on
grounding/hallucination; F1 broadened to unsourced-external-citation and
fact-transformation patterns (as general principles, not tied to any
specific case); tool_correctness now applies whenever tool calls exist,
regardless of `tool_requirements`, and explicitly does not reward query
count; analytical_quality capped at 1 when the main driver/conclusion
contradicts ground truth, regardless of structure quality;
investigation_quality decoupled from tool-call count in favor of whether the
right evidence was found and identifiers correctly resolved.
