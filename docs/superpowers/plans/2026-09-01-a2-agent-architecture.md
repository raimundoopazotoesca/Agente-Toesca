# A2 Agent Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing canonical Analyst traceable, resolution-safe, and explicitly bounded for A3/A4/A5.

**Architecture:** Build a JSON-safe TurnTrace v1 from existing runtime results and persist it atomically in existing assistant-message metadata. Normalize resolution diagnostics through adapters, not a generalized framework. The trace derives routing/evidence from actual trajectory; db_chat remains transition-only.

**Tech Stack:** Python 3.11+, dataclasses, SQLite workspace metadata, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-a2-agent-architecture-design.md`

## Global Constraints

- Base is exactly `fdc253b5167b8dbce595fa079450d6da2235497b`; work only in `feat/a2-agent-architecture`.
- Do not modify `memory/agente_toesca_v2.db`, JLL migrations 085--091, or PT gastos_usuario test ID 8.
- Canonical runtime never imports `tools.db_chat`; `/api/chat` remains transition-only.
- Public status is only resolved, ambiguous, unknown; retain detailed causes in `reason_code`/evidence.
- A successful assistant answer must include a completed persisted trace; trace failures fail the request visibly and do not return/persist the answer.
- Persist a pending turn ID on the user message. A retry of that pending turn reuses the user message and turn ID; optional trace-field collection errors are recorded without a 503, while mandatory envelope persistence errors return the 503.
- Store no raw provider payload, prompt, chain-of-thought, hidden reasoning, or scratchpad.
- Use `python -X utf8`, stage exact files only, and never push.

## File map

| File | Change |
|---|---|
| `tools/analyst_runtime/resolution.py` | New public resolution outcome and adapters |
| `tools/analyst_runtime/turn_trace.py` | New v1 trace builder, sanitizer, reconstructor |
| `tools/analyst_runtime/actions.py` | Expose normalized entity outcome in safe action trace |
| `tools/analyst_runtime/session.py` | Expose existing runtime results required by trace builder |
| `tools/analyst_workspace/conversation_service.py` | Correlation, atomic trace metadata lifecycle, fail-closed error |
| `tools/analyst_api.py`, `scripts/ingesta_server.py` | Neutral service language and 503 trace failure mapping |
| `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, `docs/a2-db-chat-transition-boundary.md` | Ownership, current-state correction, transition audit |
| `tests/analyst_runtime/test_turn_trace.py` | Resolution and pure trace tests |
| `tests/analyst_workspace/test_turn_trace_lifecycle.py` | Real persistence/reconstruction/failure tests |
| `tests/test_analyst_architecture_contract.py` | API/static ownership boundary tests |

### Task 1: Resolution contract

**Files:** create `tools/analyst_runtime/resolution.py`; modify `actions.py`; test `tests/analyst_runtime/test_turn_trace.py`.

**Interfaces:** `ResolutionOutcome(status, canonical_value, method, reason_code, evidence, candidates)`; `resolution_from_entity_payload(payload, trace)`; `resolution_from_action_trace(action_name, arguments, tool_trace, evidence)`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_low_confidence_is_unknown_without_losing_cause():
    outcome = resolution_from_entity_payload({"status": "low_confidence", "candidates": []}, {})
    assert (outcome.status, outcome.reason_code) == ("unknown", "low_confidence")

def test_ambiguous_entity_keeps_candidates():
    outcome = resolution_from_entity_payload({"status": "ambiguous", "candidates": [{"entity_key": "Apo"}]}, {})
    assert outcome.status == "ambiguous"
    assert outcome.candidates == ({"entity_key": "Apo"},)
```

- [ ] **Step 2: Verify RED**

Run: `python -X utf8 -m pytest tests/analyst_runtime/test_turn_trace.py -q`

Expected: import failure for `resolution`.

- [ ] **Step 3: Implement minimal adapters**

Use a frozen dataclass. Map `not_found` and `low_confidence` to `unknown`, retaining raw internal status in evidence. Preserve current clarification control and entity matching.

- [ ] **Step 4: Verify GREEN**

Run: `python -X utf8 -m pytest tests/analyst_runtime/test_turn_trace.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/analyst_runtime/resolution.py tools/analyst_runtime/actions.py tests/analyst_runtime/test_turn_trace.py
git commit -m "feat: normalize analyst resolution outcomes"
```

### Task 2: Pure TurnTrace v1

**Files:** create `tools/analyst_runtime/turn_trace.py`; modify `session.py`; test `tests/analyst_runtime/test_turn_trace.py`.

**Interfaces:** `build_turn_trace(result, *, user_text, turn_id, conversation_id, session_id, user_message_id=None, assistant_message_id=None) -> dict[str, Any]`; `reconstruct_turn(trace) -> ReconstructedTurn`.

- [ ] **Step 1: Write failing trace tests**

```python
def test_trace_reconstructs_answer_and_has_no_hidden_reasoning():
    trace = build_turn_trace(result, user_text="vacancia TRI", turn_id="t-1",
                             conversation_id="c-1", session_id="s-1")
    assert reconstruct_turn(trace).final_answer == result.text
    forbidden = {"raw", "chain_of_thought", "reasoning", "scratchpad"}
    assert not any(key in json.dumps(trace) for key in forbidden)
