"""Regression test for FEAT-157.

POST /api/v1/integrations/{slug}/sync 500ed with asyncpg.exceptions.
DataError: "can't subtract offset-naive and offset-aware datetimes".

Root cause: several models declare a `TIMESTAMP(timezone=True)` column
but passed the naive `datetime.utcnow` as its Python-side `default`/
`onupdate` — `DagTriggerQueue.requested_at` (written by every
integration sync via `make_sync_via_dag()`) is the column that actually
500ed. `models.base.utcnow` returns an aware datetime and is now used
everywhere that pattern appeared. Two `Integration`-family columns
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


def _assert_aware_utcnow_default(col) -> None:
    """A column whose Python-side default is `utcnow`.

    Calls the registered default callable (not just its name) so a
    future `utcnow` that satisfies the name check but returns a naive
    value — or any other regression to the production write path — is
    actually caught, not just declaration drift.
    """
    assert col.type.timezone is True
    assert col.default.arg.__qualname__ == utcnow.__qualname__
    produced = col.default.arg(None)
    assert produced.tzinfo is not None


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


def test_dag_trigger_queue_requested_at_default_produces_aware_datetime():
    """This is the actual write path every integration sync() exercises."""
    _assert_aware_utcnow_default(DagTriggerQueue.__table__.c.requested_at)


def test_conversation_session_created_at_default_produces_aware_datetime():
    _assert_aware_utcnow_default(ConversationSession.__table__.c.created_at)


def test_conversation_session_updated_at_onupdate_produces_aware_datetime():
    col = ConversationSession.__table__.c.updated_at
    assert col.type.timezone is True
    assert col.onupdate.arg.__qualname__ == utcnow.__qualname__
    assert col.onupdate.arg(None).tzinfo is not None


def test_conversation_message_created_at_default_produces_aware_datetime():
    _assert_aware_utcnow_default(ConversationMessage.__table__.c.created_at)


def test_obsidian_note_timestamps_default_produce_aware_datetime():
    for col_name in ("last_modified_at", "ingested_at"):
        _assert_aware_utcnow_default(IngestedObsidianNote.__table__.c[col_name])


def test_ingested_models_timestamp_default_produces_aware_datetime():
    for model in (
        IngestedCalendarEvent,
        IngestedGmailThread,
        IngestedGitHubActivity,
        IngestedAnalyticsSummary,
    ):
        ingested_col = next(
            c for c in model.__table__.columns if c.name.endswith("ingested_at")
        )
        _assert_aware_utcnow_default(ingested_col)
