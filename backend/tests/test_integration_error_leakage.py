"""Regression tests for SEC-002: a failed sync must never echo a stored
credential back to the client or persist one in `integration.last_error`.

httpx puts the *full request URL* in the message of HTTPStatusError and
RequestError. OpenWeatherMap authenticates with `?appid=<key>` and Stack
Exchange with `?access_token=<token>`, so the old
`f"{type(exc).__name__}: {exc}"` shape put a plaintext credential into
- the 400 body of POST /api/v1/integrations/{slug}/sync, and
- `integration.last_error`, which GET /{slug}/status returns verbatim.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.integrations.base import IntegrationError, safe_detail
from src.integrations.project._shared import mark_error

_SECRET = "sk-live-supersecret-key"
_LEAKY_URL = f"https://api.openweathermap.org/data/2.5/weather?q=X&appid={_SECRET}"


def _leaky_status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", _LEAKY_URL)
    response = httpx.Response(429, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("raise_for_status did not raise")


def test_leaky_exception_really_does_contain_the_credential():
    # Guards the premise: if httpx ever stops embedding the URL, the tests
    # below would pass vacuously.
    assert _SECRET in str(_leaky_status_error())


def test_safe_detail_omits_credential_but_keeps_status_code():
    detail = safe_detail(_leaky_status_error())
    assert _SECRET not in detail
    assert "appid" not in detail
    assert "429" in detail


def test_safe_detail_of_arbitrary_exception_is_type_name_only():
    assert safe_detail(ValueError(f"boom {_SECRET}")) == "ValueError"


class _FakeIntegration:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.status = "connected"
        self.last_error = None


@pytest.mark.asyncio
async def test_mark_error_does_not_persist_credential_in_last_error():
    integration = _FakeIntegration()
    db = MagicMock()
    db.commit = AsyncMock()

    await mark_error(integration=integration, db=db, err=_leaky_status_error())

    assert integration.status == "error"
    assert _SECRET not in integration.last_error
    assert "429" in integration.last_error


@pytest.mark.asyncio
async def test_openweathermap_sync_error_does_not_leak_api_key():
    from src.integrations.personal.openweathermap import OpenWeatherMapIntegration

    integration = _FakeIntegration()
    integration.config = {"city": "London"}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"blob"))
    db.commit = AsyncMock()

    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=_leaky_status_error())
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "src.integrations.personal.openweathermap.httpx.AsyncClient",
            return_value=client,
        ),
        patch(
            "src.integrations.personal.openweathermap.decrypt", return_value=_SECRET
        ),
    ):
        with pytest.raises(IntegrationError) as exc_info:
            await OpenWeatherMapIntegration().sync(integration=integration, db=db)

    assert exc_info.value.code == "sync_failed"
    assert _SECRET not in exc_info.value.message
    assert _SECRET not in (integration.last_error or "")
