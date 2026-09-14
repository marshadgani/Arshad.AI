"""FEAT-145: IntegrationProvider.disconnect() now actually removes local
credentials (and, where a provider declares support, attempts an upstream
revoke) instead of only flipping integration.status. Covers:

- scrub_credentials(): per-table row counts, and that it's atomic with the
  status flip (a scrub failure must not leave status flipped).
- The base class disconnect() sequence: prepare -> commit -> revoke (best
  effort) -> scrub + status commit, with the network call swallowed on
  failure.
- OAuthIntegrationProvider's revoke_url-driven _prepare_revocation /
  _revoke_upstream, including the decrypt-failure and non-2xx paths.
- Idempotency: disconnecting an already-disconnected integration doesn't
  raise or double-count.
- The provider registry: every registered provider declares a real
  revocation_kind value (the safety net that replaces an import-time
  raise — see base.py's revocation_kind ClassVar docstring).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import DisconnectOutcome, IntegrationProvider
from src.integrations.personal._oauth_base import OAuthIntegrationProvider
from src.integrations.registry import INTEGRATION_REGISTRY
from src.services.integration_credentials import ScrubCounts, scrub_credentials


def _execute_result(rowcount: int) -> MagicMock:
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _make_scrub_db(oauth=0, apikey=0, ingest=0) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _execute_result(oauth),
            _execute_result(apikey),
            _execute_result(ingest),
        ]
    )
    return db


# ── scrub_credentials ──────────────────────────────────────────────────────


class TestScrubCredentials:
    @pytest.mark.asyncio
    async def test_returns_per_table_row_counts(self):
        db = _make_scrub_db(oauth=1, apikey=0, ingest=0)

        counts = await scrub_credentials(db, integration_id=uuid.uuid4())

        assert counts == ScrubCounts(
            oauth_tokens_deleted=1,
            api_key_credentials_deleted=0,
            ingest_tokens_revoked=0,
        )
        assert db.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_zero_rows_when_nothing_stored(self):
        db = _make_scrub_db()

        counts = await scrub_credentials(db, integration_id=uuid.uuid4())

        assert counts == ScrubCounts(0, 0, 0)

    @pytest.mark.asyncio
    async def test_never_commits_itself(self):
        """Atomicity with the status flip is the caller's job (disconnect())
        — scrub_credentials must not call commit/rollback, or a caller
        composing it with another write could get a partial commit."""
        db = _make_scrub_db()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        await scrub_credentials(db, integration_id=uuid.uuid4())

        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()


# ── IntegrationProvider.disconnect() base sequence ──────────────────────────


class _StubProvider(IntegrationProvider):
    slug = "stub"
    kind = "project_apikey"
    display_name = "Stub"
    category = "test"
    description = "test"
    docs_url = None

    async def connect(self, *, user, db, payload): ...  # pragma: no cover
    async def sync(self, *, integration, db): ...  # pragma: no cover
    async def status(self, *, integration, db): ...  # pragma: no cover


def _fake_integration(user_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        status="connected",
        last_error=None,
    )


def _fake_disconnect_db():
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=True)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


class TestDisconnectBaseSequence:
    @pytest.mark.asyncio
    async def test_default_provider_scrubs_and_reports_unsupported(self, monkeypatch):
        provider = _StubProvider()
        integration = _fake_integration()
        db = _fake_disconnect_db()
        monkeypatch.setattr(
            "src.integrations.disconnect.scrub_credentials",
            AsyncMock(return_value=ScrubCounts(0, 1, 0)),
        )

        outcome = await provider.disconnect(integration=integration, db=db)

        assert outcome == DisconnectOutcome(
            status="disconnected", upstream_revocation="unsupported"
        )
        assert integration.status == "disconnected"
        assert integration.last_error is None

    @pytest.mark.asyncio
    async def test_prepare_revocation_commits_before_any_network_call(
        self, monkeypatch
    ):
        """Regression guard for the read-txn-across-network-call defect: the
        read transaction opened by _prepare_revocation must be committed
        before _revoke_upstream ever runs."""
        provider = _StubProvider()
        integration = _fake_integration()
        db = _fake_disconnect_db()
        call_order: list[str] = []

        async def _prepare(*, integration, db):
            call_order.append("prepare")
            return {"token": "x"}

        async def _revoke(*, payload):
            call_order.append("revoke")
            assert call_order == ["prepare", "commit", "revoke"]
            return "revoked"

        monkeypatch.setattr(provider, "_prepare_revocation", _prepare)
        monkeypatch.setattr(provider, "_revoke_upstream", _revoke)
        monkeypatch.setattr(
            "src.integrations.disconnect.scrub_credentials",
            AsyncMock(return_value=ScrubCounts(0, 0, 0)),
        )

        async def _commit():
            if "commit" not in call_order:
                call_order.append("commit")

        db.commit = AsyncMock(side_effect=_commit)

        outcome = await provider.disconnect(integration=integration, db=db)

        assert outcome.upstream_revocation == "revoked"

    @pytest.mark.asyncio
    async def test_revoke_failure_still_scrubs_and_reports_disconnected(
        self, monkeypatch
    ):
        provider = _StubProvider()
        integration = _fake_integration()
        db = _fake_disconnect_db()
        monkeypatch.setattr(
            provider, "_prepare_revocation", AsyncMock(return_value={"token": "x"})
        )
        monkeypatch.setattr(
            provider,
            "_revoke_upstream",
            AsyncMock(side_effect=httpx.TimeoutException("boom")),
        )
        monkeypatch.setattr(
            "src.integrations.disconnect.scrub_credentials",
            AsyncMock(return_value=ScrubCounts(1, 0, 0)),
        )

        outcome = await provider.disconnect(integration=integration, db=db)

        assert outcome.status == "disconnected"
        assert outcome.upstream_revocation == "failed"
        assert integration.status == "disconnected"

    @pytest.mark.asyncio
    async def test_scrub_failure_rolls_back_and_leaves_status_unchanged(
        self, monkeypatch
    ):
        provider = _StubProvider()
        integration = _fake_integration()
        integration.status = "connected"
        db = _fake_disconnect_db()
        monkeypatch.setattr(
            "src.integrations.disconnect.scrub_credentials",
            AsyncMock(side_effect=RuntimeError("db exploded")),
        )

        with pytest.raises(RuntimeError):
            await provider.disconnect(integration=integration, db=db)

        db.rollback.assert_awaited_once()
        # Not flipped to 'disconnected' — the whole write txn rolled back.
        assert integration.status == "connected"

    @pytest.mark.asyncio
    async def test_idempotent_second_disconnect_is_a_clean_no_op(self, monkeypatch):
        provider = _StubProvider()
        integration = _fake_integration()
        integration.status = "disconnected"
        db = _fake_disconnect_db()
        monkeypatch.setattr(
            "src.integrations.disconnect.scrub_credentials",
            AsyncMock(return_value=ScrubCounts(0, 0, 0)),
        )

        outcome = await provider.disconnect(integration=integration, db=db)

        assert outcome.status == "disconnected"
        assert outcome.upstream_revocation == "unsupported"


# ── OAuthIntegrationProvider revoke_url-driven revocation ───────────────────


class _FakeOAuthProvider(OAuthIntegrationProvider):
    slug = "fake-oauth"
    display_name = "Fake OAuth"
    category = "test"
    description = "test"
    docs_url = None
    auth_url = "https://example.com/authorize"
    token_url = "https://example.com/token"
    revoke_url = "https://example.com/revoke"
    scopes: list[str] = []
    client_id_env = "FAKE_OAUTH_CLIENT_ID"
    client_secret_env = "FAKE_OAUTH_CLIENT_SECRET"

    async def sync(self, *, integration, db): ...  # pragma: no cover


class _FakeOAuthProviderNoRevoke(OAuthIntegrationProvider):
    slug = "fake-oauth-no-revoke"
    display_name = "Fake OAuth No Revoke"
    category = "test"
    description = "test"
    docs_url = None
    auth_url = "https://example.com/authorize"
    token_url = "https://example.com/token"
    scopes: list[str] = []
    client_id_env = "FAKE_OAUTH_CLIENT_ID"
    client_secret_env = "FAKE_OAUTH_CLIENT_SECRET"

    async def sync(self, *, integration, db): ...  # pragma: no cover


class TestOAuthRevocationDerivation:
    def test_revoke_url_set_derives_revokes(self):
        assert _FakeOAuthProvider.revocation_kind == "revokes"

    def test_no_revoke_url_keeps_default(self):
        assert _FakeOAuthProviderNoRevoke.revocation_kind == "no_revoke"


class TestOAuthPrepareRevocation:
    @pytest.mark.asyncio
    async def test_no_revoke_url_returns_none(self, monkeypatch):
        provider = _FakeOAuthProviderNoRevoke()
        db = MagicMock()
        db.scalar = AsyncMock()

        payload = await provider._prepare_revocation(
            integration=_fake_integration(), db=db
        )

        assert payload is None
        db.scalar.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_token_row_returns_none(self, monkeypatch):
        provider = _FakeOAuthProvider()
        db = MagicMock()
        db.scalar = AsyncMock(return_value=None)

        payload = await provider._prepare_revocation(
            integration=_fake_integration(), db=db
        )

        assert payload is None

    @pytest.mark.asyncio
    async def test_decrypt_failure_returns_none_not_raises(self, monkeypatch):
        provider = _FakeOAuthProvider()
        token_row = SimpleNamespace(
            encrypted_access_token=b"garbage", encrypted_refresh_token=None
        )
        db = MagicMock()
        db.scalar = AsyncMock(return_value=token_row)
        monkeypatch.setattr(
            "src.integrations.personal._oauth_base.decrypt",
            MagicMock(side_effect=Exception("bad ciphertext")),
        )

        payload = await provider._prepare_revocation(
            integration=_fake_integration(), db=db
        )

        assert payload is None

    @pytest.mark.asyncio
    async def test_happy_path_decrypts_both_tokens(self, monkeypatch):
        provider = _FakeOAuthProvider()
        token_row = SimpleNamespace(
            encrypted_access_token=b"enc-access", encrypted_refresh_token=b"enc-refresh"
        )
        db = MagicMock()
        db.scalar = AsyncMock(return_value=token_row)
        monkeypatch.setattr(
            "src.integrations.personal._oauth_base.decrypt",
            lambda blob: {"enc-access": "access-1", "enc-refresh": "refresh-1"}[
                blob.decode()
            ],
        )

        payload = await provider._prepare_revocation(
            integration=_fake_integration(), db=db
        )

        assert payload == {"access_token": "access-1", "refresh_token": "refresh-1"}


class TestOAuthRevokeUpstream:
    @pytest.mark.asyncio
    async def test_2xx_reports_revoked(self, monkeypatch):
        provider = _FakeOAuthProvider()
        monkeypatch.setenv("FAKE_OAUTH_CLIENT_ID", "id")
        monkeypatch.setenv("FAKE_OAUTH_CLIENT_SECRET", "secret")
        resp = httpx.Response(200, request=httpx.Request("POST", provider.revoke_url))
        monkeypatch.setattr(
            provider, "_post_revoke_request", AsyncMock(return_value=resp)
        )

        outcome = await provider._revoke_upstream(
            payload={"access_token": "a", "refresh_token": "r"}
        )

        assert outcome == "revoked"
        assert provider._post_revoke_request.await_count == 2  # refresh + access

    @pytest.mark.asyncio
    async def test_non_2xx_reports_failed(self, monkeypatch):
        provider = _FakeOAuthProvider()
        resp = httpx.Response(400, request=httpx.Request("POST", provider.revoke_url))
        monkeypatch.setattr(
            provider, "_post_revoke_request", AsyncMock(return_value=resp)
        )

        outcome = await provider._revoke_upstream(payload={"access_token": "a"})

        assert outcome == "failed"

    @pytest.mark.asyncio
    async def test_request_exception_reports_failed_not_raises(self, monkeypatch):
        provider = _FakeOAuthProvider()
        monkeypatch.setattr(
            provider,
            "_post_revoke_request",
            AsyncMock(side_effect=httpx.ConnectError("down")),
        )

        outcome = await provider._revoke_upstream(payload={"access_token": "a"})

        assert outcome == "failed"

    @pytest.mark.asyncio
    async def test_no_tokens_in_payload_reports_failed(self):
        provider = _FakeOAuthProvider()

        outcome = await provider._revoke_upstream(
            payload={"access_token": None, "refresh_token": None}
        )

        assert outcome == "failed"


# ── Registry-wide safety net ─────────────────────────────────────────────


class TestRegistryRevocationDeclarations:
    def test_every_registered_provider_has_a_valid_revocation_kind(self):
        """The safety net that replaces an import-time raise (see base.py's
        revocation_kind ClassVar docstring for why an import-time raise was
        rejected): this fails a CI run, loudly, the moment a new provider
        is registered with a bogus value — without being able to crash
        production boot the way the rejected design could.
        """
        assert len(INTEGRATION_REGISTRY) > 0
        for provider in INTEGRATION_REGISTRY.values():
            assert provider.revocation_kind in ("revokes", "no_revoke", "no_credential")

    def test_apple_health_declares_no_revoke_not_no_credential(self):
        """Apple Health DOES store a real local credential (the ingest
        token) — unlike the Google/GitHub 'no_credential' family — it just
        has no upstream provider to revoke with."""
        provider = INTEGRATION_REGISTRY["apple_health"]
        assert provider.revocation_kind == "no_revoke"

    def test_shared_google_oauth_providers_declare_no_credential(self):
        for slug in (
            "gmail",
            "google_calendar",
            "google_drive",
            "google_tasks",
            "youtube",
            "github",
        ):
            assert INTEGRATION_REGISTRY[slug].revocation_kind == "no_credential"

    def test_plaid_declares_revokes(self):
        assert INTEGRATION_REGISTRY["plaid"].revocation_kind == "revokes"
