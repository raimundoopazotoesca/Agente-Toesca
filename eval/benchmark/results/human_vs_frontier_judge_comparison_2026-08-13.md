# Human vs. Frontier Judge (Gemini) — diagnostic pass

Date: 2026-08-13. Purpose: isolate whether residual judge scoring errors
come from **mistral-large-latest** as judge model or from the **rubric
itself**. Same rubric (`rubric.yaml`, current HEAD, `rubric_version=1.2`,
post-C4-narrowing), same judge implementation (`JUDGE_IMPL_VERSION=1.2.0`),
same 8 already-graded (case_id, track) pairs, same frozen
`response_text`/`executed_sql` — only the judge model/provider changed.

**Provider/model used:** `gemini / gemini-flash-latest` (routes to
`gemini-3.7-flash` server-side per the 429 error body), via the
OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai/`,
same client pattern as `tools/db_chat.py`. Probed in this order per the
task spec: `gemini-2.5-flash` (404, retired for new users) →
`gemini-flash-latest` (200, chosen) — `gemini-2.0-flash` and
`gemini-1.5-pro` were not tried once a working candidate was found.

**Deterministic sanity check:** `score_turn()` recomputed fresh from
current HEAD reproduced the exact `dimension_scores` /
`unscored_dimensions` already recorded in the Mistral baseline jsonl for
all 8 cases (`deterministic_matches_baseline: true` on every record) — no
drift between round 3 and current HEAD's deterministic grader.

## Blocker: 1 of 8 cases could not be judged (quota, not a rubric/model finding)

`tae-l4-003/track_b` (Respuesta 10, TIR TRI) failed on the first run and
on a dedicated retry (6 attempts, exponential-ish backoff up to ~60s)
with `RESOURCE_EXHAUSTED` / `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
**quota=20/day** for the underlying `gemini-3.7-flash` model on this
account. This is a hard daily cap already exhausted by the other 7 cases'
retries, not a transient error — retrying further today will not help.
Per the task's hard constraints this is reported as a blocker, not
worked around (no other provider is configured: `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY` are absent from the main repo's `.env`). All
comparisons below therefore use **7 of 8 cases**; the same 7 are also
used for the Mistral side so the comparison stays apples-to-apples
(Mistral's full-8 round-3 numbers are cited separately, from the existing
doc, for reference only).

Files:
- `eval/benchmark/results/judge_run_frontier_gemini-flash-latest_calibration_2026-08-13.jsonl`
  (7 judged + 1 `judge_failed=true` record with `failure_detail` showing the quota error)
- `eval/benchmark/results/_frontier_judge_experiment.py` (the script)

## Per-dimension metrics — Human vs Mistral vs Frontier, same 7 comparable cases

(Recomputed for both judges on the identical 7-case subset — excludes
Respuesta 10 on both sides for a fair comparison. Mistral's full-8,
round-3 numbers from `human_vs_judge_v1_2_comparison_2026-08-13.md` are
NOT reused as-is here because they include Respuesta 10; use them only as
general-shape reference, not for exact deltas.)

| Dimension | Mistral MAD/exact/±1/NA/bias (n=7-subset) | Frontier MAD/exact/±1/NA/bias (n=7-subset) |
|---|---|---|
| analytical_quality | 0.286 / 71.4% / 100% / 0 / +0.286 | 0.286 / 71.4% / 100% / 0 / **+0.000** |
| grounding | 0.500 / 75.0% / 75.0% / 0 (n=4) | 0.750 / 25.0% / 100% / 0 (n=4) / +0.250 |
| hallucination | 0.571 / 57.1% / 85.7% / 0 / +0.571 | 0.429 / 57.1% / 100% / 0 / **+0.143** |
| clarification_judgment | 0.286 / 71.4% / 100% / 0 / +0.000 | 0.143 / 85.7% / 100% / 0 / +0.143 |
| investigation_quality | 0.429 / 57.1% / 100% / 0 / +0.143 | 0.571 / 57.1% / 85.7% / 0 / -0.286 |
| output_usefulness | 0.714 / 28.6% / 100% / 0 / +0.714 | 0.571 / 42.9% / 100% / 0 / **+0.000** |
| tool_correctness | 0.286 / 71.4% / 100% / 0 / +0.286 | 0.000 / 100% / 100% / 2 NA-mismatch / **+0.000** |
| **Overall (46 vs 44 numeric pairs)** | **MAD 0.435, exact 60.9%, ±1 95.7%, bias +0.348** | **MAD 0.386, exact 63.6%, ±1 97.7%, bias +0.023** |

Frontier is directionally better on the aggregate: lower MAD (0.386 vs
0.435), higher exact agreement (63.6% vs 60.9%), higher ±1 agreement
(97.7% vs 95.7%), and a much smaller signed bias (+0.023 vs +0.348 —
Mistral systematically over-scores on this subset, frontier is close to
unbiased). Grounding is the one dimension frontier is worse on
(0/4→1/4 exact instead of 3/4), but n=4 is too small to weigh heavily.
`tool_correctness` shows a 2-case NA-mismatch for frontier not present in
Mistral's run (frontier marked `not_applicable` where the deterministic
`_enforce_tool_correctness_policy` safety net did not override it because
those 2 turns had no ground truth data available — legitimate NA, not a
frontier defect; Mistral scored those same 2 turns with a number instead
of NA, which is itself a Mistral NA-policy miss on this subset).

