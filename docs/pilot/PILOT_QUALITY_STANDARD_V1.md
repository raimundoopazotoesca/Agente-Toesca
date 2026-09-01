# Toesca Real Estate AI Analyst — Pilot Quality Standard v1

**Status:** design/standard document only. No runtime, prompt, grader, DB, test, CI, or
deployment change is made or implied by this document. Historical design origin: base
commit `d986996`; current repository state is synchronized with protected branch
`feat/alpha-v0.1`. Worktree `docs/pilot-quality-standard-v1`.

**Revision provenance.** Draft 1 of this standard was written without access to the
external agent-engineering and agent-evaluation sources it referred to; principles taken
from them were tagged `A(general)` and nothing specific was attributed. Those sources are
now available and have been read. This revision is an **incremental, evidence-driven pass**
over Draft 1 — it keeps Draft 1's structure and numbering, cites the sources concretely,
corrects the claims that the new evidence contradicts or qualifies, and removes the
`PILOT_OPS` pseudo-taxonomy. §34 records exactly which sources were read, what each is,
what it supports, and what changed as a result. Every Draft 1 open decision is still open.

**Relationship to existing work.** This document does **not** create a second evaluation
taxonomy. It consumes:

- `docs/toesca-analyst-eval-observability-blueprint-v1.md` (the eval blueprint — failure
  taxonomy, outcome/component/trajectory evals, judge split, trace contract, Reliability
  Core, CI gates). Cited below as **blueprint §X**.
- `docs/toesca-analyst-llm-judge-policy-v1.md` (the committed judge policy). Cited as
  **judge policy**.
- `docs/toesca-data-foundation-target-contract-v1.md` (A1.5 Entity/Metric/Dataset/Source/
  Temporal contracts). Cited as **A1.5 §X**.
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md` (verified current product state).
- `docs/superpowers/plans/2026-08-28-jll-v2-production-readiness.md` and the
  `jll-v2-*` worktree docs (JLL v2 disposition).

The eval blueprint answers *"how do we measure the Analyst?"*. This document answers a
different question: *"what must be true before real Toesca people are allowed to depend on
it?"* Pilot readiness ⊇ eval reliability core, and adds product, operations, data
freshness, reporting, and human-support dimensions the blueprint deliberately did not
cover.

### Authority model (used throughout)

Every load-bearing claim in this document belongs to exactly one of four authority types.
The letter tags below are the shorthand actually written inline; the authority type is what
the tag *means*. The distinction matters most in one direction: **an external source may
motivate a Toesca requirement, but it never issues one.** "Anthropic/OpenAI/Stanford
describe X, therefore Toesca must implement exactly Y" is two claims, and the second is
always a `TOESCA-DESIGN-DECISION`.

| Tag | Authority type | Meaning |
|---|---|---|
| **S** | `SOURCE-DERIVED` | A principle directly supported by one of the external sources read in the revision pass (§34). Cited by filename plus section/lesson/slide/page. Replaces the earlier `A(general)` tag, which existed only because those sources had not yet been read. |
| **A** | `REPO-EVIDENCE` (governing documents) | Backed by a governing Toesca document already in this repository: the eval blueprint, the judge policy, or the A1.5 data-foundation contract. Normative *inside this repo*; not an external authority. |
| **B** | `REPO-EVIDENCE` (implementation state) | A verified fact about the current repository: code, migrations, tests, `CURRENT_STATE.md`, `ROADMAP.md`, gate manifests. Cited with the file it came from. |
| **C** | `TOESCA-DESIGN-DECISION` | A judgment call proposed here for Toesca. May be *motivated* by **S** or **A**, but is not required by them. Contestable by construction. |
| **D** | `OPEN-DECISION` | Needs a named human. Deliberately unresolved; an external source can never close one of these. |

Where a claim is motivated by a source but decided here, both tags appear: **S → C**.

### Threshold policy tags (used for every quantitative statement)

Per blueprint §N's own discipline, no bare number appears in this document without one of:

| Tag | Meaning |
|---|---|
| `HARD_INVARIANT` | Structurally guaranteed by construction, not measured as a rate. |
| `ZERO_TOLERANCE` | Hard zero-occurrence gate; a single occurrence blocks. |
| `THRESHOLD_TO_CALIBRATE` | A number that must be measured on real data before it is fixed. The calibration method is stated with it. |
| `BASELINE_RELATIVE` | Judged against a measured baseline, never an absolute. |
| `HUMAN_ACCEPTANCE_REQUIRED` | No metric substitutes; a named human signs off. |

---

## 1. Purpose

This document defines the **entry gate** for an internal pilot of the Toesca Real Estate
AI Analyst: the explicit, evidence-based set of conditions that must hold before real
Toesca analysts are invited to use the product for real work.

It exists so that, months from now, this project can say *"no, not ready yet"* even when
the product technically works and demos well — and equally can say *"yes, good enough to
learn from real users"* without demanding impossible perfection. **[C]**

Governing principle, adopted as a project rule: **preferimos un buen piloto más tarde que
un mal piloto antes.** Pilot readiness is a gate on evidence, never a date. **[C]**

Target product framing this standard is written against, quoted verbatim from the product
brief:

> "Toesca Real Estate AI Analyst no será un chatbot incrustado en un factsheet. Será el
> workspace analítico principal de Toesca, dentro del cual viven el chat, el factsheet,
> los informes determinísticos y posteriormente los artifacts personalizados."

The target pipeline this standard evaluates readiness against:

```
User
  → Conversational understanding
  → Semantic / governance layer
  → Single Analyst Agent
  → Governed analytical tools/datasets  OR  verified queries  OR  controlled Text-to-SQL long tail
  → SQL safety
  → Result validation
  → Evidence package
  → Synthesis
  → Answer
                      (with tracing/evals over the whole path)
