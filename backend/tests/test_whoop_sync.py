"""Tests for WhoopIntegration.sync() — the live NameError fix.

WhoopIntegration.sync() never persists biometric values (see the comment
in oauth_providers.py). rows_written must always be 0; len(records) would
be a monitoring lie about rows that were never written.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal.oauth_providers import WhoopIntegration


def _make_integration():
    integration = MagicMock()
    integration.status = "connected"
    integration.last_error = None
    return integration


def _make_db():
    db = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_sync_with_records_reports_zero_rows_written(monkeypatch):
    provider = WhoopIntegration()
    integration = _make_integration()
    db = _make_db()
    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"records": [{"id": 1}, {"id": 2}]})

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

    result = await provider.sync(integration=integration, db=db)

    assert result.rows_written == 0
    assert "2 recovery record" in result.summary
    assert integration.status == "connected"


@pytest.mark.asyncio
async def test_sync_with_empty_records_list_does_not_raise(monkeypatch):
    provider = WhoopIntegration()
    integration = _make_integration()
    db = _make_db()
    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"records": []})

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

    result = await provider.sync(integration=integration, db=db)
    assert result.rows_written == 0


@pytest.mark.asyncio
async def test_sync_body_missing_records_key_does_not_raise(monkeypatch):
    provider = WhoopIntegration()
    integration = _make_integration()
    db = _make_db()
    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={})

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

    result = await provider.sync(integration=integration, db=db)
    assert result.rows_written == 0


@pytest.mark.asyncio
async def test_sync_network_error_raises_integration_error_and_sets_status(monkeypatch):
    provider = WhoopIntegration()
    integration = _make_integration()
    db = _make_db()
    monkeypatch.setattr(provider, "get_access_token", AsyncMock(return_value="tok"))

    client = AsyncMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)

    with pytest.raises(IntegrationError):
        await provider.sync(integration=integration, db=db)

    assert integration.status == "error"