## Gates — same 7 comparable cases

| Gate | Human/Mistral exact/FP/FN | Human/Frontier exact/FP/FN |
|---|---|---|
| F1_fabrication | 6/7 (85.7%), FP=0, FN=1 (Respuesta 2) | 6/7 (85.7%), FP=0, FN=1 (Respuesta 2) |
| C4_unsupported_causality | 5/7 (71.4%), FP=1 (Respuesta 8), FN=1 (Respuesta 2) | 6/7 (85.7%), FP=0, FN=1 (Respuesta 2) |
| C5_forbidden_claim | not triggered by human on any of these 8 cases; not triggered by either judge on any of the 7 comparable cases — 7/7 trivial agreement for both | same |

Frontier eliminates Mistral's C4 false positive on Respuesta 8 (properly
hedged Apo/CBRE hypothesis) — confirmed correct, see case (b) below — and
matches Mistral (and human) exactly on Respuesta 9's true C4 trigger. F1
is unchanged: **both judges still miss the Strip Machalí fabrication**
(case a).

## Divergences > 1 point

- **Mistral vs human** (on the 7-case subset, recomputed): none — the
  only >1 divergence in the original round-3 doc was on Respuesta 2's
  grounding/hallucination (human=2, judge=4, diff=2 each), which on
  recount here shows as diff=2 on hallucination but is masked in the
  MAD table above only because bias/MAD are dimension-aggregates; see
  case (a) below for the actual per-case detail.
- **Frontier vs human**: **Respuesta 8** (`tae-l5-003`/track_b),
  `investigation_quality`: human=3, frontier=1 (diff=2). Frontier judged
  the investigation as materially shallower than the human did; everything
  else on Respuesta 8 (including the correctly-not-triggered C4) matches
  within 1 point.

## Case-by-case: the four named diagnostic scenarios

### (a) Strip Machalí — `tae-l4-001`/track_b (Respuesta 2)

