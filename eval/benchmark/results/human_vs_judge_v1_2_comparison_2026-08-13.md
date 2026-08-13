# Human vs. Rubric Judge v1.2 — third calibration pass

Date: 2026-08-13. Judge: post-surgical-pass commit (F1 retrieval-failure
carve-out, C4 epistemic-commitment rewrite, clarification_judgment scoped
to initial decision, tool_correctness deterministic N/A safety net).
Provider/model: `mistral / mistral-large-latest`, same as every prior round.
Same 10 blind responses, same ground truth, same SQL/results, same human
answers (`human_calibration_answers_v1_2026-08-13.json`) -- only the judge
changed. Raw run: `judge_run_v1_2_calibration_2026-08-13.jsonl`.

**Recommendation: do not freeze yet.** See "Why not frozen" below --
found a real regression on C4, not just leftover noise.

## Per-dimension metrics, v1 -> v1.1 -> v1.2

| Dimension | v1 MAD/exact/±1/NA | v1.1 MAD/exact/±1/NA | v1.2 MAD/exact/±1/NA | v1.2 signed |
|---|---|---|---|---|
| analytical_quality | 1.000/20%/80%/3 | 0.500/50%/100%/0 | **0.375/62%/100%/0** | +0.125 |
| grounding | 1.200/0%/80%/0 | 0.800/40%/80%/0 | **0.600/60%/80%/0** | +0.200 |
| hallucination | 1.200/20%/60%/3 | 0.500/62%/88%/0 | 0.625/50%/88%/0 | +0.625 |
| clarification_judgment | 0.125/88%/100%/0 | 0.625/62%/88%/0 | **0.375/62%/100%/0** | +0.125 |
| investigation_quality | 0.800/40%/80%/3 | 0.625/38%/100%/0 | **0.500/50%/100%/0** | +0.000 |
| output_usefulness | 0.500/50%/100%/0 | 0.750/25%/100%/0 | 0.625/38%/100%/0 | +0.625 |
| tool_correctness | 1.000/0%/100%/6 | 0.333/83%/83%/2 | **0.250/75%/100%/0** | +0.250 |

Bold = improved vs. both prior rounds. `investigation_quality` is now
perfectly unbiased (signed mean 0.000). **N/A mismatches are now zero on
every dimension** -- the not_applicable escape-hatch problem from v1 is
fully resolved.

**Overall signed bias (judge − human) across 53 numeric pairs: +0.283**
(18 positive, 5 negative, 30 exact). This is worse than v1.1's +0.196 —
see below, it's concentrated in specific dimensions, not spread evenly.

## Gates

| Gate | v1 exact/FP/FN | v1.1 exact/FP/FN | v1.2 exact/FP/FN |
|---|---|---|---|
| F1_fabrication | 6/8, 0, 2 | 6/8, 1, 1 | **7/8, 0, 1** |
| C4_unsupported_causality | 7/8, 0, 1 | 6/8, 1, 1 | **5/8, 2, 1** |

F1 improved (fewer false negatives, no false positives). **C4 got worse**:
2 new false positives appeared that were not present in v1 or v1.1.

## Divergences > 1

Only 2, both on the same response:

- **Respuesta 2** (`tae-l4-001`/track_b): `grounding` human=2 judge=4
  (diff 2); `hallucination` human=2 judge=4 (diff 2).

No other response has any dimension diverging by more than 1 point --
a real, substantial improvement over v1.1 (which had divergences on 2
responses across 3 dimensions).

## Why not frozen: two concrete problems

### 1. The Respuesta 2 false negative persists (F1, and by extension grounding/hallucination)

`tae-l4-001`/track_b (Strip Machalí) is still scored near-perfect
(grounding=4, hallucination=4, F1=false) despite the human flagging the
same issue three rounds running: the response transforms
`vigente_hasta='2025-08'` into "el contrato terminó y no fue renovado" --
exactly the fact-transformation pattern the rubric has described in detail
since v1.1, now with an even more explicit F1 pattern (b) and conceptual
example. The rubric text says the right thing; the judge model isn't
reliably applying it to this response's specific phrasing. This is a
prompt-following limitation of `mistral-large-latest` on this input, not
a rubric-wording gap I can fix with more rubric text without risking
overfitting to this one response (explicitly out of scope per your
instructions).

### 2. C4 over-corrected: 2 new false positives on properly-hedged hypotheses

- **Respuesta 8** (`tae-l5-003`/track_b, Apo review): human explicitly
  did not mark `unsupported_causality` because *"las relaciones causales
  posteriores están mayormente condicionadas ('si', 'podría')"* -- the
  judge now triggers C4 anyway.
- **Respuesta 10** (`tae-l4-003`/track_b, TIR): human explicitly did not
  mark it because *"las hipótesis operacionales están calificadas, no las
  considero causalidad afirmada"* -- the judge now triggers C4 anyway.

Both are cases where the response hedges appropriately and the human
credited that. My rubric edit for "a hedged-sounding explanation that
quietly leans on an unproven event still counts as C4" appears to have
made the judge trigger-happy on **any** conditional language near an
uncertain claim, not just the narrow "hedging while still treating the
unproven event as real" pattern it was meant to catch. This is a real
regression, not calibration noise -- C4 exact agreement dropped from 6/8
(v1.1) to 5/8 (v1.2), and both new misses are false positives on exactly
the behavior the rubric is supposed to protect (appropriately qualified
hypotheses).

### What is genuinely ready

- `not_applicable` policy: fully fixed, zero mismatches across all 7
  dimensions on all 8 comparable responses.
- `clarification_judgment`: scoping to the initial decision worked --
  Respuesta 6's earlier judge=2/human=1 gap (contaminated by post-decision
  execution quality) is now judge=0/human=1, much closer, and no other
  response shows contamination from downstream execution problems.
- `tool_correctness`: N/A mismatches eliminated (was 6, now 0); MAD
  improved to 0.250, the best of any dimension.
- F1 improved on balance (no new false positives, one fewer false
  negative than v1.1).
- Every dimension is within ±1 agreement on 80-100% of pairs; only one
  response has any divergence greater than 1.

## Recommendation

Do not freeze v1.2. Two issues remain, both real rather than noise:
1. The persistent F1 false negative on the fact-transformation pattern
   (same response, three rounds).
2. The new C4 over-triggering on hedged hypotheses (a regression this
   round introduced).

Given your instruction not to over-fit to these 10 responses and to
prefer "good enough" over perfect match, my read is that (2) is the more
urgent fix -- it's a clear regression with a identifiable general cause
(the "hedged-sounding but leans on an unproven event" language is too
broad), not a hard residual disagreement like (1). A narrow walk-back of
that specific C4 addition (tightening it back toward "only when the
response actually treats the unproven event as established," not "any
hedge near an uncertain claim") is a plausible small next step, but that
is a decision for you, not something I've applied -- per your
instruction, I'm stopping here and reporting.
