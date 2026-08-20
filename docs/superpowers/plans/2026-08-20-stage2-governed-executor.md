# Stage 2 Governed Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile and execute governed read-only metric queries offline.

**Architecture:** Typed request validation resolves one catalog metric to fixed SQL templates; `LiveReadOnlySandbox` executes bound parameters and maps rows into semantic envelopes.

**Tech Stack:** Python, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-stage2-governed-executor-design.md`

## Global Constraints

- One metric only; no deltas, arbitrary SQL, agent wiring, provider calls, or DB writes.
- Every unsupported semantic operation fails closed.

### Task 1: Tests

- [ ] Write failing executor tests for scalar, breakdown/ranking, physical vacancy, invalid semantics, deterministic output, provenance, and DB hash.
- [ ] Run `python -X utf8 -m pytest tests/analytics/test_executor.py -q` and observe import failure.

### Task 2: Executor

- [ ] Implement request/result models, fixed compiler templates, and sandbox execution.
- [ ] Re-run new and isolation regression suites; commit only Stage 2 files.
