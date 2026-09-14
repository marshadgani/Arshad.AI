"""SEC-003 / SEC-001 regressions for the login boundary.

1. Account linking in auth/service.py merges a second provider identity
   into an existing user whenever the emails match, so an *unverified*
   Google email is an account-takeover primitive.
2. The OAuth callback creates a User row for any account that completes
   consent; AUTH_ALLOWED_EMAILS is the gate that keeps a single-user
   deployment single-user.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.auth.providers.base import OAuthError
from src.auth.providers.google import GoogleOAuthProvider
from src.auth.routers import _allowed_login_emails


def _userinfo_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


def _client_returning(resp: MagicMock) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_google_unverified_email_is_rejected(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    resp = _userinfo_response(
        {"sub": "1", "email": "Victim@Example.com", "email_verified": False}
    )
    with patch(
        "src.auth.providers.google.httpx.AsyncClient",
        return_value=_client_returning(resp),
    ):
        with pytest.raises(OAuthError) as exc_info:
            await GoogleOAuthProvider().fetch_user_info("tok")
    assert exc_info.value.code == "google_email_not_verified"


@pytest.mark.asyncio
async def test_google_verified_email_is_accepted_and_lowered(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    resp = _userinfo_response(
        {"sub": "1", "email": "User@Example.com", "email_verified": True}
    )
    with patch(
        "src.auth.providers.google.httpx.AsyncClient",
        return_value=_client_returning(resp),
    ):
        info = await GoogleOAuthProvider().fetch_user_info("tok")
    assert info.email == "user@example.com"


def test_allowlist_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    assert _allowed_login_emails() == set()


def test_allowlist_is_parsed_case_insensitively(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", " Owner@Example.com , b@x.io ,")
    assert _allowed_login_emails() == {"owner@example.com", "b@x.io"}
