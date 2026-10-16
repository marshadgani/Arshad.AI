"""Tests for the dedicated ingest key on POST /api/v1/ai-ecosystem/log."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from src.auth import usage_ingest
from src.auth.usage_ingest import require_usage_writer
from src.schemas.ai_ecosystem import LogRequest

KEY = "k" * 40


def _code(exc: HTTPException) -> str:
    return exc.detail["error"]["code"]


@pytest.mark.asyncio
async def test_valid_key_is_accepted_without_a_user(monkeypatch):
    monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
    assert (
        await require_usage_writer(x_usage_key=KEY, authorization=None, db=AsyncMock())
        is None
    )


@pytest.mark.asyncio
async def test_wrong_key_is_401(monkeypatch):
    monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
    with pytest.raises(HTTPException) as exc:
        await require_usage_writer(
            x_usage_key="x" * 40, authorization=None, db=AsyncMock()
        )
    assert exc.value.status_code == 401
    assert _code(exc.value) == "invalid_usage_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", ["", "short"])
async def test_unconfigured_or_weak_server_key_is_503_never_accepted(
    monkeypatch, configured
):
    monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", configured)
    with pytest.raises(HTTPException) as exc:
        await require_usage_writer(
            x_usage_key=configured or "anything", authorization=None, db=AsyncMock()
        )
    assert exc.value.status_code == 503
    assert _code(exc.value) == "usage_ingest_not_configured"


@pytest.mark.asyncio
async def test_without_key_header_falls_back_to_the_bearer_check(monkeypatch):
    monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
    with patch.object(
        usage_ingest, "get_current_user", AsyncMock(return_value="user")
    ) as gcu:
        result = await require_usage_writer(
            x_usage_key=None, authorization="Bearer t", db="db"
        )
    assert result == "user"
    gcu.assert_awaited_once_with(authorization="Bearer t", db="db")


@pytest.mark.asyncio
async def test_without_key_or_bearer_is_401(monkeypatch):
    monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
    with pytest.raises(HTTPException) as exc:
        await require_usage_writer(x_usage_key=None, authorization=None, db=AsyncMock())
    assert exc.value.status_code == 401


class TestLogRequestBounds:
    def test_accepts_builtin_and_pipeline_agent_names(self):
        for name in ("ai-engineer", "general-purpose", "Explore", "plugin:reviewer"):
            LogRequest(agent_name=name)

    @pytest.mark.parametrize("name", ["", "a b", "x" * 101, "bad/name", "drop;table"])
    def test_rejects_bad_agent_names(self, name):
        with pytest.raises(ValueError):
            LogRequest(agent_name=name)

    def test_rejects_negative_or_overflowing_numbers(self):
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", tokens_used=-1)
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", tokens_used=2_000_000_001)
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", duration_ms=-5)


class TestLogRoute:
    """The real route over HTTP, with the database session faked."""

    @pytest.fixture
    def client(self, monkeypatch):
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api.v1.ai_ecosystem_ingest import router
        from src.models.database import get_db

        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        self.db = AsyncMock()
        self.db.add = MagicMock()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        return TestClient(app)

    def test_valid_key_records_the_run_and_registers_a_new_agent(self, client):
        resp = client.post(
            "/api/v1/ai-ecosystem/log",
            json={
                "agent_name": "Explore",
                "tokens_used": 42,
                "model": "claude-haiku-5-5",
            },
            headers={"X-Usage-Key": KEY},
        )
        assert resp.status_code == 201
        logged = self.db.add.call_args.args[0]
        assert (logged.agent_name, logged.tokens_used) == ("Explore", 42)
        self.db.execute.assert_awaited_once()
        self.db.commit.assert_awaited_once()

    def test_wrong_key_writes_nothing(self, client):
        resp = client.post(
            "/api/v1/ai-ecosystem/log",
            json={"agent_name": "Explore"},
            headers={"X-Usage-Key": "x" * 40},
        )
        assert resp.status_code == 401
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()

    def test_no_credentials_writes_nothing(self, client):
        resp = client.post("/api/v1/ai-ecosystem/log", json={"agent_name": "Explore"})
        assert resp.status_code == 401
        self.db.add.assert_not_called()

    def test_invalid_body_is_422(self, client):
        resp = client.post(
            "/api/v1/ai-ecosystem/log",
            json={"agent_name": "bad name"},
            headers={"X-Usage-Key": KEY},
        )
        assert resp.status_code == 422
