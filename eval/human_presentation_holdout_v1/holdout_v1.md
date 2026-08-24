# Human Presentation Holdout v1

Frozen, not used for tuning. Grades the presentation layer built for
"Human Analytical Presentation v1" (raw-data-dump answers -> natural,
professional analyst prose) on four dimensions:

- **FACTUAL INTEGRITY** — value/unit/entity/period/aggregation match the
  underlying governed fact exactly (never mutated by presentation).
- **HUMAN READABILITY** — reads like a competent analyst, not a data dump.
- **INTERNAL-JARGON LEAKAGE** — no `canonical`, `ToolEvidence`, `coverage=`,
  `entity_id=`, `YYYY-MM..YYYY-MM`, raw account/entity codes, etc.
- **APPROPRIATE BREVITY** — short answer for a simple scalar fact; more for
  comparisons/analysis; no boilerplate disclaimer when not material.

Freeze date: 2026-08-24. Commit evaluated: working tree at HEAD 8089e9c +
this stage's changes (see final report for the exact commit hash).
Executed by: Claude (this session), against the real server
(`scripts/ingesta_server.py`, port 8765) via `POST
/api/analyst/conversations/{id}/messages`. Not used to tune the presentation
layer beyond fixing implementation bugs the run itself surfaced (documented
per-case below); no case content was altered afterward.

## Cases

### 1. Scalar annual flow
**Q:** "cual fue el noi del fondo PT en 2025?"
**A:** "El NOI acumulado del fondo PT en 2025 fue 172.868 UF."
- Factual integrity: PASS (172,868 UF matches the raw sum; "acumulado"
  correctly signals a sum aggregation).
- Readability: PASS — one clean sentence.
- Jargon leakage: PASS — no raw entity_id/metric_key/period code.
- Brevity: PASS — a one-line answer for a one-line question.

### 2. Partial-year sum (within-year range)
**Q:** "suma el NOI mensual del fondo PT entre enero y junio de 2025"
**A:** "La suma del NOI mensual del fondo PT entre enero y junio de 2025 fue 82.993 UF."
- Factual integrity: PASS.
- Readability: PASS.
- Jargon leakage: PASS — no "2025-01..2025-06" notation.
- Brevity: PASS.

### 3. Point-in-time ratio
**Q:** "cual fue el LTV del fondo TRI en junio de 2026?"
**A:** "El LTV del fondo TRI en junio de 2026 fue 61,02%."
- Factual integrity: PASS — matches the frozen TIR/leverage-block value
  (61.0165% rounds to 61,02%).
- Readability: PASS.
- Jargon leakage: PASS.
- Brevity: PASS.

### 4. Multi-turn follow-up (year substitution)
**Q1:** "NOI del fondo TRI en 2025" -> "El NOI acumulado del fondo TRI en 2025 fue de 315.312 UF."
**Q2:** "y en 2024?" -> "El NOI anual de fondo TRI aumentó entre 2024 y 2025: pasó de 310.473 UF a 315.312 UF. Esto equivale a un alza aproximada de 1,6% interanual."
- Factual integrity: PASS — both years' values correct, delta correctly computed.
- Readability: PASS — natural comparative sentence, not two disconnected facts.
- Jargon leakage: PASS.
- Brevity: PASS — a little more elaboration than case 1, appropriate for a
  comparison.

### 5. Multi-turn entity substitution + comparison synthesis
**Q3 (same thread):** "y PT ese mismo año?" -> entity-resolution clarification
("¿Te refieres al fondo PT o a un activo?") -> "el fondo PT" -> table +
one-line synthesis naming TRI/PT/years and values.
- Factual integrity: PASS.
- Readability: PASS (compact table appropriate for 3 facts).
- Jargon leakage: PASS.
- Brevity: PASS.
- Note: the entity-resolution clarification step is a pre-existing,
  out-of-scope behavior (ambiguous "PT" as asset vs fund), not a
  presentation defect; documented as a known limitation in the final report.

