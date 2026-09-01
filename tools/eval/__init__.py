"""Eval-foundation infrastructure: baseline-aware pytest gating.

This package is intentionally decoupled from the `automation_agent` runtime
(db_chat, tools/registry, etc.) — it only ever reads pytest's own reporting
output (JUnit XML, and the JSON produced by `pytest_nodeid_reporter`) and
compares it against committed baseline/allowlist JSON files. It must never
call into the system under test or any LLM/judge.
"""
