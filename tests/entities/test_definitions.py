from pathlib import Path

from tools.entities.definitions import load_entity_definitions


def test_entity_aliases_are_resolved_from_typed_metadata():
    definitions = load_entity_definitions(Path("semantic/entities.yaml"))

    assert definitions.resolve_exact("Apoquindo", "fund").entity_id == "Apo"
    assert definitions.resolve_exact("PT", "fund").entity_id == "PT"
    assert definitions.resolve_exact("Apoquindo", "asset") is None
