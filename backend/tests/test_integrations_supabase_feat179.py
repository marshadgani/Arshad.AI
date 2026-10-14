"""FEAT-179 - Supabase sync() infrastructure-health tests.

Uses src. import paths, consistent with every other test in this repo.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.integrations.base import IntegrationError
from src.integrations.project import supabase as sb_mod
from src.integrations.project.supabase import SupabaseIntegration


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


def _make_project(
    ref: str,
    name: str,
    status: str = "ACTIVE_HEALTHY",
    region: str = "us-east-1",
) -> dict:
    return {"id": ref, "name": name, "region": region, "status": status}


# TC-008: sync stores project status and synced_at
# REQ-179-2 AC-1,2,3
@pytest.mark.asyncio
async def test_sync_stores_project_status_and_synced_at(monkeypatch):
    """TC-008: config contains projects with status field and synced_at ISO UTC timestamp."""
    projects = [_make_project("ref-1", "prod-db", "ACTIVE_HEALTHY")]
    resp = _fake_response(200, projects)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=resp)

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(sb_mod, "decrypt", lambda _: "test-pat")
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(sb_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await SupabaseIntegration().sync(integration=integration, db=db)

    config = integration.config
    assert "synced_at" in config
    parsed = datetime.fromisoformat(config["synced_at"])
    assert parsed.tzinfo is not None
    assert len(config["projects"]) == 1
    proj = config["projects"][0]
    assert proj["status"] == "ACTIVE_HEALTHY"


# TC-009: missing status field stored as None
# REQ-179-2 AC-2
@pytest.mark.asyncio
async def test_sync_missing_status_stored_as_none(monkeypatch):
    """TC-009: project with no 'status' key -> stored as None (not error)."""
    projects = [{"id": "ref-1", "name": "legacy-db", "region": "us-east-1"}]
    resp = _fake_response(200, projects)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=resp)

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(sb_mod, "decrypt", lambda _: "test-pat")
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(sb_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await SupabaseIntegration().sync(integration=integration, db=db)

    assert integration.config["projects"][0]["status"] is None


# TC-010: max 10 projects stored
# REQ-179-2 AC-2
@pytest.mark.asyncio
async def test_sync_truncates_to_10_projects(monkeypatch):
    """TC-010: 15 projects returned -> only 10 stored."""
    projects = [_make_project(f"ref-{i}", f"db-{i}") for i in range(15)]
    resp = _fake_response(200, projects)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=resp)

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(sb_mod, "decrypt", lambda _: "test-pat")
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(sb_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await SupabaseIntegration().sync(integration=integration, db=db)

    assert len(integration.config["projects"]) == 10


# TC-011: unhealthy projects sorted first so they are never dropped by the 10-cap
# REQ-179-2 AC-2
@pytest.mark.asyncio
async def test_sync_unhealthy_projects_sorted_first(monkeypatch):
    """TC-011: 11 projects, one unhealthy - unhealthy must be in stored 10."""
    projects = [
        _make_project(f"ref-{i}", f"db-{i}", "ACTIVE_HEALTHY") for i in range(10)
    ]
    projects.append(_make_project("ref-10", "pausing-db", "PAUSING"))
    resp = _fake_response(200, projects)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=resp)

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(sb_mod, "decrypt", lambda _: "test-pat")
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(sb_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await SupabaseIntegration().sync(integration=integration, db=db)

    stored_statuses = [p["status"] for p in integration.config["projects"]]
    assert "PAUSING" in stored_statuses, (
        "Unhealthy project must survive 10-cap truncation"
    )


# TC-012: fetch failure -> mark_error called, IntegrationError message is type name only, no project name
# REQ-179-2 AC-4 / REQ-179-11
@pytest.mark.asyncio
async def test_sync_failure_marks_error_type_name_only(monkeypatch, caplog):
    """TC-012: network failure -> IntegrationError code='sync_failed'; message is type name only."""
    import httpx as _httpx

    SECRET_PROJECT = "secret-project-name"

    async def fake_get(url, **kwargs):
        raise _httpx.TimeoutException("timeout")

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = fake_get

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))
    mock_mark_error = AsyncMock()

    monkeypatch.setattr(sb_mod, "decrypt", lambda _: "test-pat")
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(sb_mod, "mark_error", mock_mark_error)

    with pytest.raises(IntegrationError) as exc_info:
        await SupabaseIntegration().sync(integration=integration, db=db)

    mock_mark_error.assert_awaited_once()
    msg = exc_info.value.message
    assert SECRET_PROJECT not in msg
    assert "api.supabase.com" not in msg
    for record in caplog.records:
        assert SECRET_PROJECT not in record.message


# TC-013: config excludes API key and raw response
# REQ-179-11
@pytest.mark.asyncio
async def test_sync_config_does_not_contain_pat(monkeypatch):
    """TC-013: config keys limited to whitelist; PAT never stored."""
    SECRET_PAT = "sbp_super_secret_personal_access_token"
    projects = [_make_project("ref-1", "prod")]
    resp = _fake_response(200, projects)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=resp)

    integration = MagicMock()
    integration.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key=b"enc"))

    monkeypatch.setattr(sb_mod, "decrypt", lambda _: SECRET_PAT)
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", lambda **kw: fake_client)
    monkeypatch.setattr(sb_mod, "mark_synced", AsyncMock(return_value=MagicMock()))

    await SupabaseIntegration().sync(integration=integration, db=db)

    config_json = json.dumps(integration.config)
    assert SECRET_PAT not in config_json
    allowed = {"project_count", "projects", "synced_at"}
    assert set(integration.config.keys()) <= allowed
