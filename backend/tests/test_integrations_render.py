"""FEAT-179: Render sync stores deploy health and never leaks names or keys."""

import asyncio
import functools
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.integrations.base import IntegrationError
from src.integrations.project import render as render_mod
from src.integrations.project.render import RenderIntegration


def _service(i, suspended="not_suspended"):
    return {
        "service": {
            "id": f"srv-{i}",
            "name": f"secret-name-{i}",
            "type": "web_service",
            "suspended": suspended,
        }
    }


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
                "https://api.render.com/v1/secret", request=MagicMock(), response=self
            )


def _client(routes):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return routes(url)

    return _C


@pytest.fixture
def integration(monkeypatch):
    monkeypatch.setattr(render_mod, "decrypt", lambda _: "rnd_key")
    monkeypatch.setattr(render_mod, "mark_error", AsyncMock(side_effect=_mark_error))
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))
    row = MagicMock()
    row.id = uuid.uuid4()
    row.config = {}
    return row


async def _mark_error(*, integration, db, err):
    integration.status = "error"


@pytest.fixture
def db():
    d = MagicMock()
    d.scalar = AsyncMock(return_value=MagicMock(encrypted_key="enc"))
    return d


@_sync
async def test_sync_stores_suspended_and_latest_deploy(monkeypatch, integration, db):
    def routes(url):
        if url.endswith("/services?limit=20"):
            return _Resp([_service(1), _service(2, "suspended")])
        sid = url.split("/services/")[1].split("/")[0]
        status = "build_failed" if sid == "srv-2" else "live"
        return _Resp([{"deploy": {"status": status}}])

    monkeypatch.setattr(render_mod.httpx, "AsyncClient", _client(routes))
    await RenderIntegration().sync(integration=integration, db=db)
    cfg = integration.config
    assert cfg["services_truncated"] is False
    assert [(s["suspended"], s["latest_deploy_status"]) for s in cfg["services"]] == [
        ("not_suspended", "live"),
        ("suspended", "build_failed"),
    ]
    assert cfg["synced_at"]
    assert "rnd_key" not in str(cfg)


@_sync
async def test_sync_flags_truncation_and_caps_at_ten(monkeypatch, integration, db):
    def routes(url):
        if url.endswith("/services?limit=20"):
            return _Resp([_service(i) for i in range(12)])
        return _Resp([])

    monkeypatch.setattr(render_mod.httpx, "AsyncClient", _client(routes))
    await RenderIntegration().sync(integration=integration, db=db)
    assert integration.config["service_count"] == 12
    assert integration.config["services_truncated"] is True
    assert len(integration.config["services"]) == 10
    services = integration.config["services"]
    assert all(s["latest_deploy_status"] is None for s in services)


@_sync
async def test_deploy_failure_fails_sync_without_leaking_names(
    monkeypatch, integration, db
):
    def routes(url):
        if url.endswith("/services?limit=20"):
            return _Resp([_service(1), _service(2)])
        if "srv-1" in url:
            raise httpx.ConnectError("boom secret-name-1")
        return _Resp([{"deploy": {"status": "live"}}])

    monkeypatch.setattr(render_mod.httpx, "AsyncClient", _client(routes))
    with pytest.raises(IntegrationError) as exc:
        await RenderIntegration().sync(integration=integration, db=db)
    assert "secret-name" not in str(exc.value)
    assert "ConnectError" in str(exc.value)
    render_mod.mark_error.assert_awaited_once()
    assert integration.config == {}


@_sync
async def test_deploy_timeout_fails_sync(monkeypatch, integration, db):
    def routes(url):
        if url.endswith("/services?limit=20"):
            return _Resp([_service(1)])
        raise TimeoutError()

    monkeypatch.setattr(render_mod.httpx, "AsyncClient", _client(routes))
    with pytest.raises(IntegrationError) as exc:
        await RenderIntegration().sync(integration=integration, db=db)
    assert "TimeoutError" in str(exc.value)
    render_mod.mark_error.assert_awaited_once()
    assert integration.config == {}


@_sync
async def test_service_list_failure_marks_error_with_type_only(
    monkeypatch, integration, db
):
    monkeypatch.setattr(
        render_mod.httpx, "AsyncClient", _client(lambda url: _Resp([], 500))
    )
    with pytest.raises(IntegrationError) as exc:
        await RenderIntegration().sync(integration=integration, db=db)
    assert "secret" not in str(exc.value)
    assert "HTTPStatusError" in str(exc.value)
    render_mod.mark_error.assert_awaited_once()
    assert integration.config == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["../../users", "srv-x#frag", "srv x", "", "x" * 10])
async def test_odd_service_id_never_reaches_the_url(bad_id):
    from unittest.mock import MagicMock

    from src.integrations.project import render

    client = MagicMock()
    client.get = AsyncMock(side_effect=AssertionError("must not be called"))

    status = await render._latest_deploy_status(
        client, asyncio.Semaphore(1), "key", bad_id
    )

    assert status is None
