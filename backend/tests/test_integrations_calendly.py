"""FEAT-180 — Calendly provider connect/sync."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal import calendly as mod
from src.integrations.registry import INTEGRATION_REGISTRY

INFO = {"user_uri": "https://api.calendly.com/users/U", "user_timezone": "Asia/Riyadh"}


def test_registered_as_personal_apikey():
    p = INTEGRATION_REGISTRY["calendly"]
    assert p.kind == "personal_apikey"


@pytest.mark.asyncio
async def test_connect_writes_user_uri_to_config_immediately(monkeypatch):
    monkeypatch.setattr(mod, "probe_user", AsyncMock(return_value=INFO))
    store = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(mod, "store_api_key", store)
    row = MagicMock(config={})
    db = MagicMock(scalar=AsyncMock(return_value=row), commit=AsyncMock())
    user = MagicMock(id=uuid.uuid4())
    await mod.CalendlyIntegration().connect(
        user=user, db=db, payload={"api_key": "tok"}
    )
    assert row.config == INFO
    assert store.await_args.kwargs["extra"] == INFO
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_connect_rejects_invalid_token_and_stores_nothing(monkeypatch):
    monkeypatch.setattr(
        mod, "probe_user", AsyncMock(side_effect=IntegrationError("invalid_key", "no"))
    )
    store = AsyncMock()
    monkeypatch.setattr(mod, "store_api_key", store)
    with pytest.raises(IntegrationError) as ei:
        await mod.CalendlyIntegration().connect(
            user=MagicMock(), db=MagicMock(), payload={"api_key": "bad"}
        )
    assert ei.value.code == "invalid_key"
    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_requires_user():
    with pytest.raises(IntegrationError):
        await mod.CalendlyIntegration().connect(user=None, db=MagicMock(), payload={})