### 6. Cross-metric comparison + "which is more leveraged"
**Q1:** "LTV del fondo TRI en junio de 2026" -> scalar answer.
**Q2:** "y el fondo PT?" -> "A junio de 2026, el LTV de fondo PT fue superior al de fondo TRI: fondo PT 81,22% frente a fondo TRI 61,02%. Esto refleja un nivel de apalancamiento relativamente mayor en fondo PT para ese mes."
**Q3:** "cual esta mas apalancado?" -> "El fondo **PT** está más apalancado: su LTV fue **81,2%**, versus **61,0%** de TRI en junio de 2026."
- Factual integrity: PASS.
- Readability: PASS — Q3 correctly compresses to the shortest sufficient
  answer once the comparison was already established.
- Jargon leakage: PASS.
- Brevity: PASS — adaptive length across the three turns (scalar -> full
  comparison -> compressed follow-up) is exactly the spec's target
  behavior.

### 7. Accrued-vs-cash disclosure
**Q:** "cuanto pagamos por contribuciones en Torre A durante 2025?"
**A:** "En 2025, Torre A registró en contribuciones 15.220 UF. Corresponde a gasto contable devengado del período, por lo que no necesariamente equivale al monto efectivamente pagado en caja."
- Factual integrity: PASS.
- Readability: PASS — disclosure reads as one analyst would say it, not a
  compliance footer.
- Jargon leakage: PASS — no "basis=accrued_pnl_expense".
- Brevity: PASS — the disclosure is material to a cash-phrased question, so
  it is not boilerplate.

### 8. NONE case (no evidence, not zero)
**Q:** "cuanto gasto el fondo Apoquindo en seguros durante 2025?"
**A:** "No encontré evidencia de gasto en seguros para fondo Apo durante 2025. Esto no implica que el gasto haya sido cero, sólo que no hay datos gobernados que lo respalden."
- Factual integrity: PASS — correctly refuses to claim a zero; no invented
  number.
