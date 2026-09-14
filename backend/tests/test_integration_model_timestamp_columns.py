"""Regression test for FEAT-157.

Every integration sync() writes datetime.now(timezone.utc) — a tz-aware
value — into Integration.last_synced_at, IntegrationOAuthToken.expires_at,
and IntegrationIngestToken.last_used_at. If any of those columns is
declared as a plain (tz-naive) TIMESTAMP, asyncpg raises "can't subtract
offset-naive and offset-aware datetimes" on Postgres and the sync/OAuth
callback/ingest request 500s. This test pins the column types so a future
change can't silently reintroduce the mismatch without a matching
Alembic migration.
"""

from src.models.integration import Integration, IntegrationIngestToken, IntegrationOAuthToken


def test_integration_last_synced_at_is_timezone_aware():
    assert Integration.__table__.c.last_synced_at.type.timezone is True


def test_integration_oauth_token_expires_at_is_timezone_aware():
    assert IntegrationOAuthToken.__table__.c.expires_at.type.timezone is True


def test_integration_ingest_token_last_used_at_is_timezone_aware():
    assert IntegrationIngestToken.__table__.c.last_used_at.type.timezone is True