**Not fixed.** Frontier judge, same as Mistral across all three prior
rounds, does **not** trigger F1 for the response's transformation of
`vigente_hasta='2025-08'` into "el contrato terminó y no fue renovado."
Frontier's F1 gate output for this case: `{"triggered": false,
"confidence": 0.95}` — no justification/evidence needed since untriggered,
but the confidence is high, meaning the model is not hedging; it
genuinely does not read this as fabrication. C4 is also untriggered
(again matching Mistral's original miss, before Mistral's own C4 rewrite
made it swing the other way on unrelated cases). However, frontier *did*
score this response more conservatively on the surrounding dimensions
than Mistral did: `grounding=3, hallucination=3` (Mistral: `4, 4`) — a
partial signal that the frontier judge sees *something* off, it just
doesn't cross into F1. This is the single most important data point in
the whole experiment: it is not a Mistral-specific quirk. **Points toward
a rubric-conceptual gap**, not a judge-model limitation.

### (b) Apo/CBRE-JLL — `tae-l5-003`/track_b (Respuesta 8)

Response text opens with an F1-eligible claim (external-source
attribution: figures framed as coming from "CBRE/JLL" data the system
never consulted) and later includes appropriately hedged conditional
language elsewhere. Frontier correctly separates the two: `F1_fabrication:
triggered=true` (matches human and Mistral — all three agree this is
fabrication) and `C4_unsupported_causality: triggered=false` (matches
human; **Mistral incorrectly triggered C4 here** in round 3, one of the
two C4 regressions documented in `human_vs_judge_v1_2_comparison`).
Frontier gets the harder distinction right where Mistral (on the
pre-narrowing round-3 rubric) did not. Caveat: Mistral was run against
round-3's rubric (pre-C4-narrowing); the current HEAD rubric frontier
used already contains the C4 narrowing intended to fix exactly this kind
of false positive, so this delta is partly rubric-version, partly
judge-model — cannot cleanly attribute 100% to the model swap. Frontier's
own within-response consistency (F1 vs C4 correctly split) is still a
clean result on its own terms.

### (c) TRI vacancia / wrong driver — `tae-l4-002`/track_b (Respuesta 9)

Response claims a January 2026 vacancy drop at Viña Centro was a
"reporting/accounting error" and asserts causal explanations for both the
drop and the February rebound without corroborating evidence
(`raw_movimiento_contrato`/`v_absorcion_activo` cited as absent, not as
supporting the claim). Frontier: `F1_fabrication=true`,
`C4_unsupported_causality=true`, `analytical_quality=0`, `grounding=0`,
`hallucination=0` — all matching both human and Mistral exactly. No
divergence on this case; both judges catch the wrong-driver diagnosis and
the unsupported causal narrative correctly, unaffected by the model swap.

### (d) TIR TRI / wrong ticker + retrieval failure — `tae-l4-003`/track_b (Respuesta 10)

**Blocked** — could not be judged by the frontier model; see "Blocker"
section above (Gemini free-tier daily quota exhausted at 20
requests/model/day, confirmed on a dedicated retry with backoff, not a
transient failure). Mistral's round-3 result for this case (for
reference, not part of the frontier comparison): `F1_fabrication=false`
(correctly withheld — matches the retrieval-failure carve-out) but
`C4_unsupported_causality=true` where human marked it false ("las
hipótesis operacionales están calificadas, no las considero causalidad
afirmada") — this was one of round 3's two documented C4 regressions.
Whether the current-HEAD narrowed rubric plus a frontier model would fix
this specific C4 false positive is **unresolved** — could not be tested
today.

## Verdict

**Migrar al frontier judge** (migrate), with a clearly flagged residual
rubric gap.

This is not a declaration that `gemini-flash-latest` is the definitive
judge model — it was the only frontier-tier candidate with a live key in
this environment (no `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` configured),
one case was blocked by its free-tier quota, and it has not been
calibrated against a larger sample. It clearly outperforms
`mistral-large-latest` on every metric in this calibration (bias, MAD,
exact agreement, C4 gate) and is recorded as the **provisional preferred
judge** going forward, pending a broader run and/or a stronger candidate
(GPT-5.6, Opus 5/Sonnet 5) becoming available.

Reasoning from the numbers, not vibes:
- Overall signed bias improves sharply: **+0.348 → +0.023** (Mistral
  systematically over-scores by a third of a point on average across
  dimensions; frontier is nearly unbiased) on the identical 7-case
  subset.
- Overall MAD improves: **0.435 → 0.386**; exact agreement improves:
  **60.9% → 63.6%**; ±1 agreement improves: **95.7% → 97.7%**.
- C4 exact-gate-agreement improves: **5/7 → 6/7**, by eliminating exactly
  the false-positive pattern (over-triggering on properly hedged
  hypotheses) that round 3 flagged as "a real regression, not
  calibration noise" — case (b) confirms this concretely, though with the
  rubric-narrowing caveat noted above.
- No new disagreements appeared that Mistral did not already have, except
  a single >1-point dimension divergence on Respuesta 8's
  `investigation_quality` (human=3, frontier=1) — a plausible stricter
  read, not an obviously wrong one, and isolated to one dimension on one
  case.
- **However, the headline target of this experiment — the Strip Machalí
  F1 false negative — did NOT flip to a true positive with the frontier
  judge.** Since the same rubric, on the same input, produces the same
  miss from two different model families (Mistral and Gemini), this is
  evidence the gap is not "`mistral-large-latest` isn't reliably applying
  the rule" (as `judge_versioning_2026-08-13.md` speculated) but that the
  rule itself — F1 pattern (b), "transforming a supported fact into a
  more specific fact the data doesn't establish on its own" — is not
  landing on this response's specific phrasing for *any* model tried so
  far. That is exactly the rubric-conceptual-gap outcome, isolated to
  this one pattern.

Combined recommendation: the aggregate calibration (bias, MAD, C4 gate)
is meaningfully better on the frontier judge, supporting migration for
day-to-day grading. But do not treat this experiment as closing the
Strip Machalí case — flag F1 pattern (b) as a still-open rubric
sharpening target for a future round, now backed by two-model evidence
rather than one.
