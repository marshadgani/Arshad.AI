"""FEAT-179 - Render sync() infrastructure-health tests.

All cases use a fake httpx route table; no real Render API calls.
Uses src. import paths, consistent with every other test in this repo.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.integrations.project import render as render_mod
from src.integrations.project.render import RenderIntegration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(status: int, body: Any) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=body)

    def _raise():
        if status >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"HTTP {status}",
                request=MagicMock(),
                response=resp,
            )

    resp.raise_for_status = MagicMock(side_effect=_raise)
    return resp


def _make_service(
    sid: str, name: str = "svc", suspended: str = "not_suspended"
) -> dict:
    return {
        "service": {
            "id": sid,
            "name": name,
            "type": "web_service",
            "suspended": suspended,
        }
    }


def _make_deploy(status: str) -> list:
    return [{"deploy": {"status": status}}]


# TC-001: sync stores suspended + latest_deploy_status + synced_at
# REQ-179-1 AC-1,2,3
@pytest.mark.asyncio
async def test_sync_stores_health_fields_and_synced_at(monkeypatch):
    """TC-001: config holds per-service state and an ISO synced_at."""
    services_payload = [_make_service("srv-1", "api")]
    deploy_payload = _make_deploy("live")

    async def fake_get(url, **kwargs):
        if "/services?" in url:
            return _fake_response(200, services_payload)
        return _fake_response(200, deploy_payload)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(render_mod, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await RenderIntegration().sync(integration=integration, db=db)

    config = integration.config
    assert "synced_at" in config
    parsed = datetime.fromisoformat(config["synced_at"])
    assert parsed.tzinfo is not None
    assert len(config["services"]) == 1
    svc = config["services"][0]
    assert svc["suspended"] == "not_suspended"
    assert svc["latest_deploy_status"] == "live"


# TC-002: at most 10 services stored; services_truncated flag correct
# REQ-179-1 AC-2
@pytest.mark.asyncio
async def test_sync_truncates_to_10_services_sets_flag(monkeypatch):
    """TC-002: with 12 services returned, only 10 stored and services_truncated=True."""
    services_payload = [_make_service(f"srv-{i}", f"srv-{i}") for i in range(12)]
    deploy_payload = _make_deploy("live")

    async def fake_get(url, **kwargs):
        if "/services?" in url:
            return _fake_response(200, services_payload)
        return _fake_response(200, deploy_payload)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(render_mod, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await RenderIntegration().sync(integration=integration, db=db)

    assert len(integration.config["services"]) == 10
    assert integration.config["services_truncated"] is True
    assert integration.config["service_count"] == 12


# TC-003: service with no deploys stores latest_deploy_status=None
# REQ-179-1 AC-2 (null is not a conflict)
@pytest.mark.asyncio
async def test_sync_no_deploys_stores_none(monkeypatch):
    """TC-003: empty deploy list -> latest_deploy_status is None, not a failure."""
    services_payload = [_make_service("srv-1", "fresh")]

    async def fake_get(url, **kwargs):
        if "/services?" in url:
            return _fake_response(200, services_payload)
        return _fake_response(200, [])  # empty deploys

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(render_mod, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await RenderIntegration().sync(integration=integration, db=db)

    assert integration.config["services"][0]["latest_deploy_status"] is None


# TC-004: one failed per-service deploy lookup does not discard the snapshot
@pytest.mark.asyncio
async def test_sync_deploy_fetch_failure_is_unchecked_and_leaks_nothing(
    monkeypatch, caplog
):
    services_payload = [_make_service("srv-1", "SECRET-SERVICE-NAME")]

    async def fake_get(url, **kwargs):
        if "/services?" in url:
            return _fake_response(200, services_payload)
        raise httpx.ConnectError("boom SECRET-SERVICE-NAME https://api.render.com/x")

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))
    mock_mark_error = AsyncMock()
    mock_mark_synced = AsyncMock()

    monkeypatch.setattr(render_mod, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_error", mock_mark_error)
    monkeypatch.setattr(render_mod, "mark_synced", mock_mark_synced)
    caplog.set_level("DEBUG")

    await RenderIntegration().sync(integration=integration, db=db)

    mock_mark_error.assert_not_awaited()
    assert integration.config["services"][0]["latest_deploy_status"] == "unchecked"
    assert "SECRET-SERVICE-NAME" not in caplog.text


# TC-005: services-list fetch failure -> mark_error called, IntegrationError raised
# REQ-179-1 AC-4,5
@pytest.mark.asyncio
async def test_sync_services_list_failure_marks_error(monkeypatch):
    """TC-005: HTTP error -> mark_error, IntegrationError with type name only."""
    import httpx as _httpx

    async def fake_get(url, **kwargs):
        raise _httpx.ConnectError("refused")

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))
    mock_mark_error = AsyncMock()

    monkeypatch.setattr(render_mod, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_error", mock_mark_error)

    with pytest.raises(IntegrationError) as exc_info:
        await RenderIntegration().sync(integration=integration, db=db)

    mock_mark_error.assert_awaited_once()
    assert exc_info.value.code == "sync_failed"
    assert "ConnectError" in exc_info.value.message


# TC-006: concurrency cap - at most 3 concurrent deploy requests
# REQ-179-1 AC-1 (Semaphore(3))
@pytest.mark.asyncio
async def test_sync_deploy_concurrency_capped_at_3(monkeypatch):
    """TC-006: simultaneous in-flight deploy fetches must not exceed 3."""
    services_payload = [_make_service(f"srv-{i}", f"s{i}") for i in range(5)]
    max_inflight = 0
    current_inflight = 0

    async def fake_get(url, **kwargs):
        nonlocal max_inflight, current_inflight
        if "/services?" in url:
            return _fake_response(200, services_payload)
        current_inflight += 1
        max_inflight = max(max_inflight, current_inflight)
        await asyncio.sleep(0.01)
        current_inflight -= 1
        return _fake_response(200, _make_deploy("live"))

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(render_mod, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await RenderIntegration().sync(integration=integration, db=db)

    assert max_inflight <= 3, f"Expected <=3 concurrent fetches, got {max_inflight}"


# TC-007: config never contains API key or raw response bodies
# REQ-179-11
@pytest.mark.asyncio
async def test_sync_config_does_not_contain_api_key(monkeypatch):
    """TC-007: stored config keys are limited to whitelist; no API key stored."""
    SECRET_KEY = "rnd_super_secret_key_12345"
    services_payload = [_make_service("srv-1", "svc")]

    async def fake_get(url, **kwargs):
        if "/services?" in url:
            return _fake_response(200, services_payload)
        return _fake_response(200, _make_deploy("live"))

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(render_mod, "decrypt", lambda _: SECRET_KEY)
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await RenderIntegration().sync(integration=integration, db=db)

    config_json = json.dumps(integration.config)
    assert SECRET_KEY not in config_json
    allowed_keys = {"service_count", "services_truncated", "services", "synced_at"}
    assert set(integration.config.keys()) <= allowed_keys


def test_deploy_value_reraises_cancellation():
    with pytest.raises(asyncio.CancelledError):
        render_mod._deploy_value(asyncio.CancelledError())


def test_deploy_value_maps_failure_to_unchecked():
    assert render_mod._deploy_value(RuntimeError("x")) == render_mod.DEPLOY_UNCHECKED
    assert render_mod._deploy_value("live") == "live"


@pytest.mark.asyncio
async def test_mark_error_records_type_and_http_status_only():
    from src.integrations.project._shared import mark_error

    class _Err(Exception):
        response = MagicMock(status_code=503)

    integ = MagicMock()
    db = MagicMock()
    db.commit = AsyncMock()
    await mark_error(integration=integ, db=db, err=_Err("secret srv-abc"))
    assert integ.last_error == "_Err (HTTP 503)"
    assert integ.status == "error"
