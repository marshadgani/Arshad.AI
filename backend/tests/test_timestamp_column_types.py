"""created_at / updated_at declarations must match Postgres, so that
`alembic revision --autogenerate` (compare_type=True) never proposes an
offset-dropping ALTER. The aware set below was read from production's
information_schema.columns on 2026-10-08; every other table is naive."""

import pytest
import src.models  # noqa: F401  (registers every table on Base.metadata)
from src.models.base import Base

AWARE_TABLES = {
    "agent_registry",
    "api_key_credentials",
    "conversation_sessions",
    "integration_oauth_tokens",
    "integrations",
    "ontology_entities",
    "ontology_relationships",
    "skill_registry",
}

NAIVE_TABLES = {
    "agent_activity",
    "agents_global",
    "commute",
    "daily_briefing",
    "decisions",
    "domain_agents",
    "domain_applications",
    "domain_feed_rows",
    "domain_kpis",
    "domains",
    "events",
    "focus_now",
    "health_habits",
    "integration_ingest_tokens",
    "knowledge_suggestions",
    "nav_items",
    "news_items",
    "notifications",
    "oauth_accounts",
    "oauth_tokens",
    "quick_actions",
    "tasks",
    "users",
    "weather",
}

TABLES_WITH_MIXIN_COLUMNS = sorted(
    name
    for name, table in Base.metadata.tables.items()
    if "created_at" in table.c and "updated_at" in table.c
)


@pytest.mark.parametrize("table_name", TABLES_WITH_MIXIN_COLUMNS)
def test_timestamp_columns_match_the_database(table_name):
    table = Base.metadata.tables[table_name]
    expect_aware = table_name in AWARE_TABLES
    for column in ("created_at", "updated_at"):
        assert table.c[column].type.timezone is expect_aware, (
            f"{table_name}.{column} should be "
            f"{'timezone-aware' if expect_aware else 'naive'}"
        )


def test_every_known_aware_table_is_actually_modelled():
    assert AWARE_TABLES <= set(TABLES_WITH_MIXIN_COLUMNS)


def test_ingest_tokens_stay_naive_because_their_columns_really_are():
    table = Base.metadata.tables["integration_ingest_tokens"]
    assert table.c.created_at.type.timezone is False
    assert table.c.updated_at.type.timezone is False


def test_both_mixins_keep_server_side_defaults():
    from src.models.integration import ApiKeyCredential
    from src.models.user import User

    for model in (ApiKeyCredential, User):
        for column in ("created_at", "updated_at"):
            assert model.__table__.c[column].server_default is not None


def test_every_table_is_explicitly_classified_as_aware_or_naive():
    """A new table must be added to AWARE_TABLES or NAIVE_TABLES on purpose, so
    the timestamp type is a decision (and checked against Postgres), never a
    default that silently drifts."""
    unclassified = set(TABLES_WITH_MIXIN_COLUMNS) - AWARE_TABLES - NAIVE_TABLES
    assert not unclassified, (
        f"Classify {sorted(unclassified)} in AWARE_TABLES or NAIVE_TABLES. "
        "New tables should use TimestampedTZMixin."
    )
    assert not (AWARE_TABLES & NAIVE_TABLES)


def test_updated_at_refreshes_on_update_for_both_mixins():
    from src.models.integration import ApiKeyCredential
    from src.models.user import User

    for model in (ApiKeyCredential, User):
        column = model.__table__.c.updated_at
        assert column.onupdate is not None
        assert column.server_default is not None
