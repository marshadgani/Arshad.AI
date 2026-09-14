"""Tests for services/integration_credentials.py.

This module is the shared seam between two callers that must never drift
apart: IntegrationProvider.disconnect() (one integration) and
scripts/scrub_orphaned_integration_credentials.py (a subquery of many).
What is pinned here is the contract that makes sharing safe —

  - every statement is scoped; neither caller can produce an unbounded
    DELETE/UPDATE,
  - hard-delete vs soft-revoke is decided per table, not per caller,
  - the module never commits, so the caller keeps control of atomicity.

Behaviour specific to disconnect() (status flip, rollback, audit log)
belongs in test_integration_disconnect.py, not here.

No live DB is available in this environment, so these assert on the
compiled SQL handed to the mocked session — the same pattern as
test_integration_disconnect.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.sql.dml import Delete, Update
from src.models.integration import (
    ApiKeyCredential,
    Integration,
    IntegrationIngestToken,
    IntegrationOAuthToken,
)
from src.services.integration_credentials import (
    count_live_credentials,
    scrub_credentials,
)

DISCONNECTED_IDS = select(Integration.id).where(Integration.status == "disconnected")


def _make_db(rowcount: int = 3) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=rowcount))
    db.scalar = AsyncMock(return_value=rowcount)
    db.commit = AsyncMock()
    return db


def _statements(db: MagicMock) -> list:
    return [call.args[0] for call in db.execute.call_args_list]


def _entity_of(stmt) -> type:
    return stmt.entity_description["entity"]


@pytest.mark.asyncio
async def test_scrub_covers_every_credential_table_exactly_once():
    db = _make_db()

    await scrub_credentials(db, scope=uuid.uuid4())

    entities = [_entity_of(s) for s in _statements(db)]
    assert entities == [
        ApiKeyCredential,
        IntegrationOAuthToken,
        IntegrationIngestToken,
    ]


@pytest.mark.asyncio
async def test_scrub_hard_deletes_secrets_and_soft_revokes_hashes():
    db = _make_db()

    await scrub_credentials(db, scope=uuid.uuid4())

    by_entity = {_entity_of(s): s for s in _statements(db)}
    assert isinstance(by_entity[ApiKeyCredential], Delete)
    assert isinstance(by_entity[IntegrationOAuthToken], Delete)
    # The ingest token row is only a hash — kept, with revoked_at stamped,
    # as the audit record that a token existed and when it stopped working.
    ingest = by_entity[IntegrationIngestToken]
    assert isinstance(ingest, Update)
    assert "revoked_at" in str(ingest.compile())


@pytest.mark.asyncio
async def test_scrub_scoped_to_one_integration_uses_equality():
    integration_id = uuid.uuid4()
    db = _make_db()

    await scrub_credentials(db, scope=integration_id)

    for stmt in _statements(db):
        compiled = stmt.compile()
        assert "integration_id" in str(compiled)
        assert integration_id in compiled.params.values()


@pytest.mark.asyncio
async def test_scrub_scoped_to_a_subquery_uses_in_clause():
    """The bulk remediation path. The risk this guards is a scope type
    silently degrading to an unbounded statement rather than an IN."""
    db = _make_db()

    await scrub_credentials(db, scope=DISCONNECTED_IDS)

    for stmt in _statements(db):
        sql = str(stmt.compile()).upper()
        assert "WHERE" in sql
        assert "IN (SELECT" in sql


@pytest.mark.asyncio
async def test_scrub_never_commits():
    """Atomicity belongs to the caller: disconnect() commits the scrub and
    the status flip together, the script commits one bulk sweep."""
    db = _make_db()

    await scrub_credentials(db, scope=uuid.uuid4())

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_scrub_skips_already_revoked_ingest_tokens():
    db = _make_db()

    await scrub_credentials(db, scope=uuid.uuid4())

    ingest = next(s for s in _statements(db) if _entity_of(s) is IntegrationIngestToken)
    assert "IS NULL" in str(ingest.compile()).upper()


@pytest.mark.asyncio
async def test_counts_are_read_only_and_report_per_table():
    db = _make_db(rowcount=7)

    counts = await count_live_credentials(db, scope=DISCONNECTED_IDS)

    assert (counts.api_key_rows, counts.oauth_rows, counts.ingest_rows) == (7, 7, 7)
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_nothing_reaches_the_shared_login_grant():
    """oauth_accounts/oauth_tokens back the Arshad.AI sign-in itself.
    Disconnecting an integration must never sign the user out."""
    db = _make_db()

    await scrub_credentials(db, scope=DISCONNECTED_IDS)

    for stmt in _statements(db):
        assert _entity_of(stmt).__tablename__ not in ("oauth_accounts", "oauth_tokens")
