"""FEAT-158: get_current_user re-checks AUTH_ALLOWED_EMAILS on every request.

This is the central fix, not the OAuth-callback check alone — a JWT
issued before AUTH_ALLOWED_EMAILS existed (or during any future gap)
stays valid for JWT_EXPIRY_HOURS regardless of what happens at login, so
revoking access for an already-issued session requires re-checking the
allowlist here, on every authenticated request. Calls the REAL
get_current_user with a mocked DB, not a dependency override, so this
still fails if the real check is ever deleted or weakened.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.auth.dependencies import get_current_user
from src.auth.jwt import encode_jwt

USER_ID = uuid.uuid4()


def _mock_db_with_user(email: str) -> MagicMock:
    user = MagicMock()
    user.id = USER_ID
    user.email = email
    db = MagicMock()
    db.scalar = AsyncMock(return_value=user)
    return db


@pytest.mark.asyncio
async def test_get_current_user_denies_email_no_longer_on_allowlist(monkeypatch):
    """A JWT for a user whose email is not on AUTH_ALLOWED_EMAILS is rejected
    on every request, not just at login — closing sessions that predate the
    allowlist or were issued during a gap in it."""
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    token = encode_jwt(USER_ID)
    db = _mock_db_with_user("attacker@example.com")

    with pytest.raises(Exception) as exc_info:
        await get_current_user(authorization=f"Bearer {token}", db=db)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "email_not_allowed"


@pytest.mark.asyncio
async def test_get_current_user_allows_email_on_allowlist(monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", "owner@example.com")
    token = encode_jwt(USER_ID)
    db = _mock_db_with_user("owner@example.com")

    user = await get_current_user(authorization=f"Bearer {token}", db=db)
    assert user.email == "owner@example.com"


@pytest.mark.asyncio
async def test_get_current_user_denies_by_default_when_allowlist_unset(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("AUTH_ALLOW_ALL_LOGINS", raising=False)
    token = encode_jwt(USER_ID)
    db = _mock_db_with_user("anyone@example.com")

    with pytest.raises(Exception) as exc_info:
        await get_current_user(authorization=f"Bearer {token}", db=db)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"]["code"] == "email_not_allowed"


@pytest.mark.asyncio
async def test_get_current_user_allows_with_local_dev_opt_in(monkeypatch):
    monkeypatch.delenv("AUTH_ALLOWED_EMAILS", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_ALL_LOGINS", "true")
    token = encode_jwt(USER_ID)
    db = _mock_db_with_user("anyone@example.com")

    user = await get_current_user(authorization=f"Bearer {token}", db=db)
    assert user.email == "anyone@example.com"
