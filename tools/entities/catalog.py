from dataclasses import dataclass

@dataclass(frozen=True)
class EntityTypeDefinition:
    entity_type: str; source_object: str; key_field: str; display_field: str
    searchable_fields: tuple[str, ...]; parent_context_fields: tuple[str, ...]; active_field: str | None

ENTITY_TYPES = {
    "asset": EntityTypeDefinition("asset", "dim_activo", "activo_key", "nombre", ("activo_key", "nombre"), ("fondo_key", "sociedad_key"), "vigente_hasta"),
    "fund": EntityTypeDefinition("fund", "dim_fondo", "fondo_key", "nombre", ("fondo_key", "nombre"), ("fondo_padre",), None),
    "company": EntityTypeDefinition("company", "dim_sociedad", "sociedad_key", "nombre", ("sociedad_key", "nombre"), ("fondo_key",), None),
}
