"""Unit tests for services/gateway.py — GatewayError, dispatch(), list_agents().

Tests all code paths:
  1. GatewayError — attributes, default status
  2. dispatch — unknown agent (404), invalid payload (400), success
  3. list_agents — empty registry, populated registry shape
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeInput(BaseModel):
    message: str


class _FakeOutput(BaseModel):
    reply: str


def _make_agent(run_result=None, run_exc=None):
    agent = MagicMock()
    agent.domain = "test"
    agent.name = "agent"
    agent.slug = "test_agent"
    agent.description = "A test agent"
    agent.input_schema = _FakeInput
    agent.output_schema = _FakeOutput
    agent.tool_dependencies = ["tool_a"]
    if run_exc is not None:
        agent.run = AsyncMock(side_effect=run_exc)
    else:
        agent.run = AsyncMock(return_value=run_result or _FakeOutput(reply="ok"))
    return agent


# ---------------------------------------------------------------------------
# GatewayError
# ---------------------------------------------------------------------------


class TestGatewayError:
    def test_attributes_stored(self):
        from src.services.gateway import GatewayError

        err = GatewayError("unknown_agent", "Not found", status=404)
        assert err.code == "unknown_agent"
        assert err.message == "Not found"
        assert err.status == 404

    def test_is_exception(self):
        from src.services.gateway import GatewayError

        assert issubclass(GatewayError, Exception)

    def test_str_is_message(self):
        from src.services.gateway import GatewayError

        err = GatewayError("code", "the message")
        assert str(err) == "the message"

    def test_default_status_is_400(self):
        from src.services.gateway import GatewayError

        err = GatewayError("invalid_input", "bad")
        assert err.status == 400


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDispatch:
    async def test_unknown_agent_raises_404(self):
        from src.services.gateway import GatewayError, dispatch

        with patch("src.services.gateway.get_agent", return_value=None):
            with pytest.raises(GatewayError) as exc_info:
                await dispatch(
                    "unknown", "agent", user=MagicMock(), db=AsyncMock(), payload={}
                )
        err = exc_info.value
        assert err.code == "unknown_agent"
        assert err.status == 404
        assert "unknown/agent" in err.message

    async def test_invalid_payload_raises_400(self):
        """Missing required field triggers Pydantic ValidationError → GatewayError(400)."""
        from src.services.gateway import GatewayError, dispatch

        agent = _make_agent()
        with patch("src.services.gateway.get_agent", return_value=agent):
            with pytest.raises(GatewayError) as exc_info:
                # {} is missing required field 'message'
                await dispatch(
                    "test", "agent", user=MagicMock(), db=AsyncMock(), payload={}
                )
        err = exc_info.value
        assert err.code == "invalid_input"
        assert err.status == 400

    async def test_success_returns_agent_output(self):
        expected = _FakeOutput(reply="hello from agent")
        agent = _make_agent(run_result=expected)
        user = MagicMock()
        db = AsyncMock()

        from src.services.gateway import dispatch

        with patch("src.services.gateway.get_agent", return_value=agent):
            result = await dispatch(
                "test", "agent", user=user, db=db, payload={"message": "hi"}
            )

        assert result is expected
        agent.run.assert_awaited_once()
        call_kwargs = agent.run.call_args.kwargs
        assert call_kwargs["user"] is user
        assert call_kwargs["db"] is db
        assert isinstance(call_kwargs["payload"], _FakeInput)
        assert call_kwargs["payload"].message == "hi"

    async def test_agent_error_propagates(self):
        """AgentError from run() bubbles out of dispatch unchanged."""
        from src.agents.base import AgentError
        from src.services.gateway import dispatch

        exc = AgentError("not_yet_implemented", "stub")
        agent = _make_agent(run_exc=exc)

        with patch("src.services.gateway.get_agent", return_value=agent):
            with pytest.raises(AgentError):
                await dispatch(
                    "test",
                    "agent",
                    user=MagicMock(),
                    db=AsyncMock(),
                    payload={"message": "x"},
                )


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    def test_empty_registry_returns_empty_list(self):
        from src.services.gateway import list_agents

        with patch("src.services.gateway.AGENT_REGISTRY", {}):
            result = list_agents()
        assert result == []

    def test_populated_registry_shape(self):
        """Each entry has the expected keys."""
        from src.services.gateway import list_agents

        agent = _make_agent()
        with patch("src.services.gateway.AGENT_REGISTRY", {"test_agent": agent}):
            result = list_agents()

        assert len(result) == 1
        item = result[0]
        assert item["domain"] == "test"
        assert item["name"] == "agent"
        assert item["slug"] == "test_agent"
        assert item["description"] == "A test agent"
        assert "input_schema" in item
        assert item["tool_dependencies"] == ["tool_a"]

    def test_multiple_agents_all_listed(self):
        from src.services.gateway import list_agents

        agents = {f"domain_{i}": _make_agent() for i in range(5)}
        with patch("src.services.gateway.AGENT_REGISTRY", agents):
            result = list_agents()
        assert len(result) == 5