- Readability: PASS.
- Jargon leakage: PASS after the fix landed by this holdout run (see "Bugs
  found and fixed" below) — concept_id/entity/period previously leaked raw
  (`insurance`, `Apo`, `2025-01..2025-12`); now uses the account-concept
  catalog's display name ("seguros") and the generic period formatter.
- Brevity: PASS.

### 9. PARTIAL case, cross-year range
**Q:** "contribuciones de Torre A entre diciembre de 2017 y enero de 2018"
**A:** "Las contribuciones de Torre A entre diciembre de 2017 y enero de 2018 suman 1.495 UF. La cobertura es parcial: el monto observado corresponde a enero de 2018 y no hay registro disponible para diciembre."
- Factual integrity: PASS.
- Readability: PASS.
- Jargon leakage: PARTIAL — the model's own free prose uses the bare
  Spanish word "cobertura" (not the technical token `coverage=`); it is
  ordinary vocabulary an analyst might use, but the spec's letter prefers
  avoiding even "coverage"/"partial"-shaped words. Documented as a known
  limitation (soft, prompt-level, LLM word choice) rather than fixed via
  code, since forcibly banning the word "cobertura" from free Spanish prose
  is a prompt-tuning problem, not a deterministic-layer bug.
- Brevity: PASS.

### 10. Multi-entity comparison (table-worthy) with accrual disclosure
**Q:** "compara las contribuciones de Torre A y Boulevard durante 2025"
**A:** "En 2025, Torre A registró contribuciones por 15.220 UF. Boulevard PT registró 7.526 UF. La contribución de Torre A fue algo más del doble de la de Boulevard PT. Los montos corresponden al gasto contable devengado del período, no necesariamente a pagos efectivos de caja."
- Factual integrity: PASS.
- Readability: PASS — prose comparison (no table needed for 2 numbers, per
  spec's "presenter's choice").
- Jargon leakage: PASS after the fix in this run (see below) — the asset's
  own display name "Boulevard PT" was previously mangled to "Boulevard
  fondo PT" by an over-eager entity substitution.
- Brevity: PASS.

### 11. Full-fund ranking with materially incomplete coverage
**Q:** "Rankea los activos de TRI por NOI mensual de junio de 2026."
**A:** "El ranking informado corresponde sólo a una cobertura parcial: 4 de los 11 activos de fondo TRI en junio de 2026. Entre los activos observados, el orden descendente de NOI mensual es Viña Centro, INMOSA, Bodegas Maipú (Sucden) y Mall Curicó; por lo tanto, no permite afirmar que sea el ranking completo del fondo. [+ deterministic coverage caveat + per-entity values]"
- Factual integrity: PASS — ranking and values correct; the deterministic
  4-of-11 caveat is present verbatim from `coverage_guard`, not paraphrased
  away.
- Readability: PASS, with a caveat: the deterministic prefix ("Ojo: estos
  datos alcanzan a...") and the model's own prose caveat both explain the
  same limitation, which is somewhat repetitive. Not a regression from this
  work (the redundancy existed with the old wording too) — noted as a known
  limitation, candidate for a v2 that de-duplicates when both layers agree.
- Jargon leakage: PASS — no "coverage=", no raw entity_ids.
- Brevity: FAIL (minor) — the double caveat is longer than strictly
  necessary for what is otherwise a correctly-scoped answer.

### 12. Detailed disaggregation with mixed per-asset coverage (floor-level vacancy)
**Q:** "¿Cuál es la vacancia por piso de todos los activos de TRI en junio de 2026?"
**A:** table for Apoquindo 3001 + natural explanation of why the rest of the portfolio can't be broken down by floor + clean entity list (post-fix; previously had "Apoquindo 3001 (Apoquindo 3001)" duplication and a missing space before "En Apoquindo 3001").
- Factual integrity: PASS.
- Readability: PASS after the dedup fix in this run.
- Jargon leakage: PASS.
- Brevity: PASS — appropriately long for a materially complex partial
  answer (table + explanation + full entity list), not padded.

### 13. Legacy/free-text asset vacancy (raw_text fragment path)
**Q (synthetic, from `test_entity_provenance_session.py`):** raw_text fragment carrying "Apo3001 tuvo vacancia alta este mes."
**A (rendered):** "Apoquindo 3001 tuvo vacancia alta este mes."
- Factual integrity: PASS — the sentence's claim is unchanged, only the
  identifier is relabelled.
- Readability: PASS.
- Jargon leakage: PASS — raw asset key no longer reaches the reader.
- Brevity: PASS.

## Bugs found and fixed during this holdout run

1. **"fondo fondo PT" duplication** — `humanize_text`'s entity substitution
   added the fund's "fondo " prefix even when the model's own prose already
   wrote "el fondo PT". Fixed in `tools/analytics/humanize.py` by detecting
   the immediately-preceding "fondo "/"Fondo " and dropping the duplicate.
2. **"Boulevard fondo PT" mangling** — a raw fund key ("PT") that happens to
   be a suffix of an asset's own display name ("Boulevard PT") was
   substituted mid-phrase. Fixed by switching to a single combined
   alternation pass (longest match wins, including known display names as
   self-protecting entries) instead of per-key sequential passes.
3. **NONE-case jargon leak** (`insurance`, `Apo`, `2025-01..2025-12` in raw
   form) — `_account_no_evidence_text` in `tools/analyst_runtime/session.py`
   was an f-string over raw fields. Rewritten to use the account-concept
   catalog's `display_name`, `entity_display_name`, and the generic period
   formatter.
4. **"Apoquindo 3001 (Apoquindo 3001)"** self-parenthetical duplication in
   entity enumerations. Fixed in `coverage_guard._render_entity_fact` by
   skipping the parenthetical when the raw `name` field equals the already
   -resolved display name.

None of these were tuned against wording preference; each was a literal
defect (duplicated/garbled identifier, or a raw internal token reaching the
user) caught by running real questions through the real server.

## Summary

| Dimension | Pass | Partial | Fail |
|---|---|---|---|
| Factual integrity | 13 | 0 | 0 |
| Human readability | 12 | 1 | 0 |
| Internal-jargon leakage | 12 | 1 | 0 |
| Appropriate brevity | 12 | 0 | 1 |

No case shows a factual-integrity failure. The two soft findings (case 9's
bare word "cobertura" in free prose, case 11's redundant double caveat) are
prompt-level polish items, not architecture defects, and are listed as known
limitations in the final report rather than papered over.
