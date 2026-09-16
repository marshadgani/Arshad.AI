"""FEAT-161 — disconnect() actually revokes and scrubs credentials.

Covers:
  - registry-walk: every registered provider declares revocation_kind
  - no_credential providers never touch a credential row
  - IntegrationProvider.disconnect() sequencing (commit before network call,
    scrub + status flip in one atomic commit, rollback on commit failure)
  - OAuthIntegrationProvider._revoke_upstream() RFC 7009 semantics
  - the disconnect router surfaces upstream_revocation without changing
    the HTTP status
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import DisconnectOutcome, IntegrationProvider
from src.integrations.personal._oauth_base import OAuthIntegrationProvider
from src.integrations.registry import INTEGRATION_REGISTRY
from src.models.integration import Integration
from src.services.integration_credentials import ScrubCounts, scrub_credentials

# ── registry-walk completeness ──────────────────────────────────────────


def test_registry_walk_every_provider_has_explicit_revocation_kind():
    """A provider that forgets to declare revocation_kind must fail CI,
    not silently inherit a value that misrepresents what disconnect()
    does for it. Walk the MRO rather than checking type(p).__dict__
    directly — factory-generated bulk providers (project/bulk_providers.py)
    inherit the ClassVar from _ApiKeyProvider, not their own class."""
    assert INTEGRATION_REGISTRY, (
        "registry must not be empty for this test to mean anything"
    )
    for slug, provider in INTEGRATION_REGISTRY.items():
        defining_cls = next(
            cls for cls in type(provider).__mro__ if "revocation_kind" in cls.__dict__
        )
        assert defining_cls is not IntegrationProvider, (
            f"{slug} inherits revocation_kind from the ABC itself — "
            "it never declared one"
        )
        assert provider.revocation_kind in ("revokes", "no_revoke", "no_credential")


def test_oauth_providers_revoke_url_and_kind_are_consistent():
    for slug, provider in INTEGRATION_REGISTRY.items():
        if not isinstance(provider, OAuthIntegrationProvider):
            continue
        has_url = provider.revoke_url is not None
        is_revokes = provider.revocation_kind == "revokes"
        assert has_url == is_revokes, (
            f"{slug}: revoke_url={provider.revoke_url!r} but "
            f"revocation_kind={provider.revocation_kind!r} — these must agree"
        )


@pytest.mark.parametrize(
    "slug",
    ["gmail", "google_calendar", "google_drive", "google_tasks", "youtube", "github"],
)
@pytest.mark.asyncio
async def test_no_credential_providers_scrub_zero_rows(slug):
    provider = INTEGRATION_REGISTRY[slug]
    assert provider.revocation_kind == "no_credential"
    db = _fake_db(rowcount=0)
    counts = await scrub_credentials(integration_id=uuid.uuid4(), db=db)
    assert counts == ScrubCounts(oauth_rows=0, apikey_rows=0, ingest_rows=0)


# ── test doubles ────────────────────────────────────────────────────────


def _fake_db(rowcount: int = 0):
    db = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    return db


def _fake_integration(config: dict | None = None) -> Integration:
    integration = MagicMock(spec=Integration)
    integration.id = uuid.uuid4()
    integration.status = "connected"
    integration.last_error = None
    integration.config = config or {}
    return integration


class _RevokesProvider(IntegrationProvider):
    """Minimal concrete provider exercising the revokes path directly,
    without needing DB/HTTP fixtures for every abstract method."""

    slug = "fake-revokes"
    kind = "personal_oauth"
    display_name = "Fake Revokes"
    category = "test"
    description = "test"
    revocation_kind = "revokes"

    async def connect(self, *, user, db, payload): ...  # type: ignore[override]
    async def sync(self, *, integration, db): ...  # type: ignore[override]
    async def status(self, *, integration, db): ...  # type: ignore[override]


# ── disconnect() sequencing ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disconnect_commits_before_calling_revoke_upstream(monkeypatch):
    """Load-bearing ordering test: _revoke_upstream must run after the read
    transaction has already been committed, never before."""
    provider = _RevokesProvider()
    integration = _fake_integration()
    db = _fake_db()

    call_order: list[str] = []

    async def _prepare(*, integration, db):
        call_order.append("prepare")
        return {"access_token": "tok"}

    async def _revoke(*, payload):
        call_order.append("revoke")
        assert call_order == ["prepare", "commit", "revoke"], call_order
        return "revoked"

    original_commit = db.commit

    async def _commit():
        if "commit" not in call_order:
            call_order.append("commit")
        await original_commit()

    db.commit = _commit
    provider._prepare_revocation = _prepare
    provider._revoke_upstream = _revoke

    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(0, 0, 0)),
    )

    outcome = await provider.disconnect(integration=integration, db=db)

    assert outcome == DisconnectOutcome(upstream_revocation="revoked")
    assert integration.status == "disconnected"
    assert integration.last_error is None


@pytest.mark.asyncio
async def test_disconnect_upstream_exception_does_not_block_local_scrub(monkeypatch):
    provider = _RevokesProvider()
    integration = _fake_integration()
    db = _fake_db()

    provider._prepare_revocation = AsyncMock(return_value={"access_token": "tok"})
    provider._revoke_upstream = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(1, 0, 0)),
    )

    outcome = await provider.disconnect(integration=integration, db=db)

    assert outcome.upstream_revocation == "failed"
    assert integration.status == "disconnected"


@pytest.mark.asyncio
async def test_disconnect_corrupt_prepare_still_scrubs_and_reports_unsupported(
    monkeypatch,
):
    provider = _RevokesProvider()
    integration = _fake_integration()
    db = _fake_db()

    provider._prepare_revocation = AsyncMock(
        side_effect=RuntimeError("corrupt ciphertext")
    )
    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(1, 0, 0)),
    )

    outcome = await provider.disconnect(integration=integration, db=db)

    assert outcome.upstream_revocation == "unsupported"
    assert integration.status == "disconnected"


@pytest.mark.asyncio
async def test_disconnect_writes_last_disconnect_audit_to_config(monkeypatch):
    provider = _RevokesProvider()
    integration = _fake_integration(config={"profile": {"id": 1}})
    db = _fake_db()

    provider._prepare_revocation = AsyncMock(return_value={"access_token": "tok"})
    provider._revoke_upstream = AsyncMock(return_value="revoked")
    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(1, 0, 1)),
    )

    await provider.disconnect(integration=integration, db=db)

    audit = integration.config["last_disconnect"]
    assert audit["upstream_revocation"] == "revoked"
    assert audit["scrub_counts"] == {
        "oauth_rows": 1,
        "apikey_rows": 0,
        "ingest_rows": 1,
    }
    assert "at" in audit
    # Original config keys survive the merge.
    assert integration.config["profile"] == {"id": 1}


@pytest.mark.asyncio
async def test_disconnect_preserves_extra_payload_keys_in_audit(monkeypatch):
    """Generic mechanism Plaid relies on to keep item_id recoverable after
    its credential row is deleted — base.py has no Plaid-specific code."""
    provider = _RevokesProvider()
    integration = _fake_integration()
    db = _fake_db()

    provider._prepare_revocation = AsyncMock(
        return_value={"access_token": "tok", "_preserve": {"plaid_item_id": "item-1"}}
    )
    provider._revoke_upstream = AsyncMock(return_value="failed")
    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(0, 1, 0)),
    )

    await provider.disconnect(integration=integration, db=db)

    assert integration.config["last_disconnect"]["plaid_item_id"] == "item-1"


@pytest.mark.asyncio
async def test_disconnect_commit_failure_rolls_back_and_propagates(monkeypatch):
    provider = _RevokesProvider()
    integration = _fake_integration()
    db = _fake_db()
    db.commit = AsyncMock(side_effect=[None, RuntimeError("db gone")])

    provider._prepare_revocation = AsyncMock(return_value=None)
    provider._revoke_upstream = AsyncMock(return_value="unsupported")
    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(0, 0, 0)),
    )

    with pytest.raises(RuntimeError):
        await provider.disconnect(integration=integration, db=db)

    db.rollback.assert_awaited_once()


# ── _oauth_base._revoke_upstream RFC 7009 semantics ─────────────────────


class _FakeOAuthProvider(OAuthIntegrationProvider):
    slug = "fake-oauth"
    display_name = "Fake OAuth"
    category = "test"
    description = "test"
    docs_url = None
    auth_url = "https://example.com/authorize"
    token_url = "https://example.com/token"
    scopes = ["read"]
    client_id_env = "FAKE_OAUTH_CLIENT_ID"
    client_secret_env = "FAKE_OAUTH_CLIENT_SECRET"
    revocation_kind = "revokes"
    revoke_url = "https://example.com/revoke"

    async def connect(self, *, user, db, payload): ...  # type: ignore[override]
    async def sync(self, *, integration, db): ...  # type: ignore[override]
    async def status(self, *, integration, db): ...  # type: ignore[override]


def _mock_httpx_client(monkeypatch, status_code: int):
    fake_response = MagicMock()
    fake_response.status_code = status_code
    fake_response.text = "error body"

    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake_client)
    return fake_client


@pytest.mark.asyncio
async def test_revoke_upstream_200_is_revoked(monkeypatch):
    monkeypatch.setenv("FAKE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("FAKE_OAUTH_CLIENT_SECRET", "secret")
    _mock_httpx_client(monkeypatch, 200)
    provider = _FakeOAuthProvider()

    result = await provider._revoke_upstream(
        payload={"access_token": "tok", "refresh_token": ""}
    )

    assert result == "revoked"


@pytest.mark.asyncio
async def test_revoke_upstream_401_is_treated_as_already_revoked(monkeypatch):
    """RFC 7009: an unrecognised token is already revoked, not an error."""
    monkeypatch.setenv("FAKE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("FAKE_OAUTH_CLIENT_SECRET", "secret")
    _mock_httpx_client(monkeypatch, 401)
    provider = _FakeOAuthProvider()

    result = await provider._revoke_upstream(
        payload={"access_token": "tok", "refresh_token": ""}
    )

    assert result == "revoked"


@pytest.mark.asyncio
async def test_revoke_upstream_500_is_failed(monkeypatch):
    monkeypatch.setenv("FAKE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("FAKE_OAUTH_CLIENT_SECRET", "secret")
    _mock_httpx_client(monkeypatch, 500)
    provider = _FakeOAuthProvider()

    result = await provider._revoke_upstream(
        payload={"access_token": "tok", "refresh_token": ""}
    )

    assert result == "failed"


@pytest.mark.asyncio
async def test_revoke_upstream_no_revoke_url_is_unsupported():
    provider = _FakeOAuthProvider()
    provider.revoke_url = None

    result = await provider._revoke_upstream(payload={"access_token": "tok"})

    assert result == "unsupported"


@pytest.mark.asyncio
async def test_revoke_upstream_no_payload_is_unsupported():
    provider = _FakeOAuthProvider()

    result = await provider._revoke_upstream(payload=None)

    assert result == "unsupported"


@pytest.mark.asyncio
async def test_prepare_revocation_missing_row_returns_none():
    provider = _FakeOAuthProvider()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    integration = _fake_integration()

    payload = await provider._prepare_revocation(integration=integration, db=db)

    assert payload is None
