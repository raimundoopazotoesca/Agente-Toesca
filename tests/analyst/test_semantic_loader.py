import pytest
from tools.analyst.semantic_loader import load_semantic_catalog, SemanticValidationError, SEMANTIC_DIR


def test_loads_real_catalog():
    catalog = load_semantic_catalog()
    assert "vacancia_pct" in catalog.metrics
    assert catalog.metrics["vacancia_pct"]["unit"] == "pct_0_100"
    assert "TRI" in catalog.entities["fondos"]
    assert catalog.synonyms["fondos"]["PT"] == ["PT", "Parque Titanium", "Fondo PT", "Rentas PT"]


def test_invalid_metric_yaml_raises(tmp_path):
    bad_dir = tmp_path / "semantic"
    (bad_dir / "metrics").mkdir(parents=True)
    (bad_dir / "schema").mkdir()
    (SEMANTIC_DIR / "schema" / "metric.schema.json").read_text(encoding="utf-8")
    import shutil
    shutil.copy(SEMANTIC_DIR / "schema" / "metric.schema.json", bad_dir / "schema" / "metric.schema.json")
    shutil.copy(SEMANTIC_DIR / "schema" / "entity.schema.json", bad_dir / "schema" / "entity.schema.json")
    (bad_dir / "metrics" / "broken.yaml").write_text("name: broken\n", encoding="utf-8")
    (bad_dir / "entities.yaml").write_text("fondos: {}\nactivos: {}\nsociedades: {}\n", encoding="utf-8")
    (bad_dir / "relationships.yaml").write_text("{}\n", encoding="utf-8")
    (bad_dir / "synonyms.yaml").write_text("{}\n", encoding="utf-8")
    (bad_dir / "domains.yaml").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SemanticValidationError):
        load_semantic_catalog(semantic_dir=bad_dir)
