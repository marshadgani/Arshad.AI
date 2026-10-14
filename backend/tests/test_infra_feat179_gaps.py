"""FEAT-179 gap coverage: deploy fan-out cap, id-less/odd payloads, and
row selection in _find_infra_integrations."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.api.v1 import trip_feasibility as route
from src.integrations.project import render as render_mod
from src.integrations.project.render import RenderIntegration


def _svc(i):
    return {
        "service": {
            "id": f"srv-{i}",
            "name": f"n{i}",
            "type": "web_service",
            "suspended": "not_suspended",
        }
    }


def _setup(monkeypatch, client_cls):
    monkeypatch.setattr(render_mod, "decrypt", lambda _: "rnd_key")
    monkeypatch.setattr(render_mod, "mark_error", AsyncMock())
    monkeypatch.setattr(render_mod, "mark_synced", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(render_mod.httpx, "AsyncClient", client_cls)
    row = MagicMock()
    row.id = uuid.uuid4()
    row.config = {}
    db = MagicMock()
    db.scalar = AsyncMock(return_value=MagicMock(encrypted_key="enc"))
    return row, db


class _Resp:
    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b

    def raise_for_status(self):
        pass


def test_deploy_fetches_never_exceed_three_in_flight_and_only_ten_are_fetched(
    monkeypatch,
):
    state = {"now": 0, "peak": 0, "deploy_calls": 0}

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            if url.endswith("/services?limit=20"):
                return _Resp([_svc(i) for i in range(12)])
            state["deploy_calls"] += 1
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return _Resp([{"deploy": {"status": "live"}}])

    row, db = _setup(monkeypatch, _C)
    asyncio.run(RenderIntegration().sync(integration=row, db=db))
    assert state["peak"] <= 3
    assert state["deploy_calls"] == 10


def test_service_without_id_and_non_string_status_store_none_not_a_guess(monkeypatch):
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            if url.endswith("/services?limit=20"):
                return _Resp(
                    [
                        {"service": {"name": "no-id", "suspended": "not_suspended"}},
                        _svc(2),
                    ]
                )
            return _Resp([{"deploy": {"status": 5}}])

    row, db = _setup(monkeypatch, _C)
    asyncio.run(RenderIntegration().sync(integration=row, db=db))
    assert [s["latest_deploy_status"] for s in row.config["services"]] == [None, None]


def _row(slug, user_id):
    return SimpleNamespace(slug=slug, user_id=user_id)


def _db_returning(rows):
    class _Rows:
        def all(self):
            return rows

    class _Db:
        async def scalars(self, stmt):
            return _Rows()

    return _Db()


def test_find_infra_prefers_callers_row_over_shared_row_per_slug():
    own_r, shared_r, shared_s = (
        _row("render", "u1"),
        _row("render", None),
        _row("supabase", None),
    )
    render, supabase = asyncio.run(
        route._find_infra_integrations("u1", _db_returning([own_r, shared_r, shared_s]))
    )
    assert render is own_r
    assert supabase is shared_s


def test_find_infra_with_only_one_provider_leaves_other_none():
    only = _row("supabase", "u1")
    render, supabase = asyncio.run(
        route._find_infra_integrations("u1", _db_returning([only]))
    )
    assert render is None
    assert supabase is only