```

## 2. Definition of a successful pilot

A pilot is successful — and therefore worth starting — only if it can plausibly produce
**authentic learning from real analytical work**. That requires three things
simultaneously **[C]**:

1. **Useful.** A Toesca analyst can bring a real question from their actual workflow
   (vacancia, rent roll, NOI, ingresos, recaudación, vencimientos, concentración) and get
   an answer that saves them time versus opening the CDG or the source workbook.
2. **Trustworthy.** When the Analyst is wrong, it is wrong in *visible, attributable*
   ways — never confidently wrong about a business fact. A user must be able to check any
   number against its stated evidence without asking a developer.
3. **Unattended.** The development team does not need to watch over each session. Failures
   are captured by tracing and feedback, not by a developer reading the screen.

Explicitly **not** a definition of pilot readiness **[C]**:

- The chat opens and responds.
- It answers some questions correctly.
- The test suite passes.
- We could technically demo it.

A pilot that produces only "it said something plausible" is worse than no pilot: it burns
internal trust, which is the scarcest resource this product has, and it generates no
diagnosable failure data.

## 3. Non-goals

Out of scope for pilot readiness, deliberately **[C]**:

- **P3** Full architectural convergence on the target pipeline. The pipeline in §1 is the
  *direction*; the pilot must be honest about which segments are real and which are stubs,
  not complete all of them.
- **P3** A rigid intent catalog. Coverage is demonstrated by the task bank
  (`PILOT_TASK_BANK_V0.md`), not by enumerating every intent.
- **P3** Multi-agent architecture. Per the product brief, a single Analyst agent is the
  target; multi-agent is not a readiness condition and adds evaluation surface without
  demonstrated need. **[S]** — `02_a_practical_guide_to_building_agents.pdf`, "When to
  consider creating multiple agents" (p. 16): *"Our general recommendation is to maximize a
  single agent's capabilities first"*, and `05_openai_api_agents_consolidated_knowledge.md`
  §15, which sequences deterministic workflow → single agent + tools → network of agents and
  says to move right *"only when evaluation shows the current architecture is
  insufficient"*. Applying that to Toesca's pilot is **[C]**.
- **P3** Personalized artifacts, Excel/PPT generation, external data (Inciti). Per
  `docs/ROADMAP.md`, deferred by design. **[B]**
- **P2** Factsheet as the primary application. Per `docs/ROADMAP.md` "Product Shell &
  Reporting v1", the Analyst-first shell is approved but **not yet implemented** **[B]**;
  §22 states the minimum shell bar, not the full target.
- **P3** Retiring `agent.py` / `tools/factsheet_tools.py`. Both are still present and
  their long-term role is an open roadmap question **[B]** (`docs/CURRENT_STATE.md`).

## 4. Quality principles derived from sources

| # | Principle | Tag | Severity |
|---|---|---|---|
| P1 | **A judge may never be the sole arbiter of a fact that has ground truth.** If a value is resolvable by SQL against the snapshot, it is graded deterministically. | **A** (blueprint §E, restated normatively in the judge policy) | P0 |
| P2 | **Deterministic evidence constrains the judge; the judge never constrains deterministic evidence.** The existing `_enforce_tool_correctness_policy` override is the template for any future guard. | **A** (judge policy) | P0 |
| P3 | **No silent fallback.** A failed judge yields an explicit unscored failure, not a guessed score. Extended here to the product: a failed tool/query yields an explicit "I could not establish this," not a plausible sentence. | **A** (judge policy) + **C** (product extension) | P0 |
| P4 | **Every bad answer must be attributable to exactly one primary failure class and one component owner.** Otherwise "wrong number" hides six upstream causes. | **A** (blueprint §D) | P0 |
| P5 | **There is no single gold trajectory.** Trajectory gates fire only on unambiguous anti-patterns, never on "this doesn't match a reference path." | **A** (blueprint §G) | P1 |
| P6 | **Resolution returns `resolved \| ambiguous \| unknown` with evidence — never a guess.** | **A** (A1.5 §G, and A1.5 A2 Entry Gates "invariantes") | P0 |
| P7 | **Meaning is declared, not inferred.** Unit, grain, temporal type, precedence, and provenance come from the contract layer, not from the model reading a column name. | **A** (A1.5 §H/I/J/K) | P0 |
| P8 | **Cheap deterministic checks run always; expensive judge/outcome runs only where they change a decision.** | **A** (blueprint §M) | P1 |
| P9 | **Latency and cost are optimized after quality, but must be *measured* before architecture tradeoffs are argued.** | **A** (blueprint §C.8) | P1 |
| P10 | **Context is engineered, not accumulated.** What the agent sees at each step is a designed artifact (governed tool results, structured evidence), not an ever-growing transcript. | **S** — `07_anthropic_agent_engineering_context_tools_evals.md` §1 (paraphrased digest of Anthropic's *Effective context engineering for AI agents*, 2025-09-29): treat the context window as a scarce working-memory resource; start from the minimum context needed; retrieve detail just in time | P1 |
| P11 | **Tools are a product surface.** Tool names, descriptions, and argument schemas are written for the model as a reader, and a tool that returns unlabeled numbers is a defective tool. | **S** — `07_...md` §2 (digest of *Writing effective tools for AI agents*): treat names, descriptions, parameter schemas and output formats as prompt design; return only context useful for the next decision; make errors actionable. Corroborated by `02_a_practical_guide_to_building_agents.pdf` p. 9 ("well-documented, thoroughly tested, and reusable tools") | P1 |
| P12 | **Evaluate outcome *and* trajectory.** A right answer reached by an invalid path is a latent failure, not a pass. | **S** — `07_...md` §3 ("Evaluation may therefore need to inspect both the final outcome and the run trace"); `04_cs329t_knowledge_pack_all.md`, Guest Lecture *Agent GPA*, slides 6–7, which decompose agent evaluation into Goal→Plan→Action alignment rather than judging only the final answer. Instantiated locally by blueprint §E/F/G **[A]** | P1 |
| P13 | **Infrastructure that is written but never invoked is worse than absent infrastructure**, because it produces a false sense of coverage (the F5 case). Anything this standard requires must be demonstrated *firing*, not merely present. | **A** (blueprint §C.3) → adopted here as a pilot rule **[C]** | P0 |
| P14 | **Determinism first; autonomy only where evaluation shows a fixed path cannot cope.** Where the analytical path is known, it belongs in code (governed dataset, deterministic report), not in the agent's discretion. This is the architectural justification for §26, and for keeping the governed-tool path preferred over the SQL long tail (TU-5). | **S** — `05_...md` §5.5: *"Do not add autonomy unless representative evaluations show that a fixed workflow cannot handle the real variation"*, and §15's level progression; `02_...pdf` p. 6: *"Before committing to building an agent, validate that your use case can meet these criteria clearly. Otherwise, a deterministic solution may suffice."* Applying it as a Toesca rule is **[C]** | P1 |
| P15 | **A judge is a system with its own error modes, and must be calibrated against humans before it gates anything.** Two specific modes matter here: judges are *distracted by too much information*, and they *agree with the agent's own stated reasoning even when it is wrong* — which is precisely the failure a self-justifying trajectory produces. This is why P1/P2 (deterministic evidence overrides the judge) are P0, why SY-6 keeps judge dimensions monitored rather than blocking, and why UC-5 adds a human layer over the C4 causality gate. | **S** — `07_...md` §3 ("Calibrate model judges with humans and inspect transcripts"); `04_cs329t...md`, *Agent GPA* slides 21–31 (LLM judges themselves benchmarked against human-annotated traces, and re-run repeatedly to measure consistency) and *Agent Evals Survey* slide 38 (AgentRewardBench: rules-based evaluation under-reports success while LLM-judges over-report it; named judge failure modes). Toesca's specific response is **[C]** | P0 |
| P16 | **Retrieval quality, groundedness, and answer relevance are three different failures and must be separable.** A query that runs and returns rows can still return the *wrong slice*; a grounded-sounding answer can rest on irrelevant context; a well-grounded answer can address the wrong question. Collapsing them into "the answer was wrong" destroys attribution (P4). | **S** — `01_building_and_evaluating_data_agents.md` Lesson 4 (the RAG-Triad applied to data agents: context relevance / groundedness / answer relevance, computed from the trace's retrieval spans); `04_cs329t...md` Lecture 3 slides 38–40 name the three failures separately (*Retrieval Failure*, *Lack of Groundedness*, *Answering the Wrong Question*) | P0 |

## 5. Pilot-readiness dimensions

Pilot readiness is assessed across ten dimensions, **all of which map onto the canonical
blueprint failure taxonomy**. Draft 1 introduced a tenth taxonomy value, `PILOT_OPS`, for
pilot-operations concerns. That was a mistake and is **corrected in this revision**: a
failure mode and an operational obligation are different objects. `PILOT_OPS` no longer
exists anywhere in this standard, the eval matrix, or the task bank.

Operational obligations are now carried by a separate, orthogonal attribute,
`pilot_operational_requirement` — a named human/process commitment (operator governance,
weekly triage, external gate closure, report cutover). Every eval row still declares a
canonical `taxonomy_dimension` describing the *failure* it prevents; rows that also carry
an operational obligation declare it in the second field. **[C]**

The canonical taxonomy, unchanged from blueprint §D and closed to additions:

`DATA · SEMANTIC · ENTITY · METRIC · PERIOD · CONTEXT · PLANNING · TOOL_SELECTION ·
TOOL_ARGUMENTS · SQL · RESULT_VALIDATION · TRAJECTORY · SYNTHESIS · CONVERSATION_STATE ·
SAFETY · INFRA`

| # | Dimension | Canonical taxonomy classes it covers | Operational requirement | Standard section |
|---|---|---|---|---|
| R1 | Data readiness | DATA | — | §8 |
| R2 | Semantic readiness | SEMANTIC | — | §9 |
| R3 | Resolution correctness | ENTITY, METRIC, PERIOD, CONTEXT | — | §10 |
| R4 | Investigation quality | PLANNING, TRAJECTORY | — | §11 |
| R5 | Tool & SQL correctness | TOOL_SELECTION, TOOL_ARGUMENTS, SQL | — | §12–13 |
| R6 | Validation & evidence | RESULT_VALIDATION | — | §14–15 |
| R7 | Answer quality | SYNTHESIS, CONVERSATION_STATE | — | §16–19 |
| R8 | Safety | SAFETY | — | §20 |
| R9 | Operability | INFRA | — | §21, §23, §24 |
| R10 | Pilot operations | DATA / SAFETY / INFRA (per the specific failure) | `operator_governance`, `weekly_triage`, `external_gate_closure`, `report_cutover` | §25–28 |

The GPA framing used by the external sources (`04_cs329t_knowledge_pack_all.md`, *Agent
GPA* slides 7–19; `01_building_and_evaluating_data_agents.md` Lesson 5) maps onto this
taxonomy without extending it — recorded here so nobody introduces it as a rival scheme
**[S → C]**:

| GPA judge (source) | Canonical class here |
|---|---|
| Goal Fulfillment / Answer Relevance | SYNTHESIS |
| Plan Quality | PLANNING |
| Plan Adherence | TRAJECTORY |
| Execution Efficiency | TRAJECTORY |
| Logical Consistency | TRAJECTORY (with SYNTHESIS for the final claim) |
| Tool Selection | TOOL_SELECTION |
| Tool Calling | TOOL_ARGUMENTS |

## 6. Hard blockers

**P0 items only.** Every item here is either a `HARD_INVARIANT`, a `ZERO_TOLERANCE` gate,
or `HUMAN_ACCEPTANCE_REQUIRED`. No item here is a tunable quality percentage — quality
percentages live in §7 and in the matrix as P1/P2.

**Blocking scope (new in this revision).** Draft 1 treated all thirteen blockers as
blocking the *entire* pilot. That is wrong for some of them, and a standard that
over-blocks gets ignored rather than obeyed. Each blocker now declares its **scope**:

| Scope | Meaning |
|---|---|
| `PRODUCT` | Unmet ⇒ no pilot at all. |
| `CAPABILITY` | Unmet ⇒ the affected capability is removed from the pilot surface (unreachable, and refused explicitly if asked); the rest of the pilot may proceed. |

`CAPABILITY` scoping is not a softening: a capability that fails its blocker must be made
**unreachable**, not caveated — the same construction HB-9 already uses. **[C]**

### Review of each blocker (revision pass)

Each of Draft 1's thirteen blockers was re-examined against the question set: what is the
exact failure, what is the damage, must it block the whole product, is it demonstrable, and
does any evidence support that severity. Outcome:

| Blocker | Draft 1 | This revision | Why |
|---|---|---|---|
| HB-1 fabrication | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | The damage is a wrong business fact acted on. Corroborated: `04_cs329t...md` Lecture 2 slide 8 defines grounding as *every* claim being attributable to an authoritative source; the *Agent GPA* Logical Consistency rubric (slide 9) treats an unjustified claim as a trace-level defect, not a style issue **[S]**. |
| HB-2 no write path | P0 `HARD_INVARIANT` | **unchanged**, `PRODUCT` | Guaranteed by construction **[B]**. `02_...pdf` p. 26 ("Tool safeguards") rates tool risk by read-only vs write, reversibility and financial impact — a read-only surface is the reason this product's guardrail surface can be narrow **[S]**. |
| HB-3 no cross-session leak | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | Irreversible confidentiality damage; the pilot is the first genuinely multi-user context **[B]**. |
| HB-4 no silent entity guess | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | `Apo3001 ∈ TRI` makes a silent guess a cross-fund error **[B]**. |
| HB-5 no undeclared period substitution | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | Declared substitution is already carved out (CB-4). |
| HB-6 no unit relabel | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | `renta_uf` rate-vs-total is a live, documented defect class **[B]**. |
| HB-7 no forbidden source | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | Standing project rule **[B]**. |
| HB-8 no unsupported causality | P0 `ZERO_TOLERANCE` | **unchanged**, `PRODUCT` | Most useful-sounding failure mode; see §17. |
| HB-9 gated metrics unreachable | P0 `HARD_INVARIANT` | **unchanged**, `CAPABILITY` by construction | Already the model for scope-aware blocking. |
| HB-10 trace on every turn | P0 `HARD_INVARIANT`, all turns | **reformulated**, `PRODUCT` | The requirement Draft 1 wanted was reconstructibility, not universal logging. Restated below as *analytically consequential* turns. |
| HB-11 every gate firing | P0 `ZERO_TOLERANCE`, all gates | **split**, `PRODUCT` for P0-backing gates, `CAPABILITY`/P1 otherwise | A dead gate behind a P0 blocker is a false safety claim; a dead P2 dimension is a coverage gap, not a hazard. |
| HB-12 operator sign-off | P0 `HUMAN_ACCEPTANCE_REQUIRED` | **kept P0**, reclassified as `pilot_operational_requirement`, not a taxonomy dimension | Supported: `02_...pdf` p. 31 makes human intervention *"especially important early in deployment, helping identify failures, uncover edge cases, and establish a robust evaluation cycle"*; `05_...md` §13 requires human control for risky or ambiguous actions **[S]**. The choice to make it a blocker is **[C]**. |
| HB-13 declared-and-true freshness | P0, mixed tags | **split**, `PRODUCT` for the declare-or-refuse invariant, `CAPABILITY` for the per-surface freshness sign-off | Two different obligations were fused; see below. |

No blocker was removed. Two were reformulated, two were split, and one was reclassified as
an operational requirement. **[C]**

| ID | Blocker | Policy tag | Scope | Source tag |
|---|---|---|---|---|
| **HB-1** | **No fabricated business fact reaches a user.** Any number, entity, period, or tenant name stated as fact must trace to a tool/query result in the same turn's trace. Corresponds to blueprint gate F1 + C1/C2. | `ZERO_TOLERANCE` | `PRODUCT` | A (blueprint §N) + S (`04_cs329t...md` L2 slide 8; *Agent GPA* slide 9) |
| **HB-2** | **No write path from the Analyst to any database.** Enforced by the SQLite authorizer (`tools/analyst_runtime/sqlite_guard.py::make_authorizer`), which allow-lists `SELECT/READ/FUNCTION/RECURSIVE` and is shared verbatim between sandbox and production **[B]**. Stated as "authorizer denial count on any non-read action = 0", which is guaranteed by construction, not measured. | `HARD_INVARIANT` | `PRODUCT` | A (blueprint §N) + B + S (`02_...pdf` p. 26 tool-risk rating) |
| **HB-3** | **No cross-session/cross-user data leakage.** Session isolation holds for every pilot user. Blueprint gates F3/F4. | `ZERO_TOLERANCE` | `PRODUCT` | A (blueprint §D SAFETY) |
| **HB-4** | **Entity resolution never silently guesses.** Every answer's entity is `resolved` with evidence, or the turn is a clarification, or an explicit `unknown`. Specifically: `Apo3001` must never be attributed to fund `Apo` **[B]** (`docs/matriz-claves-ambiguas-apoquindo.md`; it belongs to `TRI`), and `Apoquindo` / `Fondo Apoquindo` must be treated as scopes, not assets **[B]** (A1.5 §G). | `ZERO_TOLERANCE` on silent guessing | `PRODUCT` | A (A1.5 §G) + B |
| **HB-5** | **Period resolution never silently substitutes.** A period different from the one asked may be used only if the answer declares the substitution. Blueprint gate C3. | `ZERO_TOLERANCE` on undeclared substitution | `PRODUCT` | A (blueprint §E) |
| **HB-6** | **Unit is never relabelled.** The unit reported must be the `value_unit` the structured evidence declares (A1.5 §H). The `renta_uf` total-vs-per-m² class of bug is the canonical example. | `ZERO_TOLERANCE` on unit relabelling | `PRODUCT` | A (blueprint §E, A1.5 §H/I) |
| **HB-7** | **Forbidden source is never used.** "No usar el CDG" is a standing project rule, not a preference **[B]** (`CLAUDE.md`, MEMORY). Source precedence must be established from structured tool provenance (A1.5 §J), not from which table a query happened to hit. | `ZERO_TOLERANCE` | `PRODUCT` | A (blueprint §E/N) + B |
| **HB-8** | **No unsupported causal claim.** Blueprint gate C4. See §17. | `ZERO_TOLERANCE` | `PRODUCT` | A (blueprint §N) |
| **HB-9** | **Every metric the Analyst can answer on is `active` in the contract layer.** Metrics behind an A1.5 domain gate (`dy_amort`; LTV/DSCR/net debt/duration without approved temporal methodology; vacancia with unresolved UG treatment; Mall Curicó ER account mapping) must be *unreachable* in the pilot surface, not merely discouraged **[B]** (A1.5 A2 Entry Gates). | `HARD_INVARIANT` (unreachable by construction) | `CAPABILITY` | A (A1.5) + B |
| **HB-10** | **Every analytically consequential turn produces a reconstructible trace.** An *analytically consequential* turn is any turn that (a) states a business fact, (b) invokes a tool or emits SQL, or (c) resolves an entity, metric, or period. For those turns the §24 MUST fields exist and are sufficient to reconstruct `entity → metric → period → plan → tool → query → result → validation → evidence → synthesis`. Turns that are none of the three (greetings, meta-questions about the product, pure clarification exchanges carrying no resolved state) are not required to carry a full trace. **Revised from Draft 1's "every turn"**: the failure being prevented is an *undiagnosable wrong answer*, and an untraced greeting cannot produce one. Over-broad logging was also the wrong ask — the sources treat the trace as the input to evaluation, spanned by step type, not as an audit log of everything. | `HARD_INVARIANT` (a consequential turn is traced or is not served) | `PRODUCT` | C, grounded in blueprint §K and **S** (`01_...md` Lesson 4: spans typed *planning / routing / retrieval / tool use / generation*, with retrieval spans carrying the eval inputs; `05_...md` §6, which lists exactly model calls, tool calls, tool outputs, handoffs, guardrails, approvals and retries as what observability must cover) |
| **HB-11** | **Every gate and guard that backs a P0 blocker is demonstrated firing at least once** on the pilot-representative task set — the anti-F5 rule (P13). Concretely: F1, F3, F4, F5, C1–C5, the SQLite authorizer, the coverage guard, and the RV-5 validator subset. **Revised from Draft 1's "every gate"**: a dead gate behind a P0 blocker is a *false safety claim* and blocks the product; a dead P1/P2 dimension is a coverage gap, and blocks only the claim that that dimension is covered (it moves to SW-9). | `ZERO_TOLERANCE` on dead P0-backing gates | `PRODUCT` (P0-backing) / `CAPABILITY` (all others) | A (blueprint §C.3/§H) |
| **HB-12** | **A named pilot operator has signed off** that the product is fit to put in front of the named pilot users, having personally run the P0 subset of the task bank. This is a **`pilot_operational_requirement` (`operator_governance`), not a taxonomy dimension** — it prevents no specific failure mode; it establishes who is accountable when one occurs. It remains a blocker because a pilot with no accountable human is a demo, and because the sources treat early-deployment human oversight as the mechanism that turns failures into an evaluation cycle at all. | `HUMAN_ACCEPTANCE_REQUIRED` | `PRODUCT` | C, motivated by **S** (`02_...pdf` p. 31 "Plan for human intervention"; `05_...md` §13 "Human control") |
| **HB-13a** | **Declare-or-refuse.** Every factual answer states the period coverage and `as_of` behind it, or refuses. An answer that is silent about its own freshness is the failure being prevented; whether the underlying data is *recent enough* is a separate judgment (HB-13b). | `HARD_INVARIANT` (declared coverage or refusal) | `PRODUCT` | A (A1.5 §K) + C |
| **HB-13b** | **Per-surface freshness acceptance.** For each data surface in pilot scope, the operator confirms the freshness is fit for the questions that surface will be asked, and the §27 JLL conditions hold for the surfaces they govern. **Split from Draft 1's HB-13**, which fused a product-wide invariant with a per-surface human judgment. A stale surface removes *that* capability, not the pilot. | `HUMAN_ACCEPTANCE_REQUIRED`; `pilot_operational_requirement: external_gate_closure` | `CAPABILITY` | C, grounded in A1.5 §K + B (§27) |

## 7. Soft warnings

Acceptable imperfections during a pilot, provided they are **known, bounded, visible to
the user, and instrumented**. Each is P1 or P2 — none blocks the pilot. **[C]**

| ID | Imperfection | Severity | Bound |
|---|---|---|---|
| SW-1 | Coverage gaps — the Analyst cannot answer some legitimate questions. | P2 | Must fail *loudly* ("no tengo datos gobernados para esto"), never plausibly. |
| SW-2 | Over-clarification — asks for disambiguation slightly too often. | P2 | `THRESHOLD_TO_CALIBRATE` — measured on the pilot's own traffic, not fixed in advance. Over-clarifying is strictly preferable to guessing (HB-4). |
| SW-3 | Verbosity / phrasing quality below target. | P2 | Judged by `output_usefulness`; monitored, not gating. |
| SW-4 | Latency above target on multi-step investigations. | P1 | `BASELINE_RELATIVE`, see §23. |
| SW-5 | Inconsistent formatting between similar answers. | P2 | Tracked via feedback, not gating. |
| SW-6 | The long-tail SQL path answers a question the governed path should have owned. | P1 | Allowed but must be traced and reviewed weekly (§13). |
| SW-7 | `conversational_quality` is permanently unscored on turns where the deterministic layer cannot compute it. | P2 | Known, narrow, documented gap **[B]** (blueprint §I, judge policy). The judge must **never** fill it. |
| SW-8 | Deterministic reports (§26) not yet built. | P2 | The pilot may launch chat-only; but then §26's claims must not be made to users. |
| SW-9 | A gate or dimension that does **not** back a P0 blocker is present but never fires (the demoted half of Draft 1's HB-11). | P1 | Must be *listed* as not-covered in the entry-gate record, so nobody reads its presence as coverage. Zero tolerance still applies to P0-backing gates (HB-11). |
| SW-10 | Judge-scored dimensions disagree with each other, or with a human reviewer, on the same turn. | P1 | Expected, not alarming: the sources record that LLM judges over-report success and are swayed by the agent's own reasoning, while rule-based checks under-report it (**S**, `04_cs329t...md` *Agent Evals Survey* slide 38). Disagreement is a calibration input (XC-3), not a defect — provided no judge is gating (SY-6). |

## 8. Data readiness

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| DR-1 | Every entity and period the pilot surface exposes has verified coverage — the Analyst knows *which periods exist* per metric/entity and never extrapolates past them. | P0 | `HARD_INVARIANT` (coverage check precedes answer) |
| DR-2 | Coverage/freshness are answerable *as questions*: "¿hasta qué mes tienes datos de vacancia de PT?" must be answerable. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` (operator confirms on the task bank) |
| DR-3 | Metrics gated by open business decisions are unreachable, not merely caveated (see HB-9). | P0 | `HARD_INVARIANT` |
| DR-4 | Raw versioned tables are always read with the `superseded_at IS NULL` filter **[B]** (`CLAUDE.md`, A1.5 §J). | P0 | `HARD_INVARIANT` (enforced in the governed dataset layer, not in prompt text) |
| DR-5 | Excluded entities stay excluded: Machalí (divested), Guardiamarina, Placilla **[B]** (project memory / `dim_activo` deletions). A pilot answer naming them as current portfolio is a data-readiness failure. | P0 | `ZERO_TOLERANCE` |
| DR-6 | The baseline-gated `tests` check has zero new regressions against the active 19-item historical known-failure allowlist; when a known failure is fixed, the allowlist shrinks. The immutable `d986996` artifact remains historical evidence, not the active baseline. | P0 | `ZERO_TOLERANCE` on *new* failing IDs (baseline-relative set comparison, per blueprint §M) |
| DR-7 | **[D]** Which entities/periods constitute the pilot's declared scope is an open decision — the full portfolio, or a named subset (e.g. PT + Apo4501/4700 + Apo3001 + Viña + Curicó) chosen for data confidence. | — | `HUMAN_ACCEPTANCE_REQUIRED` |

