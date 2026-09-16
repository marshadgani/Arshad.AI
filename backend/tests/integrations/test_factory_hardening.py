"""Tests for _factory.py's widened exception handling (FEAT-069).

Before this fix:
  - connect()'s try/except only matched IntegrationError and httpx.HTTPError,
    so a bare Exception raised by spec.parse_probe (the Slack case) or a
    json.JSONDecodeError from resp.json() propagated as an unhandled 500.
  - sync() called spec.parse_sync(body) OUTSIDE its try block entirely, so
    a parse_sync failure also propagated unhandled.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from src.integrations.base import IntegrationError
from src.integrations.project._factory import ProviderSpec, make_provider


def _spec(**overrides) -> ProviderSpec:
    defaults = dict(
        slug="test_provider",
        display_name="Test Provider",
        category="Infrastructure",
        description="A fake provider for factory hardening tests.",
        docs_url="https://example.com/docs",
        icon="test",
        probe_url="https://api.example.com/probe",
        auth_header=lambda key: {"Authorization": f"Bearer {key}"},
        sync_url="https://api.example.com/sync",
    )
    defaults.update(overrides)
    return ProviderSpec(**defaults)


@pytest.mark.asyncio
@respx.mock
async def test_connect_wraps_bare_exception_from_parse_probe():
    def _boom(body):
        raise Exception("unexpected provider bug")

    respx.get("https://api.example.com/probe").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    provider = make_provider(_spec(parse_probe=_boom))()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=None, db=AsyncMock(), payload={"api_key": "k"})
    assert exc_info.value.code == "probe_failed"


@pytest.mark.asyncio
@respx.mock
async def test_connect_preserves_integration_error_code_from_parse_probe():
    """Ordering regression guard: an IntegrationError raised inside
    parse_probe must survive with its own code, not be rewritten to
    'probe_failed' by the new broad except Exception branch."""

    def _raise_custom(body):
        raise IntegrationError("custom_code", "custom failure")

    respx.get("https://api.example.com/probe").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    provider = make_provider(_spec(parse_probe=_raise_custom))()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=None, db=AsyncMock(), payload={"api_key": "k"})
    assert exc_info.value.code == "custom_code"


@pytest.mark.asyncio
@respx.mock
async def test_connect_wraps_json_decode_error():
    respx.get("https://api.example.com/probe").mock(
        return_value=httpx.Response(200, content=b"not json")
    )
    provider = make_provider(_spec())()

    with pytest.raises(IntegrationError) as exc_info:
        await provider.connect(user=None, db=AsyncMock(), payload={"api_key": "k"})
    assert exc_info.value.code == "probe_failed"


@pytest.mark.asyncio
@respx.mock
async def test_sync_wraps_bare_exception_from_parse_sync(monkeypatch):
    """The regression this feature closes: parse_sync used to run outside
    the try block, so this exception previously propagated unhandled."""

    def _boom(body):
        raise Exception("unexpected refresh bug")

    respx.get("https://api.example.com/sync").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    provider = make_provider(_spec(parse_sync=_boom))()

    integration = MagicMock()
    integration.id = "int-1"
    integration.config = {}
    db = AsyncMock()
    creds = MagicMock()
    creds.encrypted_key = b"irrelevant"
    db.scalar = AsyncMock(return_value=creds)

    import src.integrations.project._factory as factory_module

    monkeypatch.setattr(factory_module, "decrypt", lambda blob: "fake-api-key")

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=integration, db=db)
    assert exc_info.value.code == "sync_failed"


@pytest.mark.asyncio
@respx.mock
async def test_sync_error_message_never_contains_raw_exception_text(monkeypatch):
    """A 401 whose request URL carries a credential in the query string
    must not leak it into the raised IntegrationError.message."""
    respx.get("https://api.example.com/sync").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )
    provider = make_provider(_spec())()

    integration = MagicMock()
    integration.id = "int-1"
    integration.config = {}
    db = AsyncMock()
    creds = MagicMock()
    creds.encrypted_key = b"irrelevant"
    db.scalar = AsyncMock(return_value=creds)

    import src.integrations.project._factory as factory_module

    monkeypatch.setattr(factory_module, "decrypt", lambda blob: "SUPERSECRET")

    with pytest.raises(IntegrationError) as exc_info:
        await provider.sync(integration=integration, db=db)
    assert exc_info.value.code == "sync_failed"
    assert "SUPERSECRET" not in exc_info.value.message
