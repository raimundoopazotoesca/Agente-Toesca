# F4 Governed Analytics — Stage 0.5 and Stage 1 Design

## Scope

Build two isolated foundations: an Alpha Product Eval for product regressions and a governed metric catalog. Neither changes the agent runtime, prompts, tools, database schema, benchmark, or provider integration.

## Baseline and boundaries

The baseline is `589ebb13c672334db38d76db05dac5a7240a494c` on `feat/alpha-v0.1`. Its only delta from B.3 is the temporary deliverable-sufficiency experiment in `ALPHA_EVIDENCE_INSTRUCTION`; it remains unmodified and is not an architectural dependency.

The knowledge database remains read-only. The benchmark is not imported, edited, or re-fingerprinted. `tools/analyst/semantic_loader.py` and `semantic/` remain legacy and are not a source for the new catalog.

## Alpha Product Eval

`eval/product_alpha/` owns a small YAML case format, loader, typed trial/result records, and deterministic offline graders. Cases specify user turns, purpose, deterministic and semantic expectations, prohibited outcomes, optional capability requirements, and tags. They do not prescribe SQL, tool order, round count, or exact prose.

The initial eight cases encode canonical-source, driver-ranking, entity-resolution, coverage-claim, follow-up, presentation, simple-lookup, and raw-exploration regressions. A trial is an input record produced later by any runtime adapter; multiple trials for one case can be evaluated independently and aggregated without imposing a single trajectory. No runner invokes an agent or a provider.

## Governed metric catalog

`tools/analytics/` owns typed immutable definitions plus a versioned YAML catalog. A metric definition includes its key, display name, description, unit, entity and period grain, source kind, structured access strategy, aggregation behavior, permitted dimensions, status, and related metric keys. It contains no current values or duplicated entities.

Access strategies are structured contracts: `derived_kpi` identifies a KPI plus its fixed entity type, while `view_metric` identifies a DB view and value column. They are data only, deliberately not an executor and not free SQL. Stage 2 can later combine these contracts with a scope and period to generate parameterized SQL.

The initial metrics are independent economic quantities:

- `vacancia_pct_fondo`: canonical, `derived_kpi`, fund × month, percent, non-additive/governed; TRI June 2026 is represented by the database's `vacancia_pct` value 5.945 with formula `vacancia_ponderada_fondo_rentas_manual` and ingest run 142.
- `vacancia_fisica_pct_activo`: breakdown, `v_vacancia_activo.vacancia_pct`, asset × month, percent, non-additive.
- `m2_vacantes`: breakdown, `v_vacancia_activo.m2_vacantes`, asset × month, square metres, additive only across a compatible asset scope.

`related_metrics` supports navigation only. It does not grant equivalence, substitution, or aggregation rights.

## Validation and verification

Both loaders fail fast on malformed YAML and cross-reference errors. Catalog validation rejects duplicate keys, unknown relations, invalid enum values, invalid grain, malformed access strategy, and catalog value fields. Tests use temporary YAML fixtures for negative paths and the actual catalog for its consumer-visible contract.

The deliverable is split into exactly two implementation commits: Alpha Product Eval, then governed metric catalog. The design and implementation plan are included in the first commit as the auditable Stage 0.5 design record; no separate commit is created.
