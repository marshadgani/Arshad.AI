"""FEAT-145 gap: PlaidIntegration._prepare_revocation / _revoke_upstream had
zero test coverage. Plaid is the one provider that hand-rolls its own
revocation hooks (item/remove) instead of going through
OAuthIntegrationProvider's generic revoke_url machinery — every branch here
was previously unverified:

- no ApiKeyCredential row -> None (disconnect() reports 'unsupported')
- corrupt ciphertext -> None, not raised (disconnect() must not blow up)
- PLAID_CLIENT_ID/PLAID_SECRET missing -> None, not raised
- happy path -> payload carries the decrypted access_token + plaid creds
- item/remove 2xx -> 'revoked'
- item/remove 4xx/5xx -> 'failed', not raised
- item/remove network error -> 'failed', not raised

Mocking pattern follows test_shopify_client.py: monkeypatch httpx.AsyncClient
at the module boundary so no real network calls are made.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.personal.plaid import PlaidIntegration

pytestmark = pytest.mark.asyncio


def _mock_httpx_client(
    response: MagicMock | None = None, *, raises: Exception | None = None
) -> MagicMock:
    mock_client = AsyncMock()
    if raises is not None:
        mock_client.post = AsyncMock(side_effect=raises)
    else:
        mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    return resp


def _fake_integration() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4())


def _db_with_credential(encrypted_key: bytes | None) -> MagicMock:
    db = MagicMock()
    if encrypted_key is None:
        db.scalar = AsyncMock(return_value=None)
    else:
        row = SimpleNamespace(encrypted_key=encrypted_key)
        db.scalar = AsyncMock(return_value=row)
    return db


# ── _prepare_revocation ──────────────────────────────────────────────────


async def test_prepare_revocation_returns_none_when_no_credential_row():
    provider = PlaidIntegration()
    db = _db_with_credential(None)

    payload = await provider._prepare_revocation(integration=_fake_integration(), db=db)

    assert payload is None


async def test_prepare_revocation_returns_none_on_decrypt_failure(monkeypatch):
    provider = PlaidIntegration()
    db = _db_with_credential(b"corrupt-ciphertext")
    monkeypatch.setattr(
        "src.integrations.personal.plaid.decrypt",
        MagicMock(side_effect=Exception("bad ciphertext")),
    )

    payload = await provider._prepare_revocation(integration=_fake_integration(), db=db)

    assert payload is None


async def test_prepare_revocation_returns_none_when_plaid_not_configured(
    monkeypatch,
):
    """PLAID_CLIENT_ID/PLAID_SECRET unset -> _plaid_creds() raises
    IntegrationError, which must be swallowed here (disconnect() still has
    to scrub locally) rather than propagate and block the disconnect."""
    provider = PlaidIntegration()
    db = _db_with_credential(b"enc-token")
    monkeypatch.setattr(
        "src.integrations.personal.plaid.decrypt", lambda _blob: "access-sandbox-xyz"
    )
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    monkeypatch.delenv("PLAID_SECRET", raising=False)

    payload = await provider._prepare_revocation(integration=_fake_integration(), db=db)

    assert payload is None


async def test_prepare_revocation_happy_path_returns_token_and_creds(monkeypatch):
    provider = PlaidIntegration()
    db = _db_with_credential(b"enc-token")
    monkeypatch.setattr(
        "src.integrations.personal.plaid.decrypt", lambda _blob: "access-sandbox-xyz"
    )
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "secret")

    payload = await provider._prepare_revocation(integration=_fake_integration(), db=db)

    assert payload == {
        "access_token": "access-sandbox-xyz",
        "client_id": "cid",
        "secret": "secret",
    }


# ── _revoke_upstream ──────────────────────────────────────────────────────


async def test_revoke_upstream_2xx_reports_revoked(monkeypatch):
    provider = PlaidIntegration()
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _mock_httpx_client(_response(200))
    )

    outcome = await provider._revoke_upstream(
        payload={"access_token": "tok", "client_id": "cid", "secret": "sec"}
    )

    assert outcome == "revoked"


async def test_revoke_upstream_4xx_reports_failed_not_raises(monkeypatch):
    provider = PlaidIntegration()
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _mock_httpx_client(_response(400, "INVALID_ACCESS_TOKEN")),
    )

    outcome = await provider._revoke_upstream(
        payload={"access_token": "tok", "client_id": "cid", "secret": "sec"}
    )

    assert outcome == "failed"


async def test_revoke_upstream_5xx_reports_failed_not_raises(monkeypatch):
    provider = PlaidIntegration()
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _mock_httpx_client(_response(500, "boom"))
    )

    outcome = await provider._revoke_upstream(
        payload={"access_token": "tok", "client_id": "cid", "secret": "sec"}
    )

    assert outcome == "failed"


async def test_revoke_upstream_network_error_reports_failed_not_raises(monkeypatch):
    provider = PlaidIntegration()
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _mock_httpx_client(raises=httpx.ConnectError("down")),
    )

    outcome = await provider._revoke_upstream(
        payload={"access_token": "tok", "client_id": "cid", "secret": "sec"}
    )

    assert outcome == "failed"


# ── end-to-end: disconnect() drives Plaid's hooks correctly ────────────────


async def test_disconnect_calls_item_remove_and_scrubs_credential(monkeypatch):
    """Wiring check: IntegrationProvider.disconnect() -> run_disconnect()
    actually invokes Plaid's overridden hooks (not the ABC's no-op
    defaults), in the prepare -> commit -> revoke -> scrub order."""
    provider = PlaidIntegration()
    integration = _fake_integration()
    db = MagicMock()
    db.in_transaction = MagicMock(return_value=True)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(encrypted_key=b"enc-token"))
    integration.status = "connected"
    integration.last_error = "prior error"

    monkeypatch.setattr(
        "src.integrations.personal.plaid.decrypt", lambda _blob: "access-sandbox-xyz"
    )
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "secret")
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _mock_httpx_client(_response(200))
    )
    monkeypatch.setattr(
        "src.integrations.disconnect.scrub_credentials",
        AsyncMock(return_value=MagicMock()),
    )

    outcome = await provider.disconnect(integration=integration, db=db)

    assert outcome.upstream_revocation == "revoked"
    assert outcome.status == "disconnected"
    assert integration.status == "disconnected"
    assert integration.last_error is None
