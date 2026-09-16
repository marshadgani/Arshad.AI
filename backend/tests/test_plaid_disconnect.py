"""FEAT-161 — Plaid disconnect: reads ApiKeyCredential (not
IntegrationOAuthToken — Plaid is personal_apikey), uses the environment
recorded at connect time, and preserves item_id when the upstream
/item/remove call fails so the Item stays manually removable."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.personal.plaid import PlaidIntegration
from src.models.integration import ApiKeyCredential, Integration
from src.services.integration_credentials import ScrubCounts

pytestmark = pytest.mark.asyncio


def _fake_creds(
    env: str = "sandbox", item_id: str | None = "item-123"
) -> ApiKeyCredential:
    creds = MagicMock(spec=ApiKeyCredential)
    creds.encrypted_key = b"\x00" * 28  # decrypt() is monkeypatched below
    creds.extra = {"env": env, "item_id": item_id} if item_id else {"env": env}
    return creds


def _fake_integration() -> Integration:
    integration = MagicMock(spec=Integration)
    integration.id = uuid.uuid4()
    integration.config = {}
    return integration


def _mock_post(monkeypatch, status_code: int):
    fake_response = MagicMock()
    fake_response.status_code = status_code

    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake_client)
    return fake_client


async def test_prepare_revocation_reads_api_key_credential_not_oauth_token(monkeypatch):
    provider = PlaidIntegration()
    integration = _fake_integration()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=_fake_creds())
    monkeypatch.setattr(
        "src.integrations.personal.plaid.decrypt", lambda blob: "access-sandbox-abc"
    )

    payload = await provider._prepare_revocation(integration=integration, db=db)

    assert payload["access_token"] == "access-sandbox-abc"
    assert payload["env"] == "sandbox"
    assert payload["_preserve"] == {"plaid_item_id": "item-123"}


async def test_prepare_revocation_no_credential_returns_none():
    provider = PlaidIntegration()
    integration = _fake_integration()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)

    payload = await provider._prepare_revocation(integration=integration, db=db)

    assert payload is None


async def test_revoke_upstream_uses_env_from_credential_extra(monkeypatch):
    """Regression guard for the production-host blocker: the base URL must
    come from the credential's stored env, never a hardcoded production
    host."""
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "secret")
    fake_client = _mock_post(monkeypatch, 200)
    provider = PlaidIntegration()

    result = await provider._revoke_upstream(
        payload={"access_token": "tok", "env": "sandbox"}
    )

    assert result == "revoked"
    called_url = fake_client.post.call_args.args[0]
    assert called_url == "https://sandbox.plaid.com/item/remove"


async def test_revoke_upstream_falls_back_to_plaid_env_when_extra_has_no_env(
    monkeypatch,
):
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "secret")
    monkeypatch.setenv("PLAID_ENV", "development")
    fake_client = _mock_post(monkeypatch, 200)
    provider = PlaidIntegration()

    await provider._revoke_upstream(payload={"access_token": "tok", "env": None})

    called_url = fake_client.post.call_args.args[0]
    assert called_url == "https://development.plaid.com/item/remove"


async def test_revoke_upstream_posts_client_id_secret_access_token(monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid-1")
    monkeypatch.setenv("PLAID_SECRET", "secret-1")
    fake_client = _mock_post(monkeypatch, 200)
    provider = PlaidIntegration()

    await provider._revoke_upstream(payload={"access_token": "tok-1", "env": "sandbox"})

    body = fake_client.post.call_args.kwargs["json"]
    assert body == {"client_id": "cid-1", "secret": "secret-1", "access_token": "tok-1"}


async def test_revoke_upstream_non_200_is_failed(monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "secret")
    _mock_post(monkeypatch, 400)
    provider = PlaidIntegration()

    result = await provider._revoke_upstream(
        payload={"access_token": "tok", "env": "sandbox"}
    )

    assert result == "failed"


async def test_revoke_upstream_missing_plaid_credentials_is_unsupported(monkeypatch):
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    monkeypatch.delenv("PLAID_SECRET", raising=False)
    provider = PlaidIntegration()

    result = await provider._revoke_upstream(
        payload={"access_token": "tok", "env": "sandbox"}
    )

    assert result == "unsupported"


async def test_revoke_upstream_no_access_token_is_unsupported():
    provider = PlaidIntegration()

    result = await provider._revoke_upstream(payload={"env": "sandbox"})

    assert result == "unsupported"


async def test_full_disconnect_failure_preserves_item_id_in_config(monkeypatch):
    """End-to-end through base.disconnect(): even when /item/remove fails,
    the Item stays recoverable via config['last_disconnect']['plaid_item_id']."""
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "secret")
    _mock_post(monkeypatch, 500)
    monkeypatch.setattr(
        "src.integrations.personal.plaid.decrypt", lambda blob: "access-sandbox-abc"
    )
    monkeypatch.setattr(
        "src.integrations.base.scrub_credentials",
        AsyncMock(return_value=ScrubCounts(0, 1, 0)),
    )

    provider = PlaidIntegration()
    integration = _fake_integration()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=_fake_creds(item_id="item-999"))
    db.commit = AsyncMock()

    outcome = await provider.disconnect(integration=integration, db=db)

    assert outcome.upstream_revocation == "failed"
    assert integration.config["last_disconnect"]["plaid_item_id"] == "item-999"