```

- [ ] **Step 2: Verify RED**

Run: `python -X utf8 -m pytest tests/analyst_runtime/test_turn_trace.py -q`

Expected: import failure for `build_turn_trace`.

- [ ] **Step 3: Implement the allowlisted builder**

Include identity, input, resolution, routing, actions, evidence IDs, observable SQL/model/latency, output and existing validation only. Use `trace_version="1"`, `span_type="analyst_turn"`, UTC timestamp, and completion status. Omit unavailable A3/A5 fields or label them `not_owned_by_a2`.

- [ ] **Step 4: Verify GREEN**

Run: `python -X utf8 -m pytest tests/analyst_runtime/test_turn_trace.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/analyst_runtime/turn_trace.py tools/analyst_runtime/session.py tests/analyst_runtime/test_turn_trace.py
git commit -m "feat: add analyst turn trace v1"
```

### Task 3: Real canonical trace lifecycle

**Files:** modify `conversation_service.py`; optionally modify `store.py` only for metadata validation; test `tests/analyst_workspace/test_turn_trace_lifecycle.py`.

**Interfaces:** `TurnTracePersistenceError(ConversationServiceError)`; `runtime_result_to_metadata(..., turn_trace=...) -> dict[str, Any]`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_real_service_turn_persists_completed_correlated_trace(service, store):
    assistant = service.send_message(CONVERSATION_ID, "vacancia TRI")
    trace = store.get_message(assistant.id).metadata["turn_trace"]
    assert trace["identity"]["assistant_message_id"] == assistant.id
    assert trace["completion"]["status"] == "completed"

def test_trace_failure_does_not_return_or_persist_untraced_answer(service, monkeypatch):
    monkeypatch.setattr("tools.analyst_workspace.conversation_service.build_turn_trace",
                        lambda **_: (_ for _ in ()).throw(ValueError("trace unavailable")))
    with pytest.raises(TurnTracePersistenceError):
        service.send_message(CONVERSATION_ID, "vacancia TRI")
    assert not [m for m in service.list_messages(CONVERSATION_ID) if m.role == "assistant"]

def test_retry_reuses_pending_user_turn_after_trace_persistence_failure(service, monkeypatch):
    original = service.send_message
    # First attempt raises TurnTracePersistenceError after persisting the user message.
    # Second call reuses that pending message/turn ID and creates one assistant response.
    ...
```

- [ ] **Step 2: Verify RED**

Run: `python -X utf8 -m pytest tests/analyst_workspace/test_turn_trace_lifecycle.py -q`

Expected: missing trace metadata/error.

- [ ] **Step 3: Implement fail-closed persistence**

Allocate and persist a pending turn ID with the user message before `session.ask`. A retry finds that pending message by the same conversation/text boundary, reuses its turn ID, and does not append another user message. Build/serialize completed trace before assistant `append_message`. On builder, serialization, or write failure raise `TurnTracePersistenceError`; keep the pending user message but never return/persist the model result. Persist durable memory only after successful assistant trace insert. Optional field collection records an explicit collection error and does not raise the mandatory persistence error.

- [ ] **Step 4: Verify GREEN**

Run: `python -X utf8 -m pytest tests/analyst_workspace/test_turn_trace_lifecycle.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/analyst_workspace/conversation_service.py tools/analyst_workspace/store.py tests/analyst_workspace/test_turn_trace_lifecycle.py
git commit -m "feat: persist analyst turn traces"
```

### Task 4: API and transition boundary

**Files:** modify `analyst_api.py`, `ingesta_server.py`, current docs; create transition doc; test `tests/test_analyst_architecture_contract.py`.

**Interfaces:** `TurnTracePersistenceError` maps to a safe `trace_persistence_failed` 503 response. Comments/protocols use neutral conversation-service terminology.

- [ ] **Step 1: Write failing boundary tests**

```python
def test_canonical_runtime_does_not_import_db_chat():
    assert "tools.db_chat" not in Path("tools/analyst_runtime/session.py").read_text(encoding="utf-8")

def test_trace_persistence_failure_has_explicit_safe_api_error(client):
    response = client.post(MESSAGE_URL, json={"text": "x"})
    assert (response.status_code, response.json["error"]) == (503, "trace_persistence_failed")
```

