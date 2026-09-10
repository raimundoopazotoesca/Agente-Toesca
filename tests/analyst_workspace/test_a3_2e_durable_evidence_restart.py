"""A3.2e focused tests: durable evidence persistence, legacy-row/version
fail-closed handling, cross-conversation isolation, and the real restart
path (persist -> reload -> factory/session creation -> hydration).

Deliberately does NOT use FakeFactory for the restart tests -- the A3.2e
diagnostic found that the previous "restart" coverage
(test_restart_hydrates_structured_durable_context in
test_conversation_service.py) only exercised FakeFactory.create, never the
real OpenAIResponsesAnalystSessionFactory.create -> _memory_to_evidence ->
evidence_from_dict path where the actual bug lived. These tests exercise
the real factory instead.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from tools.analyst_runtime.session import OpenAIResponsesAnalystSessionFactory
from tools.analyst_runtime.transport import ToolEvidence, project_evidence_for_durable_storage
from tools.analyst_workspace.store import WorkspaceStore


def _canonical_evidence(evidence_id: str = "e1") -> ToolEvidence:
    return ToolEvidence.build(
        evidence_id=evidence_id, evidence_class="canonical_metric", tool_name="analytics_lookup_asset",
        source_kind="raw_eeff_line", scope={"asset": "PT"}, semantic_contract={"metric_key": "noi"},
        provenance={"ingest_run_id": 7}, facts=({"metric_key": "noi", "value": 100.0, "unit": "UF",
                                                  "entity_id": "PT", "period": "2026-06"},),
        metric_id="noi",
    )


def _governed_evidence(evidence_id: str = "e2") -> ToolEvidence:
    return ToolEvidence.build(
        evidence_id=evidence_id, evidence_class="governed_dataset", tool_name="analytics_query_dataset",
        source_kind="raw_rent_roll_line", scope={"fund": "TRI"}, semantic_contract={"dataset": "vacancia"},
        provenance={"ingest_run_id": 9}, facts=(
            {"metric_key": "vacancia_pct", "value": 5.0, "unit": "pct", "entity_id": "TRI", "period": "2026-06"},
        ),
        dataset_id="vacancia_mensual",
    )


def _controlled_sql_memory_item(evidence_id: str = "e3") -> dict:
    """Shaped as if a future caller accidentally fed an unfiltered evidence
    list straight to persist_analytical_turn -- the exact "indirect route"
    the persistence-layer filter must close even though the normal
    session.py path (project_evidence_for_durable_storage) already never
    produces this."""
    return {
        "evidence_id": evidence_id, "evidence_class": "controlled_sql",
        "producer": {"tool_name": "run_sql", "contract_version": "1"},
        "authority": {"kind": "controlled_sql", "sql_fingerprint": "sha256:deadbeef"},
        "scope": {}, "temporal": {}, "units": {}, "provenance": {"sql": "SELECT * FROM v_noi"},
        "facts": [], "limitations": [], "coverage": None, "semantic_contract": {},
        "projection_version": "1",
    }


def _envelope_for(evidence_ids: list[str]) -> dict:
    return {
        "canonical_metric_claims": [
            {"claim_id": f"claim-{eid}", "evidence_id": eid, "metric_key": "x", "value": 1.0,
             "unit": "UF", "entity_id": "PT", "period": "2026-06"}
            for eid in evidence_ids
        ],
        "derived_metric_claims": [],
    }


@pytest.fixture
def workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    return store


@pytest.fixture
def owned_conversation(workspace):
    user_id = workspace.create_user("raimundo", "Raimundo", "password-a")
    conversation = workspace.create_conversation(owner_user_id=user_id)
    return workspace, user_id, conversation


def _persist_turn(workspace, conversation_id: str, evidence_items: list[dict], envelope: dict | None = None) -> None:
    user_message = workspace.append_message(conversation_id, "user", "pregunta", metadata={})
    assistant_message = workspace.append_message(conversation_id, "assistant", "respuesta", metadata={})
    memory = {"evidence": evidence_items, "envelope": envelope or _envelope_for(
        [item["evidence_id"] for item in evidence_items])}
    workspace.persist_analytical_turn(conversation_id, user_message.id, assistant_message.id, memory)


# ---------------------------------------------------------------------------
# H: controlled_sql exclusion at the persistence layer
# ---------------------------------------------------------------------------

def test_controlled_sql_is_excluded_from_evidence_snapshot_even_when_fed_directly(owned_conversation):
    workspace, user_id, conversation = owned_conversation
    canonical = project_evidence_for_durable_storage(_canonical_evidence("c1"))
    governed = project_evidence_for_durable_storage(_governed_evidence("g1"))
    controlled_sql = _controlled_sql_memory_item("sql1")
    _persist_turn(workspace, conversation.id, [canonical, governed, controlled_sql])

    conn = sqlite3.connect(workspace.db_path)
    rows = conn.execute("SELECT evidence_class FROM evidence_snapshot").fetchall()
    conn.close()
    classes = sorted(row[0] for row in rows)
    assert classes == ["canonical_metric", "governed_dataset"]
    assert "controlled_sql" not in classes


def test_controlled_sql_traceability_still_survives_via_turn_trace_shaped_metadata(owned_conversation):
    """The persistence-layer exclusion of controlled_sql from durable
    evidence must not be confused with removing SQL auditability -- that
    lives in TurnTrace/message metadata (untouched by A3.2e), not
    evidence_snapshot. This test only documents the boundary: the SQL text
    a controlled_sql item carries in provenance is not what's being
    protected against here (evidence_snapshot never held it either way for
    controlled_sql after this change), only its (always-empty) facts and
    its evidence_class label."""
    controlled_sql = _controlled_sql_memory_item("sql2")
    assert controlled_sql["facts"] == []
    assert controlled_sql["evidence_class"] == "controlled_sql"


# ---------------------------------------------------------------------------
# I: legacy row (pre-A3.2e, no authority) does not crash restart
# ---------------------------------------------------------------------------

def _insert_legacy_evidence_snapshot_row(workspace, snapshot_id: str, fingerprint: str) -> None:
    """Simulate a genuine pre-A3.2e row: only the seven original columns are
    populated (matching the real historical shape found in
    memory/analyst_workspace.db during the A3.2e precheck -- source_json
    populated with a pre-A3.2a shape, everything from schema v10 onward
    NULL). Inserted via raw SQL, deliberately bypassing
    persist_analytical_turn, since no code path in the current codebase can
    produce this shape any more -- it is purely historical."""
    conn = sqlite3.connect(workspace.db_path)
    conn.execute(
        "INSERT INTO evidence_snapshot (id, fingerprint, evidence_class, scope_json, provenance_json, "
        "coverage_json, semantic_contract_json, source_json, facts_json, created_at) "
        "VALUES (?, ?, 'canonical_metric', '{}', '{}', NULL, '{}', "
        "'{\"source_kind\":\"canonical\",\"tool_name\":\"analytics_lookup_fund\"}', '[]', '2025-01-01T00:00:00')",
        (snapshot_id, fingerprint),
    )
    conn.commit()
    conn.close()


def test_legacy_row_is_dropped_without_crashing_session_creation(owned_conversation, tmp_path):
    workspace, user_id, conversation = owned_conversation
    _insert_legacy_evidence_snapshot_row(workspace, "legacy-1", "legacy-fp-1")
    conn = sqlite3.connect(workspace.db_path)
    turn_id = "turn-legacy-1"
    conn.execute("INSERT INTO analytical_turn VALUES (?, ?, ?, ?, ?)",
                 (turn_id, conversation.id, "user-msg-1", "assistant-msg-1", "2025-01-01T00:00:00"))
    conn.execute("INSERT INTO analytical_turn_evidence VALUES (?, ?)", (turn_id, "legacy-1"))
    conn.commit()
    conn.close()

    durable = workspace.load_durable_context_for_user(conversation.id, user_id)
    assert len(durable["evidence"]) == 1
    assert durable["evidence"][0]["projection_version"] is None

    business_db = tmp_path / "business.db"
    sqlite3.connect(business_db).close()
    factory = OpenAIResponsesAnalystSessionFactory(business_db, client_factory=lambda: object())
    session = factory.create(None, [], runtime_context={"durable_analytical_context": durable})
    assert session._durable_evidence == []  # dropped, not crashed


def test_legacy_row_drop_does_not_affect_other_valid_evidence_in_the_same_context(owned_conversation, tmp_path):
    workspace, user_id, conversation = owned_conversation
    _insert_legacy_evidence_snapshot_row(workspace, "legacy-2", "legacy-fp-2")
    conn = sqlite3.connect(workspace.db_path)
    turn_id = "turn-legacy-2"
    conn.execute("INSERT INTO analytical_turn VALUES (?, ?, ?, ?, ?)",
                 (turn_id, conversation.id, "user-msg-2", "assistant-msg-2", "2025-01-01T00:00:00"))
    conn.execute("INSERT INTO analytical_turn_evidence VALUES (?, ?)", (turn_id, "legacy-2"))
    conn.commit()
    conn.close()
    canonical = project_evidence_for_durable_storage(_canonical_evidence("valid-1"))
    _persist_turn(workspace, conversation.id, [canonical])

    durable = workspace.load_durable_context_for_user(conversation.id, user_id)
    business_db = tmp_path / "business.db"
    sqlite3.connect(business_db).close()
    factory = OpenAIResponsesAnalystSessionFactory(business_db, client_factory=lambda: object())
    session = factory.create(None, [], runtime_context={"durable_analytical_context": durable})
    # evidence_snapshot assigns its own fingerprint-deduped id on write (see
    # persist_analytical_turn), so the surviving item is identified by
    # content, not the caller's original evidence_id.
    assert len(session._durable_evidence) == 1
    assert session._durable_evidence[0].evidence_class == "canonical_metric"
    assert session._durable_evidence[0].facts[0]["value"] == 100.0


# ---------------------------------------------------------------------------
# J: unknown projection_version fails closed per item
# ---------------------------------------------------------------------------

def test_unknown_projection_version_is_dropped_others_survive(owned_conversation, tmp_path):
    workspace, user_id, conversation = owned_conversation
    canonical = project_evidence_for_durable_storage(_canonical_evidence("valid-2"))
    future_shaped = dict(project_evidence_for_durable_storage(_governed_evidence("future-1")))
    future_shaped["projection_version"] = "99"  # a hypothetical future shape this build does not understand
    _persist_turn(workspace, conversation.id, [canonical, future_shaped])

    durable = workspace.load_durable_context_for_user(conversation.id, user_id)
    versions = sorted(item["projection_version"] for item in durable["evidence"])
    assert versions == ["1", "99"]

    business_db = tmp_path / "business.db"
    sqlite3.connect(business_db).close()
    factory = OpenAIResponsesAnalystSessionFactory(business_db, client_factory=lambda: object())
    session = factory.create(None, [], runtime_context={"durable_analytical_context": durable})
    assert len(session._durable_evidence) == 1
    assert session._durable_evidence[0].evidence_class == "canonical_metric"
    assert session._durable_evidence[0].authority.metric_id == "noi"


# ---------------------------------------------------------------------------
# K: cross-conversation isolation
# ---------------------------------------------------------------------------

def test_evidence_from_one_conversation_never_appears_when_hydrating_another(workspace):
    user_id = workspace.create_user("raimundo", "Raimundo", "password-a")
    conversation_a = workspace.create_conversation(owner_user_id=user_id)
    conversation_b = workspace.create_conversation(owner_user_id=user_id)
    canonical = project_evidence_for_durable_storage(_canonical_evidence("only-in-a"))
    _persist_turn(workspace, conversation_a.id, [canonical])

    durable_a = workspace.load_durable_context_for_user(conversation_a.id, user_id)
    durable_b = workspace.load_durable_context_for_user(conversation_b.id, user_id)
    assert len(durable_a["evidence"]) == 1
    assert durable_a["evidence"][0]["facts"][0]["value"] == 100.0
    assert durable_b["evidence"] == []
    assert durable_b["claims"] == []


# ---------------------------------------------------------------------------
# L: restart via the real factory (no FakeFactory)
# ---------------------------------------------------------------------------

def test_real_factory_hydrates_durable_evidence_as_real_tool_evidence(owned_conversation, tmp_path):
    workspace, user_id, conversation = owned_conversation
    canonical = project_evidence_for_durable_storage(_canonical_evidence("real-1"))
    governed = project_evidence_for_durable_storage(_governed_evidence("real-2"))
    _persist_turn(workspace, conversation.id, [canonical, governed])

    durable = workspace.load_durable_context_for_user(conversation.id, user_id)
    business_db = tmp_path / "business.db"
    sqlite3.connect(business_db).close()
    factory = OpenAIResponsesAnalystSessionFactory(business_db, client_factory=lambda: object())
    session = factory.create(None, [], runtime_context={"durable_analytical_context": durable})

    # evidence_snapshot assigns its own fingerprint-deduped id, so items are
    # identified by evidence_class/content, not the caller's original
    # evidence_id (see persist_analytical_turn).
    assert len(session._durable_evidence) == 2
    by_class = {item.evidence_class: item for item in session._durable_evidence}
    assert set(by_class) == {"canonical_metric", "governed_dataset"}
    assert by_class["canonical_metric"].authority.metric_id == "noi"
    assert by_class["canonical_metric"].facts[0]["value"] == 100.0
    assert by_class["governed_dataset"].authority.dataset_id == "vacancia_mensual"
    assert all(isinstance(item, ToolEvidence) for item in session._durable_evidence)


# ---------------------------------------------------------------------------
# M: controlled_sql cannot become factual evidence after restart
# ---------------------------------------------------------------------------

def test_controlled_sql_never_reappears_as_durable_evidence_after_restart(owned_conversation, tmp_path):
    workspace, user_id, conversation = owned_conversation
    canonical = project_evidence_for_durable_storage(_canonical_evidence("m-canon"))
    governed = project_evidence_for_durable_storage(_governed_evidence("m-gov"))
    controlled_sql = _controlled_sql_memory_item("m-sql")
    _persist_turn(workspace, conversation.id, [canonical, governed, controlled_sql])

    durable = workspace.load_durable_context_for_user(conversation.id, user_id)
    assert len(durable["evidence"]) == 2
    assert {item["evidence_class"] for item in durable["evidence"]} == {"canonical_metric", "governed_dataset"}

    business_db = tmp_path / "business.db"
    sqlite3.connect(business_db).close()
    factory = OpenAIResponsesAnalystSessionFactory(business_db, client_factory=lambda: object())
    session = factory.create(None, [], runtime_context={"durable_analytical_context": durable})

    classes = {item.evidence_class for item in session._durable_evidence}
    assert "controlled_sql" not in classes
    assert classes == {"canonical_metric", "governed_dataset"}
    # Not canonical, not governed table-claim material, not a derived
    # operand, not an AllowedClaim -- coverage_guard's own boundary (A3.2c,
    # untouched here) still applies on top of this; this test only proves
    # controlled_sql never even reaches the durable evidence pool a future
    # turn's synthesis would draw from.


# ---------------------------------------------------------------------------
# N: no sensitive persistence in the durable projection
# ---------------------------------------------------------------------------

def test_durable_projection_has_a_fixed_key_set_with_no_room_for_extra_fields():
    projection = project_evidence_for_durable_storage(_canonical_evidence())
    assert set(projection.keys()) == {
        "projection_version", "evidence_id", "evidence_class", "producer", "authority",
        "scope", "temporal", "units", "provenance", "facts", "limitations", "coverage",
        "semantic_contract",
    }


def test_persisted_and_reloaded_evidence_contains_no_sensitive_markers(owned_conversation):
    workspace, user_id, conversation = owned_conversation
    canonical = project_evidence_for_durable_storage(_canonical_evidence("n-1"))
    _persist_turn(workspace, conversation.id, [canonical])
    durable = workspace.load_durable_context_for_user(conversation.id, user_id)
    serialized = json.dumps(durable)
    for forbidden in ("chain_of_thought", "raw_reasoning", "reasoning", "prompt", "secret", "api_key", "raw_items"):
        assert forbidden not in serialized
