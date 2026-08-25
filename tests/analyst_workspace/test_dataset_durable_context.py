from tools.analyst_workspace.store import WorkspaceStore


def test_dataset_query_contract_survives_workspace_hydration(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.db")
    store.initialize()
    user_id = store.set_initial_admin_password("admin", "password-123")
    conversation = store.create_conversation(owner_user_id=user_id)
    user = store.append_message(conversation.id, "user", "Top tenants")
    assistant = store.append_message(conversation.id, "assistant", "Tabla")
    contract = {
        "dataset": "rent_roll", "filters": [{"field": "activo_key", "op": "eq", "value": "Apo3001", "value_end": None}],
        "group_by": ["arrendatario"], "measures": [{"measure": "gla_m2", "aggregation": "sum"}],
        "order_by": "gla_m2", "descending": True, "limit": 5, "share_of_total": True,
    }
    memory = {"evidence": [{"evidence_id": "dataset-1", "evidence_class": "governed_dataset",
        "source": {"tool_name": "analytics_query_dataset"}, "scope": {}, "semantic_contract": contract,
        "provenance": {"tables": ["v_rent_roll_semantic"]}, "coverage": {"status": "complete"}, "facts": []}],
        "envelope": {"canonical_metric_claims": [], "derived_metric_claims": []}}
    store.persist_analytical_turn(conversation.id, user.id, assistant.id, memory)
    hydrated = store.load_durable_context_for_user(conversation.id, user_id)
    assert hydrated["evidence"][0]["semantic_contract"] == contract
