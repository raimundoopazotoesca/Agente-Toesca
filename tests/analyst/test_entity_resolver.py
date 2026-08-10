from tools.analyst.entity_resolver import resolve_entity


def test_resolves_fondo_alias():
    assert resolve_entity("APO", "fondo") == "Apo"
    assert resolve_entity("Parque Titanium", "fondo") == "PT"
    assert resolve_entity("fondo madre", "fondo") == "TRI"


def test_resolves_activo_alias():
    assert resolve_entity("Vina", "activo") == "Viña Centro"
    assert resolve_entity("Power Center", "activo") == "Mall Curicó"
    assert resolve_entity("3001", "activo") == "Apo3001"


def test_apo3001_belongs_to_tri_not_apo():
    from tools.analyst.semantic_loader import load_semantic_catalog
    catalog = load_semantic_catalog()
    assert catalog.entities["activos"]["Apo3001"]["fondo_key"] == "TRI"


def test_no_match_returns_none():
    assert resolve_entity("activo inexistente xyz", "activo") is None
