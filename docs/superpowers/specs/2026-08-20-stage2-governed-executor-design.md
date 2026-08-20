# Stage 2 Governed Analytics Executor

`tools/analytics` gains an offline, read-only executor. A request names exactly one catalog metric, optional fund/asset scope, a point or range period, and optional grouping/order/limit. The compiler accepts only catalog-defined `derived_kpi` and `view_metric` strategies and binds every caller value.

Every result row carries metric key, entity id/type, period, value, unit, source kind, and provenance; the result carries catalog version. Invalid metrics, dimensions, aggregation requests, and unsupported grouping fail closed with `SemanticQueryError`. No runtime, registry, prompts, benchmark, or database schema changes are in scope.
