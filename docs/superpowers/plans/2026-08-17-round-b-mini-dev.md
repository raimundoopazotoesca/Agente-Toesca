# Round B Mini-Dev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the frozen Mini-Dev once per B1_STANDARD candidate with auditable telemetry and deterministic-only grading.

**Architecture:** `InferenceProfile` is injected at Track B construction and turns provider response metadata into neutral `Usage`. A Round B runner owns frozen-manifest validation, retries, persistence, deterministic grading and run-manifest construction; it does not change Track B semantics.

**Tech Stack:** Python 3.12, pytest, OpenAI-compatible clients, YAML/JSON, SQLite snapshot sandbox.

**Spec:** `docs/superpowers/specs/2026-08-17-round-b-mini-dev-design.md`

## Global Constraints

- Do not modify `eval/round_b/mini_dev_v1.yaml`, its freeze or Dev cases.
- Verify canonical Mini-Dev SHA `dc4d8912986ac99e9a08853d55fa19668220032e41a89944c05d1cfcc573b976`.
- Use B1_STANDARD exactly: Groq explicitly `reasoning_effort=medium`; all sampling fields omitted; no high/max.
- Commit code and obtain a clean tree before creating the live Run Manifest or calling a provider.
- One retry only for 429/5xx/network/timeout; no fallback or semantic retry.

---

### Task 1: Inject immutable B1 inference profiles into Track B

**Files:**
- Modify: `eval/benchmark/adapters/track_b_frontier.py`
- Modify: `eval/benchmark/adapters/base.py`
- Test: `eval/benchmark/tests/test_track_b.py`

**Interfaces:**
- Produces: `InferenceProfile`, `B1_STANDARD_PROFILES`, `resolve_b1_standard_profile(provider, model)`.
- Produces: `Usage` fields for resolved model, reported token categories and retries.

- [ ] **Step 1: Write failing tests** for profile resolution, omitted sampling fields, explicit Groq medium reasoning and provider-reported usage.
- [ ] **Step 2: Run the targeted test module** and confirm failure because profile support does not yet exist.
- [ ] **Step 3: Add frozen profile registry and request kwargs builder**, then pass it through `TrackBFrontier` to `_TrackBSession` without touching prompt/tool-loop logic.
- [ ] **Step 4: Extract only reported usage fields** from OpenAI-compatible responses; leave unavailable token fields as `None` and never retain reasoning content.
- [ ] **Step 5: Re-run Track B tests** and confirm green.

### Task 2: Build an offline Round B runner and run manifest

**Files:**
- Create: `eval/round_b/runner.py`
- Test: `tests/round_b/test_runner.py`

**Interfaces:**
- Consumes: frozen manifest YAML, `TrackBFrontier`, `score_turn`, `pricing.yaml`.
- Produces: `RoundBRunner.create_run_manifest()`, `RoundBRunner.run_candidate()`, JSONL turn records and run summary.

- [ ] **Step 1: Write failing tests** for canonical freeze validation, Run Manifest required fields, profile pinning, price calculation and one eligible retry.
- [ ] **Step 2: Run the new test module** and confirm expected missing-module failure.
- [ ] **Step 3: Implement pure manifest, pricing, error-taxonomy and serialization helpers**, including hashes over UTF-8 canonical JSON and source files.
- [ ] **Step 4: Implement candidate execution** with the frozen order, new session per case, one eligible retry and deterministic scoring. Persist raw final output, SQL, tool trace and neutral telemetry only.
- [ ] **Step 5: Re-run new tests** and the existing Round B tests.

### Task 3: Verify, commit and run without qualitative judging

**Files:**
- Create at runtime: `eval/round_b/results/<run-id>/run_manifest.json`, candidate JSONL/summary files.

- [ ] **Step 1: Run required offline suites:** `tests/round_b`, Track B contract tests, relevant snapshot tests and deterministic grader tests.
- [ ] **Step 2: Commit implementation and tests**, record its SHA, and verify `git status --porcelain` is empty.
- [ ] **Step 3: Generate and verify the Run Manifest**, validating canonical hash, 15 cases/25 turns, Track B, code SHA and B1 mappings before any network call.
- [ ] **Step 4: Execute candidates in frozen roster order**, once each, preserving all outputs and deterministic results even on infrastructure failure.
- [ ] **Step 5: Re-run offline verification, commit only generated results if required, and report descriptive results without ranking.**
