"""Fixtures shared by integration-router tests.

Provides:
  async_client        — httpx AsyncClient wired to the FastAPI app with get_db
                        and get_current_user overridden so tests need no real DB.
  auth_headers        — Authorization: Bearer <valid JWT for test_user_id>
  patch_provider_sync — context manager stubbing a provider's sync() by SLUG.

All DB work in test_routers_sync.py is patched at the service/dao layer;
these fixtures just ensure the HTTP layer resolves auth and a DB session
without hitting Postgres.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.jwt import encode_jwt
from src.models.user import User

# Stable test user — reused across the session so JWT and DB mock line up.
_TEST_USER_ID = uuid.uuid4()


def _make_test_user() -> User:
    user = MagicMock(spec=User)
    user.id = _TEST_USER_ID
    user.email = "test@example.com"
    return user


async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a trivial AsyncMock session. Tests that need DB behaviour
    patch at the service layer, not here."""
    session = AsyncMock(spec=AsyncSession)
    yield session


@contextmanager
def patch_provider_sync(slug: str, result: object) -> Iterator[AsyncMock]:
    """Stub the registered provider's ``sync()`` for ``slug``.

    Resolves the provider through the registry — the same lookup the router
    itself performs — rather than naming a concrete class. An earlier revision
    of these tests patched
    ``personal.google_calendar.GoogleCalendarProvider.sync``; the shipped class
    is ``GoogleCalendarIntegration``, so every one of those patches raised
    AttributeError and the tests never ran against real code. Keying off the
    slug makes that class of drift impossible: if the slug stops resolving, the
    router is broken too, and the test fails for the right reason.
    """
    from src.integrations.registry import get_provider

    provider = get_provider(slug)
    assert provider is not None, f"no provider registered for slug {slug!r}"
    stub = AsyncMock(return_value=result)
    with patch.object(type(provider), "sync", new=stub):
        yield stub


@pytest.fixture(scope="session")
def test_user() -> User:
    return _make_test_user()


@pytest.fixture(scope="session")
def auth_headers() -> dict:
    token = encode_jwt(_TEST_USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture()
async def async_client(test_user: User) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient backed by the FastAPI app.

    get_db is replaced with a no-op session; get_current_user is replaced
    with a function that returns the session-scoped test_user without
    hitting the database.
    """
    from src.auth.dependencies import get_current_user
    from src.main import app
    from src.models.database import get_db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: test_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