## 9. Semantic readiness

Per A1.5 §F, there must be exactly **one** semantic authority. **[A]**

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| SR-1 | Every metric the pilot exposes has a complete Metric Contract entry (`metric_id`, semantic/method version, formula reference, entity grain, `value_unit`, aggregation, temporal contract, valid entities/scopes, precedence/eligibility, lineage expectations, null semantics, invariants) **[A]** A1.5 §H. | P0 | `HARD_INVARIANT` (incomplete ⇒ not `active` ⇒ unreachable) |
| SR-2 | Business definitions are never invented by the LLM at answer time. If a definition is not in the contract, the Analyst says so. | P0 | `ZERO_TOLERANCE` on model-invented definitions |
| SR-3 | Prompts contain linguistic guidance only — no formulas, no aliases, no physical source names **[A]** A1.5 §F (`prompts: RUNTIME_ONLY`). | P1 | `HARD_INVARIANT` by review at pilot entry |
| SR-4 | No aggregation of ratios or snapshots, no mixing of units **[A]** A1.5 A2 Entry Gates invariants. | P0 | `HARD_INVARIANT` (dataset contract forbids the aggregation) |
| SR-5 | `renta_uf` is a **rate**, not a total **[B]** (project memory; `docs/rent-roll-renta-semantics-v1.md`; migration 091 splits it into `renta_semantica` / `renta_total_uf` / `renta_uf_m2`). Note the catalog still declares the pre-cutover definition at `tools/datasets/catalog_v1.yaml:59`, deliberately, pending cutover **[B]**. The pilot must not expose a rent-rate metric whose contract and catalog disagree. | P0 | `HARD_INVARIANT` |

## 10. Entity / metric / period resolution

Blueprint §N requires entity/period correctness be measured at the **component** level,
not only via final-answer gates F2/C3 — because a case can pass the outcome gate by
accident. **[A]** This standard adopts that unchanged.

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| ER-1 | Component-level entity resolution correctness on the pilot task set. | P0 | `THRESHOLD_TO_CALIBRATE` — blueprint §N proposes ≥98%; calibrate as the lower bound of a ≥3-run measurement before fixing, per its treatment of factual≥95%. Silent *guessing* is separately `ZERO_TOLERANCE` (HB-4). |
| ER-2 | Component-level period resolution correctness, including the CDG quarter-offset rules **[B]** (`CLAUDE.md`: CDG marzo → EEFF dic del año anterior, etc.). | P0 | `THRESHOLD_TO_CALIBRATE` (same method as ER-1) |
| ER-3 | Metric resolution correctness — a dedicated component score, which does not exist today **[B]** (blueprint §F: "no dedicated test found"). | P1 | `THRESHOLD_TO_CALIBRATE` |
| ER-4 | Ambiguity is surfaced, not resolved by preference. `Apoquindo` is ambiguous across `Apo` (fondo), `Apo4501`, `Apo4700`, `Apo3001` (which belongs to `TRI`), and the legacy `Fondo Apoquindo` scope **[B]**. | P0 | `ZERO_TOLERANCE` on silent selection |
| ER-5 | Conversational carry-over of entity/metric/period is explicit in the trace (`resolution method: explicit \| inherited-context \| inferred`, per blueprint §K). | P0 | `HARD_INVARIANT` (trace field required) |
| ER-6 | **[D]** Whether `Apoquindo` unqualified should default to the `Apo` fund scope or always clarify is an open product decision. This standard's default proposal is: **always clarify at pilot** **[C]**, on the grounds that a wrong default here is expensive and a clarification is cheap. |

## 11. Planning and investigation

Trajectory quality is evaluated per blueprint §G. **There is no gold path** — deterministic
trajectory gates fire only on the anti-patterns below. **[A]**