- [ ] **Step 2: Verify RED**

Run: `python -X utf8 -m pytest tests/test_analyst_architecture_contract.py -q`

Expected: the 503 error code is absent.

- [ ] **Step 3: Implement minimal route/error/docs changes**

Map only trace persistence failure to the explicit 503 code. Correct the misleading A4 labels. Document current ownership, caller/capability audit, retirement signal, A2/A3/A4/A5 boundaries, and only present-tense state drift.

- [ ] **Step 4: Verify GREEN**

Run: `python -X utf8 -m pytest tests/test_analyst_architecture_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tools/analyst_api.py scripts/ingesta_server.py docs/CURRENT_STATE.md docs/ARCHITECTURE.md docs/a2-db-chat-transition-boundary.md tests/test_analyst_architecture_contract.py
git commit -m "docs: define analyst transition boundaries"
```

### Task 5: Historical debt and focused regression

**Files:** modify entity tests/allowlist only if independently justified; update current state disposition.

- [ ] **Step 1: Inspect IDs 1 and 12 before changing them**

Run: `python -X utf8 -m pytest tests/entities/test_canonical_entity_resolver.py -q`

Expected: capture exact current failure reason.

- [ ] **Step 2: Write an explicit replacement contract test if the old test is positional/stale**

```python
def test_resolve_entity_trace_exposes_normalized_contract(action, request):
    result = action.execute(request)
    assert result.trace["resolution"]["status"] == "resolved"
    assert result.trace["resolution"]["method"]
```

- [ ] **Step 3: Verify RED, then apply smallest justified assertion/allowlist update**

Run: `python -X utf8 -m pytest tests/entities/test_canonical_entity_resolver.py -q`

Expected: the replacement test fails only for missing explicit contract. Remove IDs 1/12 only after their exact node IDs pass. Keep ID 2, ID 8, JLL IDs, and 13--17 within their documented owners.

- [ ] **Step 4: Run focused A2 suite**

Run: `python -X utf8 -m pytest tests/analyst_runtime/test_turn_trace.py tests/analyst_workspace/test_turn_trace_lifecycle.py tests/test_analyst_architecture_contract.py tests/entities/test_canonical_entity_resolver.py -q`

Expected: PASS except only independently observed unchanged historical IDs.

- [ ] **Step 5: Commit**

```powershell
git add tests/entities/test_canonical_entity_resolver.py eval/baselines/pytest-known-failures.json docs/CURRENT_STATE.md
git commit -m "test: close A2 architecture contract"
```

### Task 6: Exact final verification and stop

- [ ] **Step 1: Run the exact baseline-gated CI sequence in its own process**

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
python -X utf8 -m pytest tests -q --deselect tests/analyst_runtime/test_synthesis_schema_provider.py::test_synthesis_envelope_schema_accepted_by_openai_strict_structured_outputs --deselect tests/db/test_ingest_er_inmosa.py::test_parse_archivo_real_no_lanza_y_cuadra_integridad --deselect tests/db/test_ingest_er_sucden.py::test_parse_archivo_real_no_lanza_y_cuadra_integridad --deselect tests/db/test_ingest_er_apo3001.py::test_parse_archivo_real_no_lanza_y_cuadra_integridad --deselect tests/db/test_ingest_er_curico.py::test_parse_archivo_real_no_lanza_y_cuadra_integridad --junitxml=artifacts/pytest-tests.xml -p tools.eval.pytest_nodeid_reporter --nodeid-report=artifacts/pytest-tests-nodeids.json
python -X utf8 -m tools.eval.pytest_baseline_gate --nodeid-report artifacts/pytest-tests-nodeids.json --baseline eval/baselines/pytest-d986996.json --known-failures eval/baselines/pytest-known-failures.json --output artifacts/pytest-tests-gate-result.json
```

Expected: zero new/anomalous/prohibited/not-collected IDs and no collection/internal errors.

- [ ] **Step 2: Run benchmark separately**

Run: `python -X utf8 -m pytest eval/benchmark/tests -q`

Expected: exit 0.

- [ ] **Step 3: Run product-alpha separately**

Run: `python -X utf8 -m pytest eval/product_alpha/tests -q`

Expected: exit 0.

- [ ] **Step 4: Verify safety and report before push**

Run: `git status --short; git diff --stat; git diff -- memory/agente_toesca_v2.db; git log --oneline fdc253b..HEAD`

Expected: business DB unchanged, intentional commits, and no push/PR/merge.

## Review

Every required A2 behavior maps to Tasks 1--4; historical debt is constrained in Task 5; exact CI acceptance is Task 6. No task expands into A3, A4, A5, JLL, or db_chat feature scope.
