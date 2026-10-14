"""FEAT-179: Supabase sync stores project status and never leaks details."""

import asyncio
import functools
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.integrations.project import supabase as sb_mod
from src.integrations.project.supabase import SupabaseIntegration


def _sync(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))

    return wrapper


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "https://api.supabase.com/secret", request=MagicMock(), response=self
            )


def _client(resp):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return resp

    return _C


@pytest.fixture
def integration(monkeypatch):
    monkeypatch.setattr(sb_mod, "decrypt", lambda _: "pat")
    monkeypatch.setattr(sb_mod, "mark_synced", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(sb_mod, "mark_error", AsyncMock())
    row = MagicMock()
    row.id = uuid.uuid4()
    row.config = {}
    return row


@pytest.fixture
def db():
    d = MagicMock()
    d.scalar = AsyncMock(return_value=MagicMock(encrypted_key="enc"))
    return d


@_sync
async def test_sync_stores_status_and_synced_at(monkeypatch, integration, db):
    body = [
        {"id": "a", "name": "p1", "region": "eu", "status": "ACTIVE_HEALTHY"},
        {"id": "b", "name": "p2", "region": "eu", "status": "INACTIVE", "secret": "x"},
    ]
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", _client(_Resp(body)))
    await SupabaseIntegration().sync(integration=integration, db=db)
    cfg = integration.config
    assert [p["status"] for p in cfg["projects"]] == ["INACTIVE", "ACTIVE_HEALTHY"]
    assert cfg["synced_at"]
    assert "secret" not in str(cfg) and "pat" not in str(cfg.get("projects"))


@_sync
async def test_sync_missing_status_is_none(monkeypatch, integration, db):
    monkeypatch.setattr(
        sb_mod.httpx, "AsyncClient", _client(_Resp([{"id": "a", "name": "p"}]))
    )
    await SupabaseIntegration().sync(integration=integration, db=db)
    assert integration.config["projects"][0]["status"] is None


@_sync
async def test_sync_failure_marks_error_with_type_only(monkeypatch, integration, db):
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", _client(_Resp([], 500)))
    with pytest.raises(IntegrationError) as exc:
        await SupabaseIntegration().sync(integration=integration, db=db)
    assert "secret" not in str(exc.value)
    sb_mod.mark_error.assert_awaited_once()


@_sync
async def test_sync_cap_never_drops_unhealthy_project(monkeypatch, integration, db):
    body = [
        {"id": str(i), "name": f"p{i}", "status": "ACTIVE_HEALTHY"} for i in range(12)
    ] + [{"id": "down", "name": "down", "status": "INACTIVE"}]
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", _client(_Resp(body)))
    await SupabaseIntegration().sync(integration=integration, db=db)
    projects = integration.config["projects"]
    assert len(projects) == 10
    assert projects[0]["ref"] == "down"


@pytest.mark.parametrize("body", [{"projects": []}, ["junk", None]])
@_sync
async def test_sync_malformed_payload_marks_error_not_500(
    monkeypatch, integration, db, body
):
    monkeypatch.setattr(sb_mod.httpx, "AsyncClient", _client(_Resp(body)))
    with pytest.raises(IntegrationError) as exc:
        await SupabaseIntegration().sync(integration=integration, db=db)
    assert exc.value.code == "sync_failed"
    sb_mod.mark_error.assert_awaited_once()


@pytest.mark.parametrize("length", [513, 5000])
def test_api_key_over_the_length_cap_is_refused(length):
    from src.integrations.base import IntegrationError
    from src.integrations.project._shared import require_api_key

    with pytest.raises(IntegrationError) as exc:
        require_api_key({"api_key": "k" * length})

    assert exc.value.code == "api_key_too_long"


def test_api_key_at_the_length_cap_is_accepted():
    from src.integrations.project._shared import MAX_API_KEY_LENGTH, require_api_key

    assert (
        len(require_api_key({"api_key": "k" * MAX_API_KEY_LENGTH}))
        == MAX_API_KEY_LENGTH
    )