| Anti-pattern | Definition | Severity | Policy tag |
|---|---|---|---|
| **AP-1 Repeated identical action** | Same `(tool, args)` re-invoked with no intervening state change justifying it. | P1 | `BASELINE_RELATIVE` (count not worse than baseline) |
| **AP-2 Loops** | Same `(tool, args)` re-invoked with no new information and no recorded justification, until either the turn ends without an answer or the agent stops without acknowledging the failure. **Revised:** Draft 1 set this at "3+ times", which was an invented number. The sources are explicit that repetition is judged by *purpose*, not count — the Execution Efficiency rubric permits verification steps and inline-evaluation steps that "provide unique feedback, serve as sanity checks, or use a demonstrably different approach", and penalises only repetition that adds nothing (**S**, `04_cs329t...md` *Agent GPA* slide 11). Unproductive repetition that still ends in a correct, acknowledged outcome is now an efficiency concern (P1); repetition that ends in an unacknowledged failure is already AP-3/AP-5. | P1 (efficiency) / P0 via AP-3 when it ends in silence | `BASELINE_RELATIVE` on repetition counts; the P0 remains on AP-3/AP-5 |
| **AP-3 Ignored tool error** | A tool errors or returns empty and the next action neither retries differently, reformulates, nor surfaces it to the user. | P0 | `ZERO_TOLERANCE` (this is the direct path to fabrication) |
| **AP-4 Ignored validator result** | The result validator flags a concern and the agent proceeds unchanged. | P0 | `ZERO_TOLERANCE` — conditional on the validator existing (§14) |
| **AP-5 Premature stopping** | An answer is returned though a required fact was never fetched by any tool call in the trace. | P0 | `ZERO_TOLERANCE` (equivalent to fabrication at the trajectory level) |
| **AP-6 Redundant querying after sufficient evidence** | Further tool calls after all required facts are present, with no new question or ambiguity. | P2 | `BASELINE_RELATIVE` |

Explicitly **not** anti-patterns, per blueprint §G's own amendment **[A]**: a tool call
whose result isn't quoted in the final answer (defensive verification is legitimate), and
any ordering that differs from a notional dependency graph.

Investigation depth requirement **[C]**: for the "why" family of questions (§17), a
single-query answer is *itself* a planning failure — either the agent investigates, or it
declares the evidence insufficient. **P0**, `ZERO_TOLERANCE` on single-query causal
assertions.

### Plan quality and replanning (added in this revision)

Draft 1 evaluated the trajectory only through deterministic anti-patterns. The sources
identify a failure surface it did not cover at all: **the plan itself, and the justification
for changing it**. Both are directly relevant to Toesca, because the multi-step questions
the pilot exists to serve (§17, §11) are exactly where an unjustified replan produces a
confident wrong answer. **[S]**, from `04_cs329t_knowledge_pack_all.md` *Agent GPA* slides
13 and 17, and `01_building_and_evaluating_data_agents.md` Lessons 5–6:

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| PQ-1 | Where the agent plans, the plan is recorded in the trace as structured steps, not as free prose, and each step names what it will establish. The source's own intervention was to add explicit goal / precondition / postcondition per step, which improved both plan adherence and groundedness (`01_...md` Lesson 6). Adopting that shape for Toesca is **[C]**. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` at review |
| PQ-2 | A replan is accompanied by a recorded trigger (an error, an empty result, new information). An unjustified replan is the trajectory-level form of an unexplained change of mind, and the source rubric treats it as a plan-quality failure. | P1 | `THRESHOLD_TO_CALIBRATE` (judge-scored; monitored only, per SY-6) |
| PQ-3 | Plan quality is **not** judged against a reference plan. Consistent with P5 and with `07_...md` §3 ("Prefer grading outcomes over enforcing one exact reasoning path"), it is judged against the goal and the *available tools* — the source explicitly scopes plan quality to the planner's knowledge of available resources, ignoring execution outputs (`04_...md` slide 13). | P1 | — |
| PQ-4 | Plan *adherence* is judged step-by-step: an omitted or partially executed planned step is a failure of adherence **regardless of whether the final answer happened to be right** (`04_...md` slide 17). This is the same logic as P12 and PE-23 (right number, wrong query). | P1 | `THRESHOLD_TO_CALIBRATE` |

**Inline (runtime) evaluation — deferred, deliberately.** `01_...md` Lesson 6 demonstrates
feeding a retrieval-quality score back into the executor so it can decide to investigate
further, and reports the honest tradeoff: groundedness and plan adherence improved, while
**execution efficiency and logical consistency got slightly worse** — more work, more
latency, better answers. This is a real design option for the Analyst and it is recorded
here so A2–A5 can choose it knowingly. It is **not** a pilot requirement **[C]**: it adds
per-turn model calls, and its cost lands directly on §23, which has no baseline yet.

