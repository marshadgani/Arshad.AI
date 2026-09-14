"""Regression test: Google OAuth login requires a verified email.

FEAT-158 gate finding — AUTH_ALLOWED_EMAILS (auth/allowlist.py) makes the
email claim from fetch_user_info() the entire login/ownership decision,
and upsert_user_from_oauth links accounts across providers by email. An
unverified email would let an attacker who can set an arbitrary address
on their own Google account impersonate the owner.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.auth.providers.base import OAuthError
from src.auth.providers.google import GoogleOAuthProvider


def _make_provider(monkeypatch) -> GoogleOAuthProvider:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("BACKEND_URL", "https://test.example.com")
    return GoogleOAuthProvider()


def _mock_userinfo_response(payload: dict) -> AsyncMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client_cls


@pytest.mark.asyncio
async def test_fetch_user_info_rejects_unverified_email(monkeypatch):
    provider = _make_provider(monkeypatch)
    mock_client_cls = _mock_userinfo_response(
        {
            "sub": "provider-user-1",
            "email": "attacker@example.com",
            "email_verified": False,
            "name": "Attacker",
            "picture": None,
        }
    )
    with patch("httpx.AsyncClient", mock_client_cls):
        with pytest.raises(OAuthError) as exc_info:
            await provider.fetch_user_info("token")
    assert exc_info.value.code == "google_email_unverified"


@pytest.mark.asyncio
async def test_fetch_user_info_rejects_missing_email_verified_field(monkeypatch):
    """Absent email_verified must fail closed, not be treated as verified."""
    provider = _make_provider(monkeypatch)
    mock_client_cls = _mock_userinfo_response(
        {
            "sub": "provider-user-2",
            "email": "someone@example.com",
            "name": "Someone",
            "picture": None,
        }
    )
    with patch("httpx.AsyncClient", mock_client_cls):
        with pytest.raises(OAuthError) as exc_info:
            await provider.fetch_user_info("token")
    assert exc_info.value.code == "google_email_unverified"


@pytest.mark.asyncio
async def test_fetch_user_info_allows_verified_email(monkeypatch):
    provider = _make_provider(monkeypatch)
    mock_client_cls = _mock_userinfo_response(
        {
            "sub": "provider-user-3",
            "email": "Owner@Example.com",
            "email_verified": True,
            "name": "Owner",
            "picture": "https://example.com/pic.jpg",
        }
    )
    with patch("httpx.AsyncClient", mock_client_cls):
        info = await provider.fetch_user_info("token")
    assert info.email == "owner@example.com"
    assert info.provider_user_id == "provider-user-3"
