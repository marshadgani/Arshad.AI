"""Tests for IntegrationProvider.disconnect() (base.py).

The old default only flipped `Integration.status` — every provider that
didn't override it left a fully usable credential (OAuth token, API key)
in Postgres while the frontend's disconnect dialog promised "Stored
credentials will be removed." These tests pin the fixed behaviour:

  - api_key_credentials / integration_oauth_tokens rows are hard-deleted
  - integration_ingest_tokens rows are soft-revoked (revoked_at set, kept)
  - oauth_accounts (the shared Arshad.AI login grant) is never touched
  - every statement is scoped to this integration's id — the single
    highest-value property to test, since a missing WHERE clause would
    delete every user's credentials while still satisfying any
    type-only assertion

No live DB is available in this environment (conftest.py sets only env
vars) — all tests use MagicMock/AsyncMock db sessions and assert on the
compiled SQL handed to db.execute, matching the existing pattern in
test_apple_health.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Delete, Update
from src.integrations.base import (
    ConnectResult,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from src.models.integration import (
    ApiKeyCredential,
    Integration,
    IntegrationIngestToken,
    IntegrationOAuthToken,
)

USER_ID = uuid.uuid4()


class _StubProvider(IntegrationProvider):
    """Minimal concrete subclass — IntegrationProvider is an ABC and
    cannot be instantiated directly. Only disconnect() (inherited,
    unoverridden) is exercised by these tests."""

    slug = "stub-provider"
    kind = "project_apikey"
    display_name = "Stub Provider"
    category = "Test"
    description = "Test-only stub."

    async def connect(self, *, user, db, payload) -> ConnectResult:  # pragma: no cover
        raise NotImplementedError

    async def sync(self, *, integration, db) -> SyncResult:  # pragma: no cover
        raise NotImplementedError

    async def status(self, *, integration, db) -> StatusReport:  # pragma: no cover
        raise NotImplementedError


def _make_integration() -> Integration:
    return Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="stub-provider",
        kind="project_apikey",
        status="connected",
        config={},
    )


def _make_db(rowcount: int = 1, *, in_transaction: bool = False) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=rowcount))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    # Defaults to False so existing commit-count assertions below aren't
    # perturbed by the pre-revoke `if db.in_transaction(): await db.commit()`
    # guard in disconnect() — see test_disconnect_closes_open_transaction_
    # before_revoking_upstream for the True case.
    db.in_transaction = MagicMock(return_value=in_transaction)
    return db


def _compiled_params(stmt) -> dict:
    return stmt.compile().params


@pytest.mark.asyncio
async def test_disconnect_deletes_api_key_credential():
    integration = _make_integration()
    db = _make_db()
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)

    stmts = [call.args[0] for call in db.execute.call_args_list]
    matches = [
        s
        for s in stmts
        if isinstance(s, Delete) and s.entity_description["entity"] is ApiKeyCredential
    ]
    assert len(matches) == 1
    compiled_sql = str(matches[0].compile())
    assert "integration_id" in compiled_sql
    assert integration.id in _compiled_params(matches[0]).values()
    assert integration.status == "disconnected"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_deletes_oauth_token():
    integration = _make_integration()
    db = _make_db()
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)

    stmts = [call.args[0] for call in db.execute.call_args_list]
    matches = [
        s
        for s in stmts
        if isinstance(s, Delete)
        and s.entity_description["entity"] is IntegrationOAuthToken
    ]
    assert len(matches) == 1
    assert integration.id in _compiled_params(matches[0]).values()


@pytest.mark.asyncio
async def test_disconnect_soft_revokes_ingest_token_not_hard_delete():
    integration = _make_integration()
    db = _make_db()
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)

    stmts = [call.args[0] for call in db.execute.call_args_list]
    updates = [
        s
        for s in stmts
        if isinstance(s, Update)
        and s.entity_description["entity"] is IntegrationIngestToken
    ]
    assert len(updates) == 1
    compiled_sql = str(updates[0].compile())
    assert "revoked_at" in compiled_sql
    assert "IS NULL" in compiled_sql.upper()
    assert integration.id in _compiled_params(updates[0]).values()

    # No Delete construct anywhere targets IntegrationIngestToken — guards
    # against a future regression from soft-revoke back to hard-delete.
    deletes = [
        s
        for s in stmts
        if isinstance(s, Delete)
        and s.entity_description["entity"] is IntegrationIngestToken
    ]
    assert deletes == []


@pytest.mark.asyncio
async def test_disconnect_every_statement_is_scoped_to_this_integration():
    """Highest-value test: an implementation that omits
    .where(integration_id == integration.id) would delete every user's
    credentials and still pass every type-only assertion above.
    """
    integration = _make_integration()
    db = _make_db()
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)

    for call in db.execute.call_args_list:
        stmt = call.args[0]
        compiled = stmt.compile()
        assert "WHERE" in str(compiled).upper()
        assert integration.id in compiled.params.values()


@pytest.mark.asyncio
async def test_disconnect_does_not_touch_shared_oauth_account():
    integration = _make_integration()
    db = _make_db()
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)

    for call in db.execute.call_args_list:
        stmt = call.args[0]
        table_name = stmt.entity_description["entity"].__tablename__
        assert table_name not in ("oauth_accounts", "oauth_tokens")


@pytest.mark.asyncio
async def test_disconnect_idempotent_when_no_rows_match():
    integration = _make_integration()
    db = _make_db(rowcount=0)
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)
    await provider.disconnect(integration=integration, db=db)

    assert integration.status == "disconnected"
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_disconnect_log_has_no_credential_material(caplog):
    import logging

    integration = _make_integration()
    db = _make_db()
    provider = _StubProvider()

    with caplog.at_level(logging.INFO, logger="src.integrations.base"):
        await provider.disconnect(integration=integration, db=db)

    messages = [r.getMessage() for r in caplog.records]
    joined = "\n".join(messages)
    assert str(integration.id) in joined
    assert str(integration.user_id) in joined
    for forbidden in ("encrypted", "key_prefix", "token_hash", "access_token"):
        assert forbidden not in joined


@pytest.mark.asyncio
async def test_apple_health_disconnect_soft_revokes_ingest_token():
    """Regression guard for the deleted AppleHealthIntegration.disconnect()
    override: the base default must reproduce its exact semantics —
    soft-revoke, not hard-delete, and a single commit.
    """
    from src.integrations.personal.apple_health import AppleHealthIntegration

    integration = Integration(
        id=uuid.uuid4(),
        user_id=USER_ID,
        slug="apple_health",
        kind="personal_push",
        status="connected",
        config={},
    )
    db = _make_db()
    db.delete = AsyncMock()
    provider = AppleHealthIntegration()

    await provider.disconnect(integration=integration, db=db)

    assert integration.status == "disconnected"
    db.commit.assert_awaited_once()
    db.delete.assert_not_awaited()

    stmts = [call.args[0] for call in db.execute.call_args_list]
    assert [
        s
        for s in stmts
        if isinstance(s, Update)
        and s.entity_description["entity"] is IntegrationIngestToken
    ]
    assert not [
        s
        for s in stmts
        if isinstance(s, Delete)
        and s.entity_description["entity"] is IntegrationIngestToken
    ]


class _UpstreamRevokingProvider(_StubProvider):
    """Stand-in for a real OAuth/API-key provider that overrides
    _revoke_upstream() to call the third-party provider's revoke endpoint
    before local rows are deleted."""

    def __init__(self) -> None:
        self.revoke_calls: list[uuid.UUID] = []

    async def _revoke_upstream(self, *, integration, db) -> None:
        self.revoke_calls.append(integration.id)


class _FailingUpstreamRevokeProvider(_StubProvider):
    """Stand-in for a provider whose upstream revoke call fails (network
    error, already-revoked token, provider outage)."""

    async def _revoke_upstream(self, *, integration, db) -> None:
        raise RuntimeError("upstream revoke endpoint returned 503")


@pytest.mark.asyncio
async def test_disconnect_calls_revoke_upstream_hook_before_local_deletion():
    integration = _make_integration()
    db = _make_db()
    provider = _UpstreamRevokingProvider()

    await provider.disconnect(integration=integration, db=db)

    assert provider.revoke_calls == [integration.id]
    assert integration.status == "disconnected"


@pytest.mark.asyncio
async def test_disconnect_proceeds_locally_when_revoke_upstream_fails(caplog):
    import logging

    integration = _make_integration()
    db = _make_db()
    provider = _FailingUpstreamRevokeProvider()

    with caplog.at_level(logging.WARNING, logger="src.integrations.base"):
        await provider.disconnect(integration=integration, db=db)

    assert integration.status == "disconnected"
    db.commit.assert_awaited_once()
    assert any("upstream revocation failed" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_disconnect_closes_open_transaction_before_revoking_upstream():
    """.claude/rules/database.md forbids holding a transaction open across
    a network call. When the caller's own reads (auth lookup,
    _find_user_integration) left one open on `db`, disconnect() must
    close it with a commit BEFORE _revoke_upstream()'s network call runs
    — not after, and not never.
    """
    integration = _make_integration()
    db = _make_db(in_transaction=True)
    call_order: list[str] = []
    db.commit.side_effect = lambda: call_order.append("commit")

    class _OrderTrackingProvider(_StubProvider):
        async def _revoke_upstream(self, *, integration, db) -> None:
            call_order.append("revoke_upstream")

    await _OrderTrackingProvider().disconnect(integration=integration, db=db)

    assert call_order.index("commit") < call_order.index("revoke_upstream")
    # Pre-revoke commit (in_transaction guard) + post-scrub commit.
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_disconnect_skips_redundant_commit_when_no_transaction_open():
    integration = _make_integration()
    db = _make_db(in_transaction=False)
    provider = _StubProvider()

    await provider.disconnect(integration=integration, db=db)

    # Only the post-scrub commit — no gratuitous extra round trip when
    # there was nothing open to close.
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_rolls_back_on_local_deletion_failure():
    integration = _make_integration()
    db = _make_db()
    db.execute = AsyncMock(side_effect=RuntimeError("db connection lost"))
    provider = _StubProvider()

    with pytest.raises(RuntimeError):
        await provider.disconnect(integration=integration, db=db)

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    # Status must not appear flipped when the deletion itself failed.
    assert integration.status == "connected"