## 12. Tool use

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| TU-1 | `tool_selection` and `tool_arguments` are scored **separately**, per blueprint §F/§O ("stop using tool correctness as a single blended metric"). | P1 | `THRESHOLD_TO_CALIBRATE` per sub-dimension (blueprint §N's ≥95% is the starting proposal, not an accepted number) |
| TU-2 | Every pilot-relevant eval case declares `tool_requirements`, so the deterministic denominator stops shrinking silently **[A]** blueprint §N. | P1 | `HARD_INVARIANT` on new cases |
| TU-3 | Tool results carry structured metadata: row count, empty flag, error, `value_unit`, provenance, dataset/metric contract ref **[A]** blueprint §K + A1.5 §I/J. A tool returning a bare number is defective (P11). | P0 | `HARD_INVARIANT` (schema-enforced) |
| TU-4 | Tool descriptions and argument schemas are written for the model as reader; ambiguous tool pairs are disambiguated in their descriptions, not in the system prompt. **The review criterion is distinctness, not tool count** — `02_a_practical_guide_to_building_agents.pdf` p. 16 records that some deployments handle more than fifteen well-defined distinct tools while others struggle with fewer than ten overlapping ones. No tool-count threshold is set here, because the sources give a reason not to. **[S]** | P1 | `HUMAN_ACCEPTANCE_REQUIRED` (review at pilot entry) |
| TU-5 | Governed tools/datasets are preferred over the SQL long tail whenever a governed path exists; long-tail use where a governed path existed is logged as SW-6. Motivated by P14 **[S]** and by the fact that the governed path is where units, provenance and precedence are declared. | P1 | `BASELINE_RELATIVE` (share of turns using long tail, trended) |
| TU-6 | Tool errors are returned to the agent in an actionable form — what failed, and what a valid call would look like — not as an opaque exception. An unactionable error is a direct cause of AP-2/AP-3. **[S]** `07_...md` §2 ("Make errors actionable"); `04_cs329t...md` *Agent GPA* slide 11 penalises repeated attempts caused by "easily correctable input errors". | P1 | `HUMAN_ACCEPTANCE_REQUIRED` (review at pilot entry) |

## 13. SQL long-tail requirements

The controlled Text-to-SQL path is the pipeline's escape hatch. It is allowed at pilot,
under conditions. **[C]**, structurally grounded in A1.5 §L.

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| SQ-1 | Read-only, enforced by the SQLite authorizer, not by regex. `tools/analyst_runtime/actions.py::validate_sql()` is documented as **UX only**; the authorizer is the boundary **[B]** (blueprint §B.7). | P0 | `HARD_INVARIANT` |
| SQ-2 | Allow-listed surface, parameterized, row/time bounded, fully audited **[A]** A1.5 §L. | P0 | `HARD_INVARIANT` |
| SQ-3 | The long-tail path returns the **same result contract** as governed tools — entity/scope, metric/method version, period/as-of, unit, quality, structured citations **[A]** A1.5 §L. A long-tail answer with weaker provenance than a governed answer is not acceptable. | P0 | `HARD_INVARIANT` |
| SQ-4 | Every emitted statement is captured in the trace with text, row count, and tables hit **[A]** blueprint §K — noting that table-hit inspection is a *fallback* provenance signal, never the primary one. | P0 | `HARD_INVARIANT` |
| SQ-5 | SQL correctness is gradeable as its own component: generated SQL, executed, returns the same result set as the case's `ground_truth_refs` SQL — so a right-number-by-coincidence case is caught **[A]** blueprint §F. | P1 | `THRESHOLD_TO_CALIBRATE` |
| SQ-7 | The long-tail path depends on a **semantic model of the data**, not on the model reading column names. `01_building_and_evaluating_data_agents.md` Lesson 3 describes the text-to-SQL service as relying on a semantic model file declaring what columns mean, what values mean, and common synonyms — i.e. the same object A1.5 §F calls the Semantic Registry. **[S]** This does not change SQ-2/SQ-3; it changes their justification, and it gives OD-3 a technical criterion rather than an appetite question: exposure of the long tail should be conditioned on the semantic layer existing, not on willingness to risk it. | P0 | `HARD_INVARIANT` (no semantic layer for a domain ⇒ no long tail in that domain) |
| SQ-6 | **[D]** Whether the long-tail path is enabled for pilot users at all, or restricted to the operator, is an open decision. **Still open** — the sources inform the criterion (SQ-7) but cannot make a Toesca product decision. Proposal **[C]**: enabled, but every long-tail turn is flagged in the trace and reviewed in the weekly pilot review (§28). |

## 14. Result validation

`RESULT_VALIDATION` is a genuine gap: **no result-validation component exists in the
runtime or the eval today** **[B]** (blueprint §D/§F; flagged for A3).

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| RV-1 | Empty result sets are never rendered as a business fact ("la vacancia fue 0%"). An empty set must produce an explicit "no hay datos para ese período/entidad." | P0 | `ZERO_TOLERANCE` |
| RV-2 | A suspicious zero, a sign flip, or a value outside the metric's declared invariants (A1.5 §H) is surfaced, not silently reported. | P0 | `ZERO_TOLERANCE` on silent pass-through of invariant violations |
| RV-3 | Unit mismatch between the retrieved evidence and the reported answer is blocked (HB-6). | P0 | `ZERO_TOLERANCE` |
| RV-4 | A full validator component with an anomaly-injection harness (blueprint §F) is **not** a pilot blocker. RV-1..RV-3 are the minimum subset. | P2 (full validator) | `THRESHOLD_TO_CALIBRATE` post-pilot |
| RV-5 | **[C]** Minimum viable validator for pilot: empty-set check, null/zero check against the metric's declared null semantics, unit equality check, coverage check ("is this period within declared coverage?"), and the RV-6 relevance check. Anything richer is P2. | P0 (this subset) | `HARD_INVARIANT` |
| RV-6 | **Result relevance.** A non-empty result is checked against the *resolved* (entity, metric, period, grain) tuple before it is used — "the query executed" is not "the query answered the question asked". Added in this revision: Draft 1 covered emptiness, nulls, units and coverage but had no check that the returned slice is the slice the user asked for. **[S]** — the RAG-Triad's *context relevance* leg, applied to a data agent's retrieval steps (`01_...md` Lesson 4), and the three separately-named failures in `04_cs329t...md` Lecture 3 slides 38–40 (retrieval failure ≠ lack of groundedness ≠ answering the wrong question). Toesca's deterministic form of the check — comparing the resolved tuple against the result's own declared entity/metric/period metadata (TU-3) rather than scoring relevance with a model — is **[C]**, and is cheaper and more reliable than the source's LLM-judge implementation because Toesca's results are structured. | P0 | `HARD_INVARIANT` (tuple equality against result metadata) |
| RV-7 | Cardinality and duplication: a result whose row count contradicts the metric's declared grain (one row per period expected, many returned; or duplicate keys after a join) is flagged rather than aggregated. Follows from A1.5 §H grain declarations **[A]**; it is the failure that turns a correct query into a silently double-counted total. | P1 | `THRESHOLD_TO_CALIBRATE` |

## 15. Evidence / provenance

Every factual answer ships an **evidence package**. **[C]**, composed from A1.5 §J/§L and
blueprint §K.

| ID | Requirement | Severity |
|---|---|---|
| EV-1 | Answer states: entity/scope, metric + method version, period + `as_of`, unit, and quality/coverage. | P0 |
| EV-2 | Answer states its **source provenance** — provider, source-as-of, precedence policy/version — from structured tool evidence, not from table names **[A]** A1.5 §J, blueprint §E. | P0 |
| EV-3 | A pilot user can inspect the evidence without asking a developer. The mechanism (expandable panel, footnote, "ver evidencia" affordance) is a UX decision **[D]**; that *some* mechanism exists is P0. | P0 (existence), P2 (form) |
| EV-4 | `unknown` provenance is explicit, never invented **[A]** A1.5 §J. Rows carrying the `legacy_unknown` sentinel from migration 089 **[B]** must not be laundered into a confident source claim. | P0 |
| EV-5 | **[D]** The publication threshold for `legacy_unknown` provenance is an open business decision **[B]** (A1.5 §P.5). Until decided, proposal **[C]**: such rows may be counted in aggregates only if the answer discloses the unknown-provenance share. |

Policy tags: EV-1, EV-2, EV-4 are `HARD_INVARIANT` (structurally attached to the result
contract, not measured as a rate). EV-3 existence is `HUMAN_ACCEPTANCE_REQUIRED`.

## 16. Synthesis quality

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| SY-1 | No claim in the answer that isn't traceable to a tool/SQL result from the same turn (groundedness). | P0 | `ZERO_TOLERANCE` for numeric/business claims; judge-scored `grounding` is P1 monitoring |
| SY-2 | Numeric restatement is exact: the number in the prose equals the number in the evidence, with declared rounding. | P0 | `ZERO_TOLERANCE` |
| SY-3 | Completeness — every part of a multi-part question is addressed or explicitly deferred. | P1 | `THRESHOLD_TO_CALIBRATE` (deterministic `required_facts` presence) |
| SY-4 | No internal jargon leakage (table names, column names, `fondo_key` internals, tool names) in the user-facing answer. | P1 | `THRESHOLD_TO_CALIBRATE` — the presentation holdout **[B]** already graded this dimension manually |
| SY-5 | Appropriate brevity for the question asked. | P2 | `BASELINE_RELATIVE` |
| SY-6 | Judge-scored dimensions (`analytical_quality`, `grounding`, `hallucination`, `clarification_judgment`, `investigation_quality`, `output_usefulness`) are **monitored, not hard-blocking**, until repeated-run judge variance has been measured **[A]** judge policy + blueprint §N. This revision found external corroboration rather than a reason to change it: judges must be calibrated against human annotation and re-run to measure consistency before they are trusted (**S**, `07_...md` §3; `04_cs329t...md` *Agent GPA* slides 27 and 30, which measure both human-score alignment and cross-run consistency as separate properties). The published agreement figures in that deck are properties of *that* judge on *that* benchmark and are **not** adopted as Toesca targets. | P1 | `THRESHOLD_TO_CALIBRATE` (N≥3 runs; the ±0.5-on-0–4 tolerance in the judge policy is explicitly provisional, not established) |
| SY-7 | For non-deterministic behaviour, the repeated-run statistic is chosen to match what matters: **P0 gates are scored on consistency across all trials** (a single violation in any trial is a violation), while quality dimensions are scored on the mean across trials. **[S → C]** — `07_...md` §3 ("choose metrics based on whether occasional success or consistency matters"); the assignment of which Toesca metric gets which treatment is a decision made here. | P1 | `THRESHOLD_TO_CALIBRATE` |

## 17. Unsupported causality policy

The single most dangerous class of answer for an analytical product, because it is the
most useful-sounding. Blueprint gate C4, judge-decided. **[A]**

| ID | Rule | Severity | Policy tag |
|---|---|---|---|
| UC-1 | A causal claim ("el NOI cayó **porque** se fue un arrendatario") requires evidence in the trace that *decomposes* the change and attributes it. | P0 | `ZERO_TOLERANCE` on unsupported causal assertion |
| UC-2 | Correlation language must not be upgraded to causal language in synthesis. | P0 | `ZERO_TOLERANCE` |
| UC-3 | When evidence is insufficient, the required behavior is an explicit statement — "la evidencia disponible no permite atribuir la causa; lo que sí puedo mostrar es la descomposición X/Y/Z" — plus what *would* be needed. | P0 | `HARD_INVARIANT` (required response shape) |
| UC-4 | Decomposition (which line items / which units / which tenants moved) **is** a legitimate and encouraged answer to a "why" question; it is not the same as asserting a cause. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` at review |
| UC-5 | UC-1..UC-3 are judge-decided (C4) per blueprint §I. Because judge variance is unmeasured, the pilot additionally requires **operator spot-review of every "why" turn** during the pilot's first phase **[C]**. This revision strengthens the rationale rather than the rule: a documented LLM-judge failure mode is agreeing with an agent's own stated reasoning even when it is wrong (**S**, `04_cs329t...md` *Agent Evals Survey* slide 38), which is exactly the shape of a fluent unsupported causal claim. A judge is therefore the weakest possible sole arbiter for this specific gate. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |

## 18. Clarification behavior

| ID | Rule | Severity | Policy tag |
|---|---|---|---|
| CB-1 | Clarify rather than guess whenever entity, metric, or period is genuinely ambiguous (P6). | P0 | `ZERO_TOLERANCE` on silent guessing |
| CB-2 | Clarification questions are specific and offer the actual candidates ("¿Apo4501, Apo4700, o el fondo Apo completo?"), never generic ("¿puedes ser más específico?"). | P1 | `HUMAN_ACCEPTANCE_REQUIRED` at review |
| CB-3 | An unambiguous question is answered directly — over-clarification degrades usefulness. | P2 | `THRESHOLD_TO_CALIBRATE` (`clarification_judgment`, judge-scored, monitored only per SY-6) |
| CB-4 | A declared, reasonable substitution ("no tengo julio, uso junio, el último disponible") is preferable to a clarification round-trip **when the substitution is disclosed** — this is the blueprint's C3 "declared substitution" carve-out **[A]**. | P1 | `HARD_INVARIANT` on disclosure |

## 19. Conversation-state behavior

| ID | Rule | Severity | Policy tag |
|---|---|---|---|
| CS-1 | Follow-ups inherit prior entity/metric/period correctly ("¿Y Apoquindo?" keeps the metric and period, swaps the entity). | P0 | `THRESHOLD_TO_CALIBRATE` (deterministic against expected resolved state) |
| CS-2 | A user correction **overwrites** state; the corrected fact is never re-used. This is blueprint gate F5 — which is **implemented, has cases, and is dead in `runner.py`** (`correction_ctx` hardcoded to `None`) **[B]**. | P0 | `ZERO_TOLERANCE` on ignored corrections; and `HARD_INVARIANT` that the gate is demonstrated firing (HB-11) |
| CS-3 | Topic reset is honored — a new subject does not silently drag old filters. | P0 | `THRESHOLD_TO_CALIBRATE` |
| CS-4 | Multi-turn success is defined precisely, per blueprint §N's correction: "fraction of multi-turn cases with zero gate violations across all turns," not a vague aggregate. | P1 | `THRESHOLD_TO_CALIBRATE` (blueprint's ≥90% is a starting proposal only) |
| CS-5 | Context is a designed artifact per turn, not an accumulating transcript (P10). Long sessions must not degrade resolution correctness. | P1 | `BASELINE_RELATIVE` (compare turn-1 vs turn-N resolution correctness) |

## 20. Safety

The most mature category in the stack **[B]** (blueprint §D).

| ID | Rule | Severity | Policy tag |
|---|---|---|---|
| SF-1 | Read-only enforcement via the shared authorizer (HB-2). | P0 | `HARD_INVARIANT` |
| SF-2 | Session isolation across pilot users (HB-3). | P0 | `ZERO_TOLERANCE` |
| SF-3 | Every `/api/*` route remains authenticated (`X-Ingesta-Token` **[B]**, `scripts/ingesta_server.py`); pilot users reach the Analyst through the authenticated server, never `file://`. | P0 | `HARD_INVARIANT` |
| SF-4 | Confidentiality: fund/asset data must not leave the deployment boundary beyond what the model provider already receives. **[D]** — whether pilot conversations may be retained by the provider, and under what data-processing terms, is an open decision requiring a human owner. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| SF-5 | Any authorizer denial in production is alerted on, with a nonzero count treated as an incident **[A]** blueprint §H. | P0 | `ZERO_TOLERANCE` |
| SF-6 | The pilot does not weaken the holdout isolation: no holdout content, IDs, or reconstructed question shapes enter the pilot task bank **[A]** blueprint §J. | P0 | `ZERO_TOLERANCE` |
| SF-7 | Every tool exposed to the Analyst carries a recorded risk rating derived from write access, reversibility, permissions required, and financial impact. Today every rating is *low* because the surface is read-only (HB-2) — which is precisely why this product's guardrail surface can be as narrow as it is. The requirement exists so that the first tool with side effects re-opens the question deliberately rather than by omission. **[S]** `02_...pdf` p. 26 ("Tool safeguards"), which ties risk rating to pausing or escalating to a human; `05_...md` §5.3 (bounded tool authority: the model may *request*, the application validates and executes). Recording the ratings is **[C]**. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` (review at pilot entry) |
| SF-8 | Guardrails are layered, not singular: a deterministic gate, a judge, and a human review each cover what the others miss, and none is treated as sufficient alone. **[S]** `02_...pdf` p. 25: *"a single one is unlikely to provide sufficient protection"*. This is already the shape of §6 + §16 + §28; SF-8 states it so it is not simplified away later. | P1 | — |

## 21. Operational reliability

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| OR-1 | Runtime error rate over pilot traffic. Blueprint §N correctly classifies this as an **operational monitoring metric, not a pre-release gate** (pre-release volume is too low for a 2% figure to mean anything) **[A]**. | P1 | `BASELINE_RELATIVE` + `THRESHOLD_TO_CALIBRATE` on rolling pilot-traffic windows |
| OR-2 | A failed turn degrades explicitly ("no pude completar esto"), never into a plausible answer (P3). | P0 | `ZERO_TOLERANCE` |
| OR-3 | Provider errors, timeouts, and retry exhaustion are captured in the trace with reason codes. | P0 | `HARD_INVARIANT` |
| OR-4 | Conversation persistence survives a server restart — pilot users must not lose their work. `tools/analyst_workspace/` exists for exactly this **[B]**. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` (operator verifies restart behavior) |
| OR-5 | A documented rollback: how the pilot is turned off, and who can do it, within one working session. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| OR-6 | Load-bearing CI exists on protected branch `feat/alpha-v0.1`: required checks are `tests` (baseline-gated), `eval/benchmark/tests` (100% green), and `eval/product_alpha/tests` (100% green). | P1 | `HUMAN_ACCEPTANCE_REQUIRED` — **[C]** the remaining decision is whether passing these required checks is an explicit pilot-readiness evidence condition. See §29 EG-9 and OD-12. |

## 22. UX / product reliability

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| UX-1 | Login, session, and the Analyst surface are stable for the named pilot users. Login/auth and `/analyst` are active surfaces today **[B]**. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| UX-2 | Errors are legible to a non-developer. No stack traces, no raw tool errors. | P0 | `HARD_INVARIANT` |
| UX-3 | The user can see that the Analyst is working (progress/streaming), given multi-step investigations will not be instant. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` |
| UX-4 | Conversation history is browsable and exportable. `export_markdown.py` exists **[B]**. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` |
| UX-5 | The Analyst-first shell (Analyst as primary entry, factsheet as a capability reached from it) is **approved but not yet implemented** **[B]** (`docs/ROADMAP.md`). Not a pilot blocker. | P2 | — |
| UX-6 | The pilot's *scope of competence* is visible to the user — the user should be able to see what it can and cannot answer, so SW-1 failures aren't experienced as random. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` |

## 23. Latency expectations

Per P9, latency is optimized after quality but must be **measured** before it is argued
about. There is **no cost/latency baseline today**: the `Usage` dataclass has the fields
but the Track A adapter leaves token counts `None` **[B]** (blueprint §C.8).

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| LA-1 | Per-turn latency (p50/p95) is recorded, split by whether the turn involved tool calls **[A]** blueprint §H. | P0 | `HARD_INVARIANT` (field populated) |
| LA-2 | Token counts and cost per turn are populated — currently a known gap **[B]**. | P1 | `HARD_INVARIANT` (field populated) once done; the *number* is `BASELINE_RELATIVE` |
| LA-3 | A latency baseline is measured on the task bank **before** the pilot, and pilot latency is judged against it, never against an invented target. Corroborated **[S]**: `02_a_practical_guide_to_building_agents.pdf` p. 8 sequences model selection as *set up evals to establish a baseline → meet the accuracy target with the best available model → only then optimize cost and latency by substituting smaller models*. That ordering is the same as P9, and it means a pilot that ships without a baseline forfeits the ability to make any later model or architecture change defensibly. | P1 | `BASELINE_RELATIVE` |
| LA-5 | Any quality mechanism that adds per-turn model calls (inline evals, additional judges, self-verification) has its latency and token cost attributed to it in the baseline before it is adopted. The one measured example available reports the tradeoff in both directions at once — better groundedness and plan adherence, worse execution efficiency (**S**, `01_...md` Lesson 6). | P1 | `BASELINE_RELATIVE` |
| LA-4 | **[C]** A qualitative pilot bar: a simple lookup should feel like a query, a multi-step investigation may feel like a task, and the user must be told which one is happening (UX-3). No absolute second-count is set here, deliberately. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` |

## 24. Observability / traceability — Pilot Trace Contract

Blueprint §K defines the eval trace. This section makes the **pilot-launch judgment** the
blueprint did not make: which subset must exist before pilot, and which can wait. This
split is new **[C]**; the field list itself is **[A]** blueprint §K + A1.5 §J.

Pilot status values are `MUST_FOR_PILOT` (shown as **MUST**), `SHOULD_FOR_PILOT` (**SHOULD**),
and `LATER`.

**Governing test for this contract**, restated from HB-10: the trace of an analytically
consequential turn must let someone who was not present reconstruct
`entity → metric → period → plan → tool → query → result → validation → evidence →
synthesis` well enough to say *which* of those steps produced a wrong answer. A field earns
`MUST` by being necessary for that reconstruction, not by being available. **[C]**

Two fields were **added in this revision** on source evidence (`span_type`, `app_version`);
one requirement was **narrowed** (universal → consequential turns, HB-10). Nothing was
removed.

| Field | Pilot status | Why |
|---|---|---|
| `turn_id`, `session_id`, `timestamp` | **MUST** | Nothing is attributable without it |
| `app_version` (agent/prompt/tool-registry version identifying this build) | **MUST** | **Added in this revision.** Without it, pilot traffic cannot be compared before and after a change, which is the entire point of collecting it. **[S]** `01_...md` Lessons 4 and 6: the app is registered with a name *and version*, and the whole improvement loop of Lesson 6 consists of comparing the same records across two versions. `07_...md` §3 makes the same point via regression evals. |
| `span_type` per recorded step (`planning` / `routing` / `retrieval` / `tool_use` / `generation`) | **MUST** | **Added in this revision.** A flat event list makes the groundedness, result-relevance (RV-6) and context-quality checks unimplementable, because nothing marks *which* steps produced the evidence the answer must be grounded in. **[S]** `01_...md` Lesson 4 identifies retrieval spans specifically as the ones carrying the evaluation inputs, and annotates them with `query_text` and `retrieved_context`. Toesca's equivalent of a retrieval span is a governed tool result or an executed SELECT — this is a labelling requirement, not new telemetry. |
| `user_turn_text` | **MUST** | Reproduction |
| `resolved_entity` (id + method: explicit/inherited/inferred) | **MUST** | HB-4, ER-5 |
| `resolved_metric` (id + method) | **MUST** | HB-9, SR-1 |
| `resolved_period` (value + method, incl. quarter-offset rule applied) | **MUST** | HB-5, ER-2 |
| `planner_decision` (tool / clarify / direct answer + structured reason code) | **MUST** | §11 attribution; not free-text rationale, and never private chain-of-thought |
| `tool_calls[]` with `{tool_name, args, result_metadata(row count, empty?, error?), latency_ms, provenance(provider, precedence policy/version, source-as-of, value_unit), contract ref}` | **MUST** | TU-3, EV-2, HB-6, HB-7 |
| `sql_statements[]` `{text, result_row_count, tables hit}` | **MUST** | SQ-4 (fallback provenance signal only) |
| `final_answer_text` | **MUST** | Grading |
| `citations / evidence` (which resolved facts the answer claims) | **MUST** | SY-1, EV-1 |
| `latency_ms_total` | **MUST** | LA-1 |
| `model`, `provider` | **MUST** | Comparability across runs |
| `retries[]` `{reason, outcome}` | **MUST** | AP-3, OR-3 |
| `validator_outcome` (pass / flagged:`reason_code` / not_run) | **MUST** for the RV-5 minimum subset; `not_run` allowed for richer checks | §14 |
| `tokens {input, output, reasoning, cached}` | **SHOULD** (P1) | Known gap **[B]**; needed for LA-2, not for safety |
| `gate_results` (F1–F5, C1–C5) | **SHOULD** for pilot traffic; **MUST** for benchmark runs | Judge gates cost money per turn; §28 samples them |
| `dimension_scores` with deterministic-vs-judge flag | **SHOULD** for pilot traffic; **MUST** for benchmark runs | Same reason |
| `judge_model`, `rubric_version`, `judge_impl_version` | **MUST** wherever a judge verdict is persisted **[A]** judge policy | Comparability rule |

Explicitly **`LATER`** — recorded so their absence is a decision rather than an oversight
**[C]**: per-step model reasoning content (never stored; `planner_decision` carries a
structured reason code instead, per §24 above), inline-evaluation scores (§11, deferred),
approval/handoff events (no approvals or handoffs exist in a single-agent read-only
product — `05_...md` §6 lists both as observability targets, and they are simply not
applicable here **[S → C]**), and full OpenTelemetry span export.

Standardization rule **[A]** blueprint §K: this is one trace shape across benchmark runs
and production logging — do not invent a second format. The `span_type` labelling above is
compatible with that rule and with OpenTelemetry-style span typing, which is how the source
implementation carries it (`01_...md` Lesson 4) — but adopting an OTEL-compatible exporter
is a `LATER` decision, not a pilot requirement **[C]**.

## 25. Feedback capture

Real infrastructure already exists **[B]**: `/pilot-feedback`, `/pilot-control`,
message-level feedback, and feedback-report markdown export (`docs/CURRENT_STATE.md`).

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| FB-1 | A user can flag a bad answer in one action, at the message level, without leaving the Analyst. | P0 | `HARD_INVARIANT` |
| FB-2 | A flag captures the **trace**, not just the text — otherwise the report is an anecdote. | P0 | `HARD_INVARIANT` |
| FB-3 | Flagged failures are triaged into exactly one primary failure class from the blueprint §D taxonomy. **[A]** | P0 | `HUMAN_ACCEPTANCE_REQUIRED` (weekly, §28) |
| FB-4 | A classified, reproducible failure becomes a new dev-set case with SQL `ground_truth_refs` — never a free-text expectation **[A]** blueprint §J. Independently corroborated **[S]**: `07_...md` §3 and its closing checklist both state that eval tasks should be drawn from manual tests, bugs and real user failures, and that production failures should become new eval cases; `05_...md` §17.2 step 4 is the same loop (inspect failures → update → rerun → automate). This is the mechanism that makes the pilot worth running at all, and it is `pilot_operational_requirement: weekly_triage`, not a taxonomy dimension. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` |
| FB-5 | The production→eval loop **does not exist today** **[B]** (blueprint §C.6/§J: `eval/alpha_eval_v1` and the presentation holdout are one-shot artifacts). For pilot, a *manual* loop (FB-3 + FB-4 executed weekly by the operator) is acceptable; automation is P2. | P0 (manual loop), P2 (automation) | `HUMAN_ACCEPTANCE_REQUIRED` |
| FB-6 | Positive signal is captured too — otherwise the pilot only learns what's broken and can't tell what's worth keeping. | P2 | — |

## 26. Deterministic reports readiness

Per `docs/ROADMAP.md` "Product Shell & Reporting v1" — **approved target, not yet
implemented** **[B]**. Three named reports: Informe de Vacancia, Informe de Recaudación,
Informe de Ingresos. The required shape:

```
button / Analyst tool → deterministic report generator → governed dataset / SQL
   → validation → HTML template → report        (NO LLM, no model API in this path)
```

This architecture is not merely a convenience. It is the direct application of P14: where
the analytical path is fully known — one scope, one period, one governed dataset, one
layout — putting an LLM in that path adds variance and removes reproducibility while buying
nothing. **[S]** `05_openai_api_agents_consolidated_knowledge.md` §5.5 ("Workflow… best
when the path is known") and §15 Level 1; `02_a_practical_guide_to_building_agents.pdf`
p. 6 ("Otherwise, a deterministic solution may suffice"). The same sources are also the
reason the *chat* path is agentic: the analyst's ad-hoc question does not have a known
path. The two coexist by design, not by indecision. **[S → C]**

**If the pilot ships without reports, that is acceptable (SW-8, P2).** If it ships *with*
them, this bar applies **[C]**:

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| RP-1 | Zero LLM/model API calls in the generation path **[B]** (ROADMAP). | P0 | `HARD_INVARIANT` |
| RP-2 | Byte-level reproducibility: the same inputs and the same period produce the same report. This is the property that makes a deterministic report worth more than a chat answer. | P0 | `HARD_INVARIANT` |
| RP-3 | The report uses the **same** governed semantic/dataset contract as the Analyst — not a second metrics implementation **[B]** (ROADMAP). A number that differs between report and chat is a P0 defect. | P0 | `ZERO_TOLERANCE` on report-vs-chat divergence for the same metric/entity/period |
| RP-4 | Every figure in the report carries provenance and coverage, same contract as §15. | P0 | `HARD_INVARIANT` |
| RP-5 | Validation runs before rendering; a failed validation blocks the report rather than rendering a caveat. | P0 | `HARD_INVARIANT` |
| RP-6 | **Informe de Vacancia** is blocked on the UG treatment decision — migration 090 makes `UG` a visible category but the inclusion decision is open **[B]**. A vacancy report cannot ship with an undeclared UG policy. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| RP-7 | **Informe de Recaudación**: `raw_cartera_line` (aging buckets) and `raw_recaudacion` exist and are lineage-complete **[B]**, but `tasa_recaudacion` is deliberately **not derivable** — no invoice/document linkage exists to make it a real cohort rate **[B]**. The report must not contain a collections *rate*. | P0 | `ZERO_TOLERANCE` on publishing an undefined rate |
| RP-8 | **Informe de Ingresos** is the least advanced of the three **[B]** — a data-quality improvement to an existing path, not a new capability. Ship last or not at all for pilot. | P2 | — |
| RP-9 | The Analyst invokes the *same* generator (e.g. `generate_vacancy_report(scope, period)`), never a parallel LLM-driven path **[B]** (ROADMAP). | P1 | `HARD_INVARIANT` when the integration exists |

## 27. JLL / data freshness requirements

**Three independent claims must be kept distinct.** Compressing them to "JLL done" or "JLL
not started" is wrong in both directions. All three verified **[B]**:

**(1) Implemented and tested in source.** Migrations `085`–`091` exist in
`tools/db/migrations/` (091 is the highest in the repo): typed renta semantics +
provenance (085), three governed provider-agnostic tables `raw_movimiento_contable_line` /
`raw_cartera_line` / `raw_recaudacion` (086), versioned internal ER rules
`dim_er_regla_interna` (087), ER lineage with trigger-enforced coherence (088),
deterministic idempotent provenance backfill with a `legacy_unknown` sentinel (089), `UG`
as its own vacancy category (090), and `v_rent_roll_semantic` rebuilt into three explicit
fields (091). Supporting code: `tools/jll_planilla_tools.py`,
`tools/db/ingest_jll_planilla.py`, `tools/db/derive_er_jll_v2.py`, `tools/db/er_reglas.py`,
`tools/db/repo_jll_v2.py`, `tools/db/repo_rent_roll.py`. ~70 new test functions across
three test files plus 4 schema invariants. The upload path is wired into the live ingesta
UI with format auto-detection — not CLI-only.

**(2) Gated off production.** Production remains on schema `84`; **085–091 are not applied
to production**. A separate readiness effort exists on `feat/jll-v2-production-readiness`
(preflight gating, hermetic Playwright E2E, cutover runbook, a separable catalog-cutover
commit that must be applied *only* at cutover and requires schema ≥ 91). Its external gate
manifest (`docs/jll-v2-external-gate-manifest.yaml`) currently has **all eight items
`pending` with null evidence**: `archivo_oficial_jll`,
`fecha_corte_rent_roll_convencion`, `apo3001_seguro`, `tratamiento_ug`,
`mappings_pendientes`, `apo3001_ing_taipei_vs_otros`, `reconciliacion_2026_06`,
`contribuciones_aceptacion`. The preflight only *reads* this manifest and never writes it;
any `pending` item is a blocker by construction.

**(3) In the snapshot, not Analyst-queryable.** Zero code changes in
`tools/analyst_runtime/` or `web/analyst.html` are associated with the JLL v2 pipeline.
**The Analyst cannot query the new JLL v2 tables or views today.** The data is populated in
sandbox but not wired to the Analyst — a "not wired up yet" state, not a bug in either
component.

Pilot requirements that follow **[C]**:

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| JL-1 | The pilot must not *claim* rent-roll/recaudación/cartera coverage the Analyst cannot actually query. Whatever the Analyst can answer must match what is wired, exactly. | P0 | `ZERO_TOLERANCE` on overclaimed coverage |
| JL-2 | If the pilot includes rent-roll-derived answers, then: all eight external-gate items are `resolved` with non-empty evidence, the cutover is executed per the runbook, **and** the catalog cutover commit is applied in the same change (it requires schema ≥ 91). Partial application is a P0 defect — the catalog and the schema must never disagree (SR-5). | P0 | `HUMAN_ACCEPTANCE_REQUIRED` + `HARD_INVARIANT` |
| JL-3 | If the gate items are not resolved, the pilot ships **without** JLL-v2-dependent capabilities, and those questions are refused explicitly rather than answered from pre-v2 data with v2 semantics. | P0 | `ZERO_TOLERANCE` |
| JL-4 | The rent-roll cut-off convention (`fecha_corte_fuente`: día-1 vs fin de mes) is unresolved **[B]** (A1.5 §K; gate item `fecha_corte_rent_roll_convencion`). Any rent-roll answer must disclose the convention used. | P0 | `HARD_INVARIANT` (disclosure) |
| JL-5 | Freshness is stated in every answer: "datos al `<as_of>`". "Latest" means the last *eligible observation of that metric* per the temporal contract, never `MAX(periodo)` globally **[A]** A1.5 §K. | P0 | `HARD_INVARIANT` |
| JL-6 | **[D]** Who owns obtaining the official JLL file and resolving the eight gate items, and by when, is an open ownership question. It is the single most likely cause of pilot delay. |

## 28. Pilot operator / support requirements

A pilot without a named operator is a demo. **[C]**

| ID | Requirement | Severity | Policy tag |
|---|---|---|---|
| OP-1 | A named **pilot operator** exists, with explicit responsibility for triage, weekly review, and the stop decision. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| OP-2 | Named pilot users (proposal **[C]**: 3–6, enough for signal, few enough to support) who know they are in a pilot, know it can be wrong, and know how to flag. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| OP-3 | A weekly review: flagged failures triaged to a taxonomy class (FB-3), new cases written (FB-4), long-tail SQL turns reviewed (SW-6), and every "why"/causal turn spot-checked (UC-5). | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| OP-4 | A response-time expectation for pilot users when something breaks, so they don't silently stop using it. | P1 | `HUMAN_ACCEPTANCE_REQUIRED` |
| OP-5 | Users are told, in writing, what the Analyst is *not* authorized to be used for during the pilot — proposal **[C]**: no external reporting, no investor communication, no decision of record without independent verification. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |
| OP-6 | The operator does **not** need to watch sessions live (§2.3). If they do, the pilot is not ready. | P0 | `HUMAN_ACCEPTANCE_REQUIRED` |

## 29. Entry gate

The pilot starts only when **all** of the following are demonstrated. Each maps to sections
above; nothing here is new.

| # | Entry condition | Evidence required |
|---|---|---|
| EG-1 | All §6 `PRODUCT`-scope blockers satisfied (HB-1..HB-8, HB-10, HB-11 P0-backing, HB-12, HB-13a). Every `CAPABILITY`-scope blocker (HB-9, HB-13b, HB-11 non-P0) either satisfied, **or** its capability removed from the pilot surface and refused explicitly. | Written check per item, with the artifact that proves it, plus the list of removed capabilities |
| EG-2 | Every gate/guard backing a P0 blocker demonstrated **firing** at least once (HB-11 / P13); every non-P0 gate that does not fire is *listed* as uncovered (SW-9). | Liveness check output + uncovered list |
| EG-3 | The P0 subset of `PILOT_TASK_BANK_V0.md` executed end-to-end, with ground truth finalized for those tasks. | Run artifacts + a `NEEDS_VALIDATION` count of zero **for the P0 subset only** |
| EG-4 | Component-level entity/period/metric resolution measured, with thresholds calibrated (ER-1..ER-3) — not assumed. | ≥3-run measurement, per blueprint §N |
| EG-5 | Trace `MUST_FOR_PILOT` fields (§24), including `app_version` and `span_type`, populated on every **analytically consequential** turn (HB-10). | Trace sample inspection, including one reconstruction walk-through of a deliberately wrong answer |
| EG-6 | Feedback loop live: flag → trace captured → triage path defined (FB-1..FB-3, FB-5). | Operator walkthrough |
| EG-7 | Latency/cost baseline measured (§23). | Baseline artifact |
| EG-8 | JLL/freshness position explicitly chosen (JL-2 **or** JL-3) and true. | Gate manifest state + wiring check |
| EG-9 | Evidence that the required CI checks pass: `tests` is baseline-gated with zero new regressions against the active 19-item known-failure allowlist, and `eval/benchmark/tests` plus `eval/product_alpha/tests` are 100% green (DR-6). | Required-check output. Whether this evidence is an explicit Pilot Readiness Gate condition remains OD-12 **[C]** |
| EG-10 | Operator and users named; §28 in place. | Written sign-off (HB-12) |

## 30. Stop-the-pilot conditions

Any single occurrence stops the pilot immediately, pending root cause. **[C]**, derived
from the ZERO_TOLERANCE set.

| # | Condition | Policy tag |
|---|---|---|
| SP-1 | Any fabricated business fact reaches a user. | `ZERO_TOLERANCE` |
| SP-2 | Any write attempt or authorizer denial from the Analyst path. | `ZERO_TOLERANCE` |
| SP-3 | Any cross-session/user data leak. | `ZERO_TOLERANCE` |
| SP-4 | Any answer using a forbidden source (HB-7) or a domain-gated metric (HB-9). | `ZERO_TOLERANCE` |
| SP-5 | Any unsupported causal claim that a user acted on, or would plausibly have acted on. | `ZERO_TOLERANCE` |
| SP-6 | Trace loss — an analytically consequential turn served without a reconstructible trace (HB-10). | `ZERO_TOLERANCE` |
| SP-7 | A user reports being unable to tell whether an answer was right, and the evidence package does not let the operator resolve it either. | `HUMAN_ACCEPTANCE_REQUIRED` |
| SP-8 | Sustained error rate or latency degradation making the product unusable. | `BASELINE_RELATIVE` |
| SP-9 | A pilot user quietly stops using it. Not a failure of the software, but a failure of the pilot — investigate before continuing. | `HUMAN_ACCEPTANCE_REQUIRED` |

## 31. Exit criteria / graduation from pilot

The pilot **ends** — successfully — when it has produced what it was for. **[C]**

| # | Exit criterion | Policy tag |
|---|---|---|
| XC-1 | Enough real traffic to characterize failure modes by taxonomy class, not by anecdote. | `THRESHOLD_TO_CALIBRATE` — the volume needed is set from observed failure-class diversity, not fixed in advance |
| XC-2 | Every distinct failure class observed has at least one dev-set regression case with SQL ground truth (FB-4). | `HARD_INVARIANT` |
| XC-3 | Judge repeated-run variance measured (N≥3), so judge-based metrics can finally become gates **[A]** judge policy. | `THRESHOLD_TO_CALIBRATE` |
| XC-4 | Latency/cost characterized well enough to argue architecture tradeoffs honestly (P9). | `BASELINE_RELATIVE` |
| XC-5 | Pilot users state, unprompted, that they would keep using it. | `HUMAN_ACCEPTANCE_REQUIRED` |
| XC-6 | The set of questions the Analyst *should* own but doesn't is enumerated — the real roadmap input. | `HUMAN_ACCEPTANCE_REQUIRED` |
| XC-7 | Graduation to broader internal use requires the P1 items in this standard to move to satisfied, including evidence that the existing required CI checks pass (OR-6). | `HUMAN_ACCEPTANCE_REQUIRED` |

## 32. Open decisions

**None of these was closed by the external sources read in §34, and none can be.** Each is
a Toesca business, product, legal, or ownership decision. Where a source informs the
*criterion* for deciding (OD-1's "smallest useful slice", OD-3's semantic-layer
precondition), that is noted at the item and changes nothing about who must decide.

| # | Open decision | Owner needed | Blocking? |
|---|---|---|---|
| OD-1 | Pilot data scope — full portfolio or a confidence-selected subset (DR-7). The sources lean toward the narrower slice (a bounded, useful, observable first test — `05_...md` §§2.3–2.5; "start small, validate with real users" — `02_...pdf` p. 32) **[S]**, but the choice of *which* Toesca entities and periods is a data-confidence judgment only Toesca can make. **Remains open.** | Product + data owner | Yes, for EG-3 |
| OD-2 | `Apoquindo` unqualified: always clarify, or default to the `Apo` fund scope (ER-6). | Product | Yes |
| OD-3 | Is the SQL long tail exposed to pilot users at all (SQ-6)? Now has a technical precondition (SQ-7: no semantic layer ⇒ no long tail in that domain) **[S]**, which narrows the question but does not answer it. **Remains open.** | Product + eng | Yes |
| OD-4 | Provider data-retention / confidentiality terms for pilot conversations (SF-4). | Legal / compliance | Yes |
| OD-5 | Publication threshold for `legacy_unknown` provenance (EV-5) **[B]** A1.5 §P.5. | Data owner | Yes, if any affected metric ships |
| OD-6 | UG treatment in vacancia **[B]** A1.5 §P.3 / migration 090 / gate item `tratamiento_ug`. | Gestión de renta business owner | Yes, for vacancia + RP-6 |
| OD-7 | `dy_amort` denominator and Apo parameterization **[B]** A1.5 D30. | Rentabilidad/fondos business owner | Only if returns metrics ship |
| OD-8 | Financing metrics methodology — LTV/DSCR/net debt/duration inputs, look-through, caja, as-of, amortization **[B]** A1.5 D16/D33. | Riesgo/finanzas business owner | Only if those metrics ship |
| OD-9 | Mall Curicó ER rows without `cuenta_codigo`: reject, quarantine, or publish as explicitly unclassified **[B]** A1.5 §P.4. | ER/contabilidad business owner | Only if Curicó ER ships |
| OD-10 | Rent-roll `fecha_corte` convention (JL-4). | JLL relationship owner | Yes, if rent roll ships |
| OD-11 | Ownership and timing of the eight JLL external-gate items (JL-6). | Named human | Yes, if JL-2 path chosen |
| OD-12 | Must passing the existing required CI checks be an explicit Pilot Readiness Gate condition/evidence requirement? CI already exists and is load-bearing (OR-6/EG-9) **[C]**. | Eng lead | Decides EG-9's form |
| OD-13 | Evidence-inspection UX form (EV-3). | Product/design | No (form is P2) |
| OD-14 | Number of pilot users (OP-2) and pilot duration. | Pilot operator | Yes |
| OD-15 | Whether deterministic reports are in pilot scope at all (§26 / SW-8). | Product | No — either path is acceptable |

## 33. Source rationale

| Claim family | Where it comes from | Tag |
|---|---|---|
| Failure taxonomy (DATA…INFRA), gates F1–F5/C1–C5, judge dimension split, trajectory anti-patterns, trace schema, Reliability Core threshold discipline, CI gate design | `docs/toesca-analyst-eval-observability-blueprint-v1.md` §D/E/F/G/H/I/K/M/N — **reused, not re-derived**. The extensions this document relies on (splitting `tool_correctness`; standalone SQL and unit dimensions) are the blueprint's *own* justified extensions (§F, §O), not new ones. | A |
| Judge authority, no-silent-fallback, version pinning, calibration-before-release, unmeasured variance | `docs/toesca-analyst-llm-judge-policy-v1.md` | A |
| Entity/Metric/Dataset/Source/Temporal contracts; `resolved\|ambiguous\|unknown`; single semantic authority; publication boundary; A2 entry gates; open business decisions | `docs/toesca-data-foundation-target-contract-v1.md` §F–L, §P, closeout amendment | A |
| Product state: load-bearing CI on `feat/alpha-v0.1`; JLL v2 triple disposition; reports not built; Analyst-first shell approved-not-built; `renta_uf` semantics debt; feedback surfaces shipped; legacy surfaces still present | `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/superpowers/plans/2026-08-28-jll-v2-production-readiness.md`, `.worktrees/jll-v2-production-readiness/docs/jll-v2-external-gate-manifest.yaml` | B |
| Fund/asset key conventions; `Apo3001 ∈ TRI`; `superseded_at` filtering; CDG quarter offsets; "no usar el CDG"; excluded assets; server auth | `CLAUDE.md`, project memory, `docs/matriz-claves-ambiguas-apoquindo.md` | B |
| Context engineering as design (P10); tools as a product surface and actionable tool errors (P11, TU-4, TU-6); outcome-and-trajectory evaluation (P12); determinism-before-autonomy (P14, §26); judge calibration and judge failure modes (P15, SY-6, SY-7, UC-5, SW-10); retrieval/groundedness/relevance separation (P16, RV-6); plan quality and justified replanning (PQ-1..PQ-4); `span_type` and `app_version` in the trace (§24); repetition judged by purpose not count (AP-2); semantic model as a precondition for text-to-SQL (SQ-7); baseline before optimization (LA-3, LA-5); single-agent before multi-agent (§3) | **External sources read in this revision** — see §34 for the per-file inventory, nature, and what each actually supports. Each claim is cited inline by filename and section/lesson/slide/page. | S |
| Pilot definition and success criteria; hard-blocker selection; severity assignment; the MUST/SHOULD trace split; the "why"-question investigation rule; operator requirements; stop conditions; exit criteria; whether passing existing required CI checks is an explicit readiness-gate condition | Judgment calls made in this document. Contestable; several are surfaced as open decisions in §32. | C |
| Everything in §32 | Deliberately unresolved; needs a named human. | D |

---

## 34. External sources — inventory and disposition

**This section supersedes Draft 1's "Missing sources" note, which is no longer true.**
Draft 1 was written before these materials were available and stated, correctly at the
time, that seven external course/framework sources were not present locally; principles
drawn from them were tagged `A(general)` with nothing specific attributed. In this revision
all seven were supplied as a read-only research bundle and **all seven were read**. The
`A(general)` tag has been retired and replaced by **S** with concrete per-claim citations.

The bundle is a research input only. It is **not** part of this repository, is not tracked
by Git, was not copied into the worktree, and is not a Toesca governing document. Nothing
in it can close a Toesca open decision (§32).

| # | File | Nature (per the bundle's own manifest) | Read? | What it actually supports here | Limitations |
|---|---|---|---|---|---|
| 01 | `01_building_and_evaluating_data_agents.md` | Course transcript and notebook code (DeepLearning.AI / Snowflake, *Building and Evaluating Data Agents*) | **Yes** — Intro, Lessons 1–6 transcripts and notebook narrative | The RAG-Triad applied to data agents (P16, RV-6); GPA framing (P12, §11); trace spans typed by step with retrieval spans carrying eval inputs, and app versioning for before/after comparison (§24); inline/runtime evaluation and its measured tradeoff (§11, LA-5); text-to-SQL depending on a semantic model file (SQ-7) | It is a course built on one vendor stack (Snowflake Cortex, LangGraph, TruLens). The *concepts* transfer; the tooling choices are not adopted. Its reported metric values are demo runs on a sales dataset and are never used as Toesca targets. |
| 02 | `02_a_practical_guide_to_building_agents.pdf` | Practical guide to building agents (OpenAI) | **Yes** — extracted to text and read in full (33 pp.); page numbers cited from the document's own footer | Single-agent-first (§3); tool distinctness over tool count (TU-4); tool-risk rating and layered guardrails (§20, HB-2); baseline-before-optimization in model selection (LA-3); human intervention early in deployment (HB-12); "otherwise a deterministic solution may suffice" (P14, §26) | Vendor guide with SDK-specific code; the code and SDK primitives are not adopted. Its guardrail catalogue (PII, moderation, jailbreak classifiers) is largely aimed at consumer-facing assistants and is only partially relevant to an internal read-only analyst. |
| 03 | `03_workflows_and_agents.txt` | Workflows and agents material — in fact LangChain/LangGraph documentation on workflow patterns (prompt chaining, parallelization, routing, orchestrator-worker, evaluator-optimizer, agents) | **Yes** — read; predominantly framework code | Reinforces the workflow-vs-agent distinction behind P14. **Contributed no independent requirement**, and is cited nowhere as sole support for a criterion. Recorded here rather than dressed up as more than it is. | It is framework documentation, not evaluation guidance. Its patterns are implementation shapes, and Toesca's architecture decision (single agent + governed tools + deterministic reports) is already made elsewhere. |
| 04 | `04_cs329t_knowledge_pack_all.md` | Consolidated Stanford CS329T knowledge pack — per-slide extractions of ten lecture decks, with explicit visual-context flags where text extraction is incomplete | **Yes** — index and concept map; Lecture 2 (trustworthiness, RAG triad); Lecture 3 (agentic patterns, RAG failure modes); Guest Lecture *Agent GPA* (slides 1–42, including the appendix Agent Evals Survey); Lecture 10 overview | The GPA judge decomposition and its rubrics — Plan Quality, Plan Adherence, Execution Efficiency, Logical Consistency, Tool Selection, Tool Calling (§5 mapping, §11 PQ-1..PQ-4, AP-2); grounding defined as every claim being attributable (HB-1); judge benchmarking, judge/human alignment, judge cross-run consistency, and named judge failure modes (P15, SY-6, UC-5, SW-10); the three separable RAG failures (P16) | It is a **slide extraction**, not a paper or a transcript: many slides are diagrams whose semantics the text does not carry, and the pack flags this itself. Reported figures (error-coverage and localization agreement, benchmark precision/recall) are properties of the cited papers' systems on their benchmarks; none is used as a Toesca threshold. The pack also notes one deck is missing and that source 02 was deliberately excluded from it. |
| 05 | `05_openai_api_agents_consolidated_knowledge.md` | **Consolidation** of two OpenAI Academy presentations into one retrieval-friendly document — explicitly a consolidation with slide-page attributions, not the original decks | **Yes** — read in full, with §§2, 4.4, 5.3–5.6, 6, 13, 14, 15, 17 used | Smallest-capability-first and bounded first test (§2, OD-1 framing); autonomy only when evals show a fixed path fails, and the Level 1→3 architecture progression (P14, §26); bounded tool authority and human control for risky/ambiguous actions (§20, HB-12); the observability field list (§24); "retrieval does not fix every failure" (§14); eval = dataset + model + grader + metrics, and what to grade for tools and agents (§12, §16) | A consolidation of presentations, so wording is paraphrased even where page numbers are given; it is cited as a consolidation, never as a primary OpenAI publication. Its conversation-state and SDK-orchestration material is API-specific and not adopted. |
| 06 | `06_mcp_build_rich_context_ai_apps_anthropic.md` | Course transcript and notebooks, *MCP: Build Rich-Context AI Apps with Anthropic* (DeepLearning.AI / Anthropic) | **Yes** — Intro, Lesson 2 (architecture and primitives), Lessons 8–9 (host integration, remote servers); remaining lessons are implementation walkthroughs | Only two things, both minor and neither load-bearing: the tools/resources/prompts primitive split as a way to think about read-only context exposure, and the observation that human-in-the-loop approval is a property of the *host application*, not of the tool layer. **No pilot criterion rests on this source.** | It is a protocol-implementation course. Toesca does not use MCP today, and this revision does not propose adopting it. Presenting it as evaluation or quality guidance would be a misuse of it. |
| 07 | `07_anthropic_agent_engineering_context_tools_evals.md` | **Paraphrased digest** of three Anthropic Engineering articles (context engineering; writing tools for agents; demystifying evals for agents). The bundle states explicitly that it is a digest, not a verbatim copy | **Yes** — read in full | Context as a scarce designed resource (P10); tool definitions as prompt design and actionable errors (P11, TU-6); outcome *and* trace evaluation, capability vs regression evals, grading outcomes rather than one reasoning path, repeated trials with a metric chosen for consistency vs occasional success, judge calibration against humans, and production failures becoming eval cases (P12, P15, PQ-3, SY-7, FB-4) | **A digest.** Every citation to it in this document is a citation to the digest, not to the original articles, and is worded accordingly. It contains no figures, examples, or exact wording from the originals; where precision matters, the original articles must be consulted. |

**Sources not accessible: none.** No file in the bundle failed to open or parse. The PDF
(source 02) required text extraction; the extraction succeeded and was read in full,
including page-footer numbering, which is why page references to it are given.

### What the sources changed, and what they did not

Changed a criterion: AP-2 (repetition judged by purpose, not an invented count); HB-10
(reconstructibility of consequential turns, not universal logging); HB-11 (scope-aware);
HB-13 (split); §24 (`span_type`, `app_version` added; `LATER` list made explicit); §14
(RV-6 result relevance added; RV-7 cardinality); §11 (plan quality / justified replanning
added, inline evals explicitly deferred with their cost); §12 (TU-4 reframed away from tool
counts, TU-6 added); §13 (SQ-7); §16 (SY-7 trial statistic); §23 (LA-5).

Confirmed without change: P1/P2 judge authority, SY-6 monitored-not-gating, UC-5 human
layer, §26 deterministic-report architecture, §3 single-agent, LA-3 baseline-first, FB-4
failures-become-cases, and the entire evidence/provenance contract in §15.

Explicitly **not** changed by the sources: every open decision in §32 remains open; no
external figure has been adopted as a Toesca threshold; the JLL triple distinction in §27
is unchanged because no new *repository* evidence appeared; and no source was used to
justify a requirement that does not change a decision or a criterion.
