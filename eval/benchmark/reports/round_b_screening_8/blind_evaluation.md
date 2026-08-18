# Round B screening 8 — blinded evaluation

This evaluation used only `blind_package.json`; the hidden mapping was not opened. Confidence is moderate: Mini-Dev is broad but only 25 turns per candidate, and repeated five-iteration exhaustion is a material limiting behavior across the field.

## A. Current Track B quality

1. Candidate H
2. Candidate C
3. Candidate A
4. Candidate G
5. Candidate B
6. Candidate D
7. Candidate E
8. Candidate F

## B. F4 potential

1. Candidate H
2. Candidate C
3. Candidate A
4. Candidate G
5. Candidate B
6. Candidate D
7. Candidate E
8. Candidate F

## Candidate H — Full Dev: yes (moderate confidence)

Strengths: strongest observed factual/completeness signal; generally gives grounded numeric answers and appropriately qualifies data quality. Example: `tae-l8-002` reports the DSCR and explicitly marks confidence as low. Weaknesses: repeatedly exhausts the tool-iteration cap in `tae-l4-003`, `tae-l4-004`, `tae-l5-004`, and several multi-turn investigations. Serious risk: a well-framed but incomplete answer can conceal unresolved analysis. F4 potential is highest because the remaining issue looks primarily like stopping/tool-budget discipline.

## Candidate C — Full Dev: yes (moderate confidence)

Strengths: second-best completed-answer quality with clear entity-level analytical narratives; `tce-investigationdrilldown-001` turn 1 traces PT leverage to specific office-credit exposure. Weaknesses: its DSCR answer in `tae-l8-002` is not sufficiently careful about the reported indicator's reliability, and several complex cases terminate without an answer. Serious risk: plausible financial synthesis can overstate a weakly grounded interpretation.

## Candidate A — Full Dev: yes, conditional (low-to-moderate confidence)

Strengths: good investigation depth and a useful rent-roll reconciliation structure in `tae-l5-006`. Weaknesses: excessive tool use and many cap exhaustions, including both decision-challenge turns and the multi-domain sequence. Serious error: the Curicó reconciliation earned zero factual correctness, so its confident conclusion is unsafe. Advance only with explicit tool-budget and numerical reconciliation gates.

## Candidate G — Full Dev: no, reserve (low confidence)

Strengths: middle-of-field factual signal and fewer tools than the most exploratory candidates. Weaknesses: complex TAE/TCE work often ends at the cap without a conclusion, including all drilldown turns. Serious risk: reliability is too dependent on simple cases. Its F4 rank reflects a usable base, not readiness.

## Candidate B — Full Dev: no, reserve (low confidence)

Strengths: can produce structured analytical prose; `tae-l5-006` attempts a source reconciliation. Weaknesses: low completion on multi-step investigation and an incorrect Curicó conclusion. Serious risk: apparent polish is not a substitute for verified arithmetic and source alignment.

## Candidate D — Full Dev: no (moderate confidence)

Strengths: no compensating qualitative strength was consistently visible. Weaknesses: widespread cap exhaustion across analyst and conversational cases despite high tool volume. Serious risk: poor stopping behavior leaves the user without a decision-ready answer.

## Candidate E — Full Dev: no (moderate confidence)

Strengths: comparatively restrained tool usage. Weaknesses: the restraint does not yield completion; `tae-l2-003` and `tce-investigationdrilldown-001` turn 1 score zero across the available deterministic dimensions. Serious risk: insufficient investigation plus non-delivery.

## Candidate F — Full Dev: no (high confidence)

Strengths: one useful LTV-oriented response in `tae-l4-004`. Weaknesses: lowest factual/completion signal, repeated claims of unavailable data contradicted by the benchmark, and pervasive cap exhaustion. Serious errors: `tce-entitycorrection-001` makes unsupported asset/data assertions; `tce-investigationmultidomain-001` turn 2 reaches an incorrect coverage conclusion. This is dangerous confident-error behavior, not merely incompleteness.
