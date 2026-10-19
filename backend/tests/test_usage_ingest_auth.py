"""Tests for the dedicated ingest key and route on POST /api/v1/ai-ecosystem/log."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from src.auth import usage_ingest
from src.auth.usage_ingest import require_usage_writer
from src.middleware.rate_limit import RateLimitExceeded
from src.schemas.ai_ecosystem import LogRequest

KEY = "k" * 40
NEXT_KEY = "n" * 40


@pytest.fixture(autouse=True)
def _clean_key_env(monkeypatch):
    monkeypatch.delenv("AGENT_USAGE_INGEST_KEY", raising=False)
    monkeypatch.delenv("AGENT_USAGE_INGEST_KEY_NEXT", raising=False)


def _code(exc: HTTPException) -> str:
    return exc.detail["error"]["code"]


async def _call(key: str | None, authorization: str | None = None):
    return await require_usage_writer(
        x_usage_key=key, authorization=authorization, db=AsyncMock()
    )


class TestKeyCheck:
    @pytest.mark.asyncio
    async def test_valid_key_is_accepted_without_a_user(self, monkeypatch):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        assert await _call(KEY) is None

    @pytest.mark.asyncio
    async def test_both_keys_are_accepted_while_rotating(self, monkeypatch):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY_NEXT", NEXT_KEY)
        assert await _call(KEY) is None
        assert await _call(NEXT_KEY) is None

    @pytest.mark.asyncio
    async def test_wrong_key_is_401_with_www_authenticate(self, monkeypatch):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        with pytest.raises(HTTPException) as exc:
            await _call("x" * 40)
        assert exc.value.status_code == 401
        assert _code(exc.value) == "invalid_usage_key"
        assert exc.value.headers["WWW-Authenticate"] == "Bearer"

    @pytest.mark.asyncio
    async def test_empty_key_header_is_rejected_not_sent_to_the_jwt_path(
        self, monkeypatch
    ):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        with pytest.raises(HTTPException) as exc:
            await _call("")
        assert _code(exc.value) == "invalid_usage_key"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("configured", ["", "short"])
    async def test_unconfigured_server_answers_the_same_401_as_a_wrong_key(
        self, monkeypatch, caplog, configured
    ):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", configured)
        with caplog.at_level(logging.WARNING, logger=usage_ingest.__name__):
            with pytest.raises(HTTPException) as exc:
                await _call(configured or "anything")
        assert exc.value.status_code == 401
        assert _code(exc.value) == "invalid_usage_key"
        assert "no AGENT_USAGE_INGEST_KEY" in caplog.text

    @pytest.mark.asyncio
    async def test_key_length_boundary_is_32(self, monkeypatch):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", "a" * 31)
        with pytest.raises(HTTPException):
            await _call("a" * 31)
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", "a" * 32)
        assert await _call("a" * 32) is None

    @pytest.mark.asyncio
    async def test_a_rejected_key_is_never_written_to_the_log(
        self, monkeypatch, caplog
    ):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        presented = "secret-attempt-" + "z" * 30
        with caplog.at_level(logging.WARNING, logger=usage_ingest.__name__):
            with pytest.raises(HTTPException):
                await _call(presented)
        assert "does not match" in caplog.text
        assert presented not in caplog.text
        assert KEY not in caplog.text

    @pytest.mark.asyncio
    async def test_non_ascii_key_header_does_not_crash(self, monkeypatch):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        with pytest.raises(HTTPException) as exc:
            await _call("é" * 40)
        assert exc.value.status_code == 401


class TestBearerFallback:
    @pytest.mark.asyncio
    async def test_without_key_header_uses_the_bearer_check(self, monkeypatch):
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
    async def test_without_key_or_bearer_is_401(self, monkeypatch):
        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        with pytest.raises(HTTPException) as exc:
            await _call(None)
        assert exc.value.status_code == 401


class TestLogRequestBounds:
    def test_accepts_builtin_and_pipeline_agent_names(self):
        for name in ("ai-engineer", "general-purpose", "Explore", "plugin:reviewer"):
            LogRequest(agent_name=name)

    @pytest.mark.parametrize("name", ["", "a b", "x" * 101, "bad/name", "drop;table"])
    def test_rejects_bad_agent_names(self, name):
        with pytest.raises(ValueError):
            LogRequest(agent_name=name)

    @pytest.mark.parametrize("model", ["bad model!", "x" * 101, "a;b", "<script>"])
    def test_rejects_bad_model_strings(self, model):
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", model=model)

    def test_accepts_real_model_ids(self):
        for model in (
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-haiku-5-5",
        ):
            LogRequest(agent_name="a", model=model)

    def test_rejects_negative_or_overflowing_numbers(self):
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", tokens_used=-1)
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", tokens_used=10_000_001)
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", duration_ms=-5)
        with pytest.raises(ValueError):
            LogRequest(agent_name="a", duration_ms=604_800_001)

    def test_boundaries_and_defaults(self):
        body = LogRequest(agent_name="a")
        assert (body.tokens_used, body.success, body.model, body.session_id) == (
            0,
            True,
            None,
            None,
        )
        LogRequest(agent_name="a", tokens_used=10_000_000, duration_ms=604_800_000)
        LogRequest(agent_name="a", tokens_used=0, duration_ms=0)


class TestLogRoute:
    """The real route over HTTP, with the database session and Redis faked."""

    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.api.v1 import ai_ecosystem_ingest
        from src.models.database import get_db

        monkeypatch.setenv("AGENT_USAGE_INGEST_KEY", KEY)
        self.rate_limit = AsyncMock()
        monkeypatch.setattr(ai_ecosystem_ingest, "enforce_rate_limit", self.rate_limit)
        self.db = AsyncMock()
        self.db.add = MagicMock()
        self.db.scalar = AsyncMock(return_value=0)
        app = FastAPI()
        app.include_router(ai_ecosystem_ingest.router)
        app.dependency_overrides[get_db] = lambda: self.db
        return TestClient(app)

    def _post(self, client, body, key=KEY):
        headers = {"X-Usage-Key": key} if key else {}
        return client.post("/api/v1/ai-ecosystem/log", json=body, headers=headers)

    def test_valid_key_records_the_run(self, client):
        resp = self._post(
            client,
            {"agent_name": "Explore", "tokens_used": 42, "model": "claude-haiku-5-5"},
        )
        assert resp.status_code == 201
        logged = self.db.add.call_args.args[0]
        assert (logged.agent_name, logged.tokens_used) == ("Explore", 42)
        self.db.commit.assert_awaited_once()

    def test_new_agent_is_registered_with_on_conflict_do_nothing(self, client):
        self._post(client, {"agent_name": "ai-engineer"})
        statement = self.db.execute.call_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        assert "ON CONFLICT (agent_name) DO NOTHING" in str(compiled)
        assert compiled.params["agent_name"] == "ai-engineer"
        assert compiled.params["display_name"] == "Ai Engineer"
        assert compiled.params["model"] == "claude-sonnet-4-6"
        assert compiled.params["category"] == "other"

    def test_registered_model_follows_the_request_when_given(self, client):
        self._post(client, {"agent_name": "Explore", "model": "claude-haiku-5-5"})
        statement = self.db.execute.call_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        assert compiled.params["model"] == "claude-haiku-5-5"

    def test_registration_stops_at_the_cap_but_the_run_is_still_logged(self, client):
        from src.api.v1.ai_ecosystem_ingest import MAX_AUTO_REGISTERED_AGENTS

        self.db.scalar.return_value = MAX_AUTO_REGISTERED_AGENTS
        resp = self._post(client, {"agent_name": "invented-name"})
        assert resp.status_code == 201
        self.db.execute.assert_not_awaited()
        self.db.add.assert_called_once()
        self.db.commit.assert_awaited_once()

    def test_registration_still_runs_just_under_the_cap(self, client):
        from src.api.v1.ai_ecosystem_ingest import MAX_AUTO_REGISTERED_AGENTS

        self.db.scalar.return_value = MAX_AUTO_REGISTERED_AGENTS - 1
        self._post(client, {"agent_name": "one-more"})
        self.db.execute.assert_awaited_once()

    def test_rate_limit_is_enforced_before_anything_is_written(self, client):
        self.rate_limit.side_effect = RateLimitExceeded("usage_ingest", 300, 60)
        resp = self._post(client, {"agent_name": "Explore"})
        assert resp.status_code == 429
        self.db.add.assert_not_called()
        self.db.execute.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    def test_wrong_key_writes_nothing(self, client):
        resp = self._post(client, {"agent_name": "Explore"}, key="x" * 40)
        assert resp.status_code == 401
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()
        self.rate_limit.assert_not_awaited()

    def test_no_credentials_writes_nothing(self, client):
        resp = self._post(client, {"agent_name": "Explore"}, key=None)
        assert resp.status_code == 401
        self.db.add.assert_not_called()

    def test_unconfigured_server_key_is_rejected_the_same_way(
        self, client, monkeypatch
    ):
        monkeypatch.delenv("AGENT_USAGE_INGEST_KEY")
        resp = self._post(client, {"agent_name": "Explore"})
        assert resp.status_code == 401
        # A bare test app has no main.py handler, so the envelope stays under "detail".
        assert resp.json()["detail"]["error"]["code"] == "invalid_usage_key"
        self.db.add.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [
            {"agent_name": "bad name"},
            {"agent_name": "a", "model": "bad model!"},
            {"agent_name": "a", "tokens_used": 10_000_001},
            {"agent_name": "a", "duration_ms": -1},
        ],
    )
    def test_invalid_body_is_422_and_writes_nothing(self, client, body):
        resp = self._post(client, body)
        assert resp.status_code == 422
        self.db.add.assert_not_called()
