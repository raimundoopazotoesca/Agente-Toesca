"""Provider-neutral F4 reasoning runtime (extracted from eval/benchmark/adapters).

Submodules:
  base           -- Turn / ToolCall / Usage / Artifact
  transport      -- ModelTransport contract (ModelRequest/ModelResponse/ToolSpec/...)
  analyst_loop   -- AnalystLoop / LoopResult (the reasoning loop itself)
  actions        -- Action / ActionRegistry / RunSqlAction / SqlSandbox protocol
  sqlite_guard   -- shared read-only sqlite3 authorizer
  live_sandbox   -- LiveReadOnlySandbox (production DB, read-only)

This package has zero dependency on eval.benchmark.* and zero dependency on
any provider SDK (openai, anthropic). It is imported BY eval/benchmark's
adapters (track_b_*.py), not the other way around.
"""
