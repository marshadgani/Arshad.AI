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


# ── probe_user ────────────────────────────────────────────────────────────


def _http(monkeypatch, *, status=200, body=None, exc=None):
    import httpx

    seen = {}

    class _Client:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen["url"], seen["headers"] = url, headers
            if exc:
                raise exc
            return httpx.Response(
                status, json=body, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    return seen


@pytest.mark.asyncio
async def test_probe_returns_uri_and_timezone_and_sends_bearer(monkeypatch):
    seen = _http(monkeypatch, body={"resource": {"uri": "u", "timezone": "Asia/Riyadh"}})
    assert await mod.probe_user("tok") == {"user_uri": "u", "user_timezone": "Asia/Riyadh"}
    assert seen["url"].endswith("/users/me")
    assert seen["headers"] == {"Authorization": "Bearer tok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_probe_maps_401_403_to_invalid_key(monkeypatch, status):
    _http(monkeypatch, status=status, body={})
    with pytest.raises(IntegrationError) as ei:
        await mod.probe_user("tok")
    assert ei.value.code == "invalid_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"resource": {}}, {"resource": "x"}, []])
async def test_probe_without_user_uri_fails(monkeypatch, body):
    _http(monkeypatch, body=body)
    with pytest.raises(IntegrationError) as ei:
        await mod.probe_user("tok")
    assert ei.value.code == "probe_failed"


@pytest.mark.asyncio
async def test_probe_missing_timezone_defaults_to_empty(monkeypatch):
    _http(monkeypatch, body={"resource": {"uri": "u"}})
    assert (await mod.probe_user("tok"))["user_timezone"] == ""


@pytest.mark.asyncio
async def test_probe_5xx_propagates_http_error(monkeypatch):
    import httpx

    _http(monkeypatch, status=503, body={})
    with pytest.raises(httpx.HTTPStatusError):
        await mod.probe_user("tok")


# ── connect failure paths ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_network_error_is_probe_failed_without_token(monkeypatch):
    import httpx

    monkeypatch.setattr(
        mod, "probe_user", AsyncMock(side_effect=httpx.ConnectError("tok-secret"))
    )
    store = AsyncMock()
    monkeypatch.setattr(mod, "store_api_key", store)
    with pytest.raises(IntegrationError) as ei:
        await mod.CalendlyIntegration().connect(
            user=MagicMock(), db=MagicMock(), payload={"api_key": "tok-secret"}
        )
    assert ei.value.code == "probe_failed"
    assert "tok-secret" not in ei.value.message
    store.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"api_key": ""}, {"api_key": "   "}])
async def test_connect_rejects_missing_key_before_any_http(monkeypatch, payload):
    probe = AsyncMock()
    monkeypatch.setattr(mod, "probe_user", probe)
    with pytest.raises(IntegrationError) as ei:
        await mod.CalendlyIntegration().connect(
            user=MagicMock(), db=MagicMock(), payload=payload
        )
    assert ei.value.code == "missing_api_key"
    probe.assert_not_awaited()


# ── sync ──────────────────────────────────────────────────────────────────


def _sync_db(creds):
    return MagicMock(scalar=AsyncMock(return_value=creds), commit=AsyncMock())


@pytest.mark.asyncio
async def test_sync_refreshes_config_and_marks_connected(monkeypatch):
    monkeypatch.setattr(mod, "decrypt", lambda _: "tok")
    monkeypatch.setattr(mod, "probe_user", AsyncMock(return_value=INFO))
    integ = MagicMock(config={"keep": 1}, status="error", last_error="x")
    res = await mod.CalendlyIntegration().sync(
        integration=integ, db=_sync_db(MagicMock(encrypted_key="b"))
    )
    assert integ.config == {"keep": 1, **INFO}
    assert integ.status == "connected" and integ.last_error is None
    assert res.rows_written == 0


@pytest.mark.asyncio
async def test_sync_without_stored_token_raises_not_connected():
    with pytest.raises(IntegrationError) as ei:
        await mod.CalendlyIntegration().sync(
            integration=MagicMock(), db=_sync_db(None)
        )
    assert ei.value.code == "not_connected"


@pytest.mark.asyncio
async def test_sync_rejected_token_marks_error_and_reraises(monkeypatch):
    monkeypatch.setattr(mod, "decrypt", lambda _: "tok")
    monkeypatch.setattr(
        mod, "probe_user", AsyncMock(side_effect=IntegrationError("invalid_key", "no"))
    )
    integ = MagicMock(config={})
    with pytest.raises(IntegrationError) as ei:
        await mod.CalendlyIntegration().sync(
            integration=integ, db=_sync_db(MagicMock(encrypted_key="b"))
        )
    assert ei.value.code == "invalid_key"
    assert integ.status == "error"


@pytest.mark.asyncio
async def test_sync_network_failure_stores_type_only(monkeypatch):
    import httpx

    monkeypatch.setattr(mod, "decrypt", lambda _: "tok")
    monkeypatch.setattr(
        mod,
        "probe_user",
        AsyncMock(side_effect=httpx.ConnectError("https://api.calendly.com tok")),
    )
    integ = MagicMock(config={})
    with pytest.raises(IntegrationError) as ei:
        await mod.CalendlyIntegration().sync(
            integration=integ, db=_sync_db(MagicMock(encrypted_key="b"))
        )
    assert ei.value.code == "sync_failed"
    assert integ.last_error == "ConnectError"
