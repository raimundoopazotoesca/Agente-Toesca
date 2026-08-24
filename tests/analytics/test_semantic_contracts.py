from tools.analytics.models import (
    Aggregation,
    EntityDefinition,
    EntityReference,
    EntityType,
    MetricNature,
    SemanticQuery,
)


def test_semantic_query_is_provider_neutral_business_intent():
    query = SemanticQuery(
        metric_id="synthetic_flow",
        entities=(EntityReference("fund-a", EntityType.FUND),),
        period_start="2026-01",
        period_end="2026-03",
        temporal_aggregation=Aggregation.SUM,
        display_unit="UF",
    )

    assert query.metric_id == "synthetic_flow"
    assert query.entities[0].entity_id == "fund-a"
    assert query.temporal_aggregation is Aggregation.SUM


def test_entity_definition_keeps_aliases_typed_and_data_driven():
    entity = EntityDefinition(
        entity_id="fund-a",
        entity_type=EntityType.FUND,
        canonical_name="Fund Alpha",
        aliases=("Alpha", "FA"),
    )

    assert entity.aliases == ("Alpha", "FA")
    assert entity.entity_type is EntityType.FUND


def test_metric_nature_is_not_inferred_from_metric_name():
    assert MetricNature.FLOW.value == "flow"
    assert MetricNature.POINT_IN_TIME.value == "point_in_time"
