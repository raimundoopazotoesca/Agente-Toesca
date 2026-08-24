# Generic Canonical Semantic Core v1 — Design

## Goal

Introduce a provider-neutral semantic surface between Analyst actions and the read-only SQLite data layer. The surface decides metric authority, entity identity, valid temporal aggregation, coverage, units, and lineage deterministically. It does not alter the database, UI, prompts, or existing guards.

## Architecture

`Analyst action adapter → SemanticQuery → AnalyticsExecutor → MetricDefinition + EntityDefinition → read-only source → ToolEvidence → existing synthesis/guards`.

`SemanticQuery` contains a canonical metric identifier, typed entity IDs, a month or inclusive month range, an optional requested aggregation, and optional requested display unit. It represents business intent only; it has no SQL, provider, action, or metric-name-specific fields.

`MetricDefinition` declares the canonical identity and display metadata, permitted entity types, native time grain, metric nature (`flow`, `point_in_time`, `ratio`, `other`), native and presentation units, source strategies in priority order, permitted temporal/entity aggregations, coverage policy, and lineage metadata. Exactly one source strategy may be canonical for each logical metric/entity-grain contract. A catalog lint rejects ambiguity.

`EntityDefinition` is loaded from canonical entity metadata. It includes ID, entity type, canonical name, typed aliases and optional validity. Entity resolution first narrows by expected entity type and only then applies exact canonical-name/alias matching; metric observations are never an entity catalog.

The executor resolves definitions before any query. It validates type, period/range, aggregation, and source authority, runs only the canonical source through the existing read-only sandbox, calculates only catalog-authorized aggregations, validates requested coverage, and emits one structured result with source lineage. It contains no checks on concrete metric or entity names.

## Initial catalog instances

NOI is a monthly `flow`, authoritative at fund and asset grain, with `sum` permitted over a contiguous range. LTV and vacancy retain their audited real semantics as point-in-time/ratio values and reject `sum`. A fourth existing governed metric is added through metadata to demonstrate that executor/action/prompt/formatter code does not grow with a compatible metric.

The contract records `native_unit` and `display_unit`; conversion execution is deliberately excluded. The product-wide UF presentation default remains a later presentation/conversion stage.

## Evidence invariant

Every new quantitative value in a synthesis must bind by exact structured fields to `ToolEvidence`. Aggregated results produce evidence containing the aggregate value, input period coverage, the canonical source, formula/version and observed lineage. Follow-up resolution may continue an investigation, but it may not create an unbound numeric claim. Existing canonical, coverage, and provenance guards remain fail-closed and are extended only through generic evidence fields if necessary.

## Compatibility

Existing Analyst actions remain adapters. They translate their existing tool schema to `SemanticQuery`, preserving browser/provider compatibility while moving all semantic decisions to the executor and catalog. No `/api/chat`, legacy query module, prompts, UI, database migration, or database write is in scope.

## Testing and acceptance

Tests cover NOI/PT/TRI/Apoquindo/asset regressions, LTV and vacancy, a same-process clarification continuation, generic synthetic flow and point-in-time contracts, uniform invalid aggregation rejection, typed aliases, one fourth real metric configured only through metadata, catalog authority lint, and unbound quantitative-claim rejection. A semantic holdout is frozen before implementation and run only after code freeze. Provider-real smoke traces must show governed action, structured evidence, and intact guards. The Alpha regression is run without prompt tuning.
