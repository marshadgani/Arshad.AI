"""Regression test for FEAT-157.

POST /api/v1/integrations/{slug}/sync 500ed with asyncpg.exceptions.
DataError: "can't subtract offset-naive and offset-aware datetimes".

The actual root cause: several models declare a `TIMESTAMP(timezone=True)`
column but pass the naive `datetime.utcnow` as its Python-side `default`/
`onupdate` — `DagTriggerQueue.requested_at` (written by every integration
sync via `make_sync_via_dag()`) chief among them. `models.base.utcnow`
returns an aware datetime and is now used everywhere that pattern
appeared. Two `Integration`-family columns
(`integrations.last_synced_at`, `integration_oauth_tokens.expires_at`)
had a model/DB drift — the Postgres columns were always
`TIMESTAMP WITH TIME ZONE`, but the SQLAlchemy model declared them
without `timezone=True` — corrected here too, though no migration was
needed for those two since the DB column already matched. Two more
(`integration_ingest_tokens.last_used_at` / `.revoked_at`) were
genuinely naive in Postgres and needed the accompanying Alembic
migration (n1k2l3m4a5b6).
"""

from src.models.base import utcnow
from src.models.conversation import ConversationMessage, ConversationSession
from src.models.dag_trigger import DagTriggerQueue
from src.models.ingested import (
    IngestedAnalyticsSummary,
    IngestedCalendarEvent,
    IngestedGitHubActivity,
    IngestedGmailThread,
)
from src.models.integration import (
    Integration,
    IntegrationIngestToken,
    IntegrationOAuthToken,
)
from src.models.obsidian import IngestedObsidianNote


def test_utcnow_helper_returns_timezone_aware_datetime():
    assert utcnow().tzinfo is not None


def test_integration_last_synced_at_is_timezone_aware():
    assert Integration.__table__.c.last_synced_at.type.timezone is True


def test_integration_oauth_token_expires_at_is_timezone_aware():
    assert IntegrationOAuthToken.__table__.c.expires_at.type.timezone is True


def test_integration_ingest_token_last_used_at_is_timezone_aware():
    assert IntegrationIngestToken.__table__.c.last_used_at.type.timezone is True


def test_integration_ingest_token_revoked_at_is_timezone_aware():
    assert IntegrationIngestToken.__table__.c.revoked_at.type.timezone is True


def test_dag_trigger_queue_requested_at_default_is_tz_aware_utcnow():
    """This is the actual write path every integration sync() exercises."""
    col = DagTriggerQueue.__table__.c.requested_at
    assert col.type.timezone is True
    assert col.default.arg.__qualname__ == "utcnow"


def test_conversation_session_timestamps_use_tz_aware_default():
    for col_name in ("created_at", "updated_at"):
        col = ConversationSession.__table__.c[col_name]
        assert col.type.timezone is True
        assert col.default.arg.__qualname__ == "utcnow"


def test_conversation_message_created_at_uses_tz_aware_default():
    col = ConversationMessage.__table__.c.created_at
    assert col.type.timezone is True
    assert col.default.arg.__qualname__ == "utcnow"


def test_obsidian_note_timestamps_use_tz_aware_default():
    for col_name in ("last_modified_at", "ingested_at"):
        col = IngestedObsidianNote.__table__.c[col_name]
        assert col.type.timezone is True
        assert col.default.arg.__qualname__ == "utcnow"


def test_ingested_models_timestamp_use_tz_aware_default():
    for model in (
        IngestedCalendarEvent,
        IngestedGmailThread,
        IngestedGitHubActivity,
        IngestedAnalyticsSummary,
    ):
        ingested_col = next(
            c for c in model.__table__.columns if c.name.endswith("ingested_at")
        )
        assert ingested_col.type.timezone is True
        assert ingested_col.default.arg.__qualname__ == "utcnow"
