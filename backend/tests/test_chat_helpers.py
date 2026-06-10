"""Unit tests for pure helpers in services/chat.py.

Tests:
  _sse              — string and dict payloads
  _approx_tokens    — length-based estimation
  _history_token_budget — env var reading + defaults + floor
  _tool_subset      — tool/agent selection per intent
  _build_tool_schemas — registry look-up and schema assembly
  _dispatch_tool    — tool/agent dispatch, unknown names, exceptions
  _load_session_history — DB history reconstruction from message rows
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# _sse
# ---------------------------------------------------------------------------


class TestSse:
    def test_string_payload_wrapped(self):
        from src.services.chat import _sse

        result = _sse("[DONE]")
        assert result == "data: [DONE]\n\n"

    def test_dict_payload_json_encoded(self):
        from src.services.chat import _sse

        result = _sse({"delta": "hello"})
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        body = result[len("data: ") : -2]
        assert json.loads(body) == {"delta": "hello"}

    def test_nested_dict_round_trips(self):
        from src.services.chat import _sse

        payload = {"tool_use": {"id": "tu_1", "name": "foo", "input": {}}}
        result = _sse(payload)
        body = result[len("data: ") : -2]
        assert json.loads(body) == payload


# ---------------------------------------------------------------------------
# _approx_tokens
# ---------------------------------------------------------------------------


class TestApproxTokens:
    def test_empty_string_returns_one(self):
        from src.services.chat import _approx_tokens

        assert _approx_tokens("") == 1  # max(1, 0 // 4)

    def test_four_chars_is_one_token(self):
        from src.services.chat import _approx_tokens

        assert _approx_tokens("abcd") == 1

    def test_eight_chars_is_two_tokens(self):
        from src.services.chat import _approx_tokens

        assert _approx_tokens("abcdefgh") == 2

    def test_four_hundred_chars(self):
        from src.services.chat import _approx_tokens

        assert _approx_tokens("a" * 400) == 100


# ---------------------------------------------------------------------------
# _history_token_budget
# ---------------------------------------------------------------------------


class TestHistoryTokenBudget:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("CHAT_HISTORY_TOKEN_BUDGET", raising=False)
        from src.services import chat as chat_mod

        assert chat_mod._history_token_budget() == 8000

    def test_env_var_respected(self, monkeypatch):
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "4000")
        from src.services import chat as chat_mod

        assert chat_mod._history_token_budget() == 4000

    def test_value_below_floor_clamped(self, monkeypatch):
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "100")
        from src.services import chat as chat_mod

        assert chat_mod._history_token_budget() == 500  # floor is 500

    def test_invalid_env_var_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "not-a-number")
        from src.services import chat as chat_mod

        assert chat_mod._history_token_budget() == 8000


# ---------------------------------------------------------------------------
# _tool_subset
# ---------------------------------------------------------------------------


class TestToolSubset:
    def test_calendar_intent(self):
        from src.services.chat import _tool_subset

        tools, agents = _tool_subset("calendar")
        assert "calendar_list_events" in tools
        assert "calendar_create_event" in tools
        assert "calendar_update_event" in tools
        assert "calendar_find_free_slots" in tools
        assert "calendar_meeting_suggester" in agents
        assert "calendar_schedule_analyzer" in agents

    def test_email_intent(self):
        from src.services.chat import _tool_subset

        tools, agents = _tool_subset("email")
        assert "gmail_search_threads" in tools
        assert "gmail_get_thread" in tools
        assert "gmail_create_draft" in tools
        assert "gmail_apply_label" in tools
        assert "email_email_summarizer" in agents

    def test_github_intent_core_tools(self):
        from src.services.chat import _tool_subset

        tools, agents = _tool_subset("github")
        assert "github_list_issues" in tools
        assert "github_create_issue" in tools
        assert "github_update_issue" in tools
        assert "github_list_prs" in tools
        assert "github_pr_reviewer" in agents
        assert "github_code_summarizer" in agents
        assert "github_repo_monitor" in agents

    def test_general_intent_returns_council_agent(self):
        from src.services.chat import _tool_subset

        tools, agents = _tool_subset("general")
        assert tools == []
        assert agents == ["ai_core_council_chairman"]

    def test_unknown_intent_falls_through_to_general(self):
        from src.services.chat import _tool_subset

        tools, agents = _tool_subset("totally_unknown")
        assert tools == []
        assert agents == ["ai_core_council_chairman"]

    def test_github_optional_tools_added_when_registered(self):
        """github_get_pr / github_get_commit are included when present in TOOL_REGISTRY."""
        from src.services.chat import _tool_subset

        with patch(
            "src.services.chat.TOOL_REGISTRY",
            {"github_get_pr": MagicMock(), "github_get_commit": MagicMock()},
        ):
            tools, _ = _tool_subset("github")
        assert "github_get_pr" in tools
        assert "github_get_commit" in tools


# ---------------------------------------------------------------------------
# _build_tool_schemas
# ---------------------------------------------------------------------------


class _ToolInput(BaseModel):
    query: str


class _AgentInput(BaseModel):
    question: str


class TestBuildToolSchemas:
    def test_unknown_tool_skipped(self):
        from src.services.chat import _build_tool_schemas

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            result = _build_tool_schemas(["nonexistent"], [])
        assert result == []

    def test_unknown_agent_skipped(self):
        from src.services.chat import _build_tool_schemas

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            result = _build_tool_schemas([], ["nonexistent"])
        assert result == []

    def test_known_tool_included(self):
        from src.services.chat import _build_tool_schemas

        mock_tool = MagicMock()
        mock_tool.description = "Searches something"
        mock_tool.input_schema = _ToolInput

        with (
            patch("src.services.chat.TOOL_REGISTRY", {"my_tool": mock_tool}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            result = _build_tool_schemas(["my_tool"], [])

        assert len(result) == 1
        schema = result[0]
        assert schema["name"] == "my_tool"
        assert schema["description"] == "Searches something"
        assert "input_schema" in schema

    def test_known_agent_prefixed_with_agent_(self):
        from src.services.chat import _build_tool_schemas

        mock_agent = MagicMock()
        mock_agent.description = "Runs an analysis"
        mock_agent.input_schema = _AgentInput

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {"my_agent": mock_agent}),
        ):
            result = _build_tool_schemas([], ["my_agent"])

        assert len(result) == 1
        assert result[0]["name"] == "agent_my_agent"
        assert result[0]["description"] == "Runs an analysis"

    def test_mix_of_tools_and_agents(self):
        from src.services.chat import _build_tool_schemas

        mock_tool = MagicMock()
        mock_tool.description = "tool"
        mock_tool.input_schema = _ToolInput

        mock_agent = MagicMock()
        mock_agent.description = "agent"
        mock_agent.input_schema = _AgentInput

        with (
            patch("src.services.chat.TOOL_REGISTRY", {"t": mock_tool}),
            patch("src.services.chat.AGENT_REGISTRY", {"a": mock_agent}),
        ):
            result = _build_tool_schemas(["t"], ["a"])

        assert len(result) == 2
        names = {s["name"] for s in result}
        assert names == {"t", "agent_a"}


# ---------------------------------------------------------------------------
# _dispatch_tool
# ---------------------------------------------------------------------------


class _DispInput(BaseModel):
    q: str


class _DispOutput(BaseModel):
    answer: str


@pytest.mark.asyncio
class TestDispatchTool:
    async def test_unknown_tool_is_error(self):
        from src.services.chat import _dispatch_tool

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            output, is_error = await _dispatch_tool(
                "nonexistent", {}, user=MagicMock(), db=AsyncMock()
            )
        assert is_error is True
        assert output["error"] == "unknown_tool"
        assert output["name"] == "nonexistent"

    async def test_unknown_agent_is_error(self):
        from src.services.chat import _dispatch_tool

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            output, is_error = await _dispatch_tool(
                "agent_nonexistent", {}, user=MagicMock(), db=AsyncMock()
            )
        assert is_error is True
        assert output["error"] == "unknown_agent"
        assert output["name"] == "nonexistent"

    async def test_tool_success(self):
        from src.services.chat import _dispatch_tool

        mock_tool = AsyncMock(return_value=_DispOutput(answer="42"))
        mock_tool.input_schema = _DispInput

        with (
            patch("src.services.chat.TOOL_REGISTRY", {"my_tool": mock_tool}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            output, is_error = await _dispatch_tool(
                "my_tool", {"q": "hello"}, user=MagicMock(), db=AsyncMock()
            )
        assert is_error is False
        assert output == {"answer": "42"}

    async def test_tool_exception_returns_error_envelope(self):
        from src.services.chat import _dispatch_tool

        mock_tool = AsyncMock(side_effect=RuntimeError("boom"))
        mock_tool.input_schema = _DispInput

        with (
            patch("src.services.chat.TOOL_REGISTRY", {"my_tool": mock_tool}),
            patch("src.services.chat.AGENT_REGISTRY", {}),
        ):
            output, is_error = await _dispatch_tool(
                "my_tool", {"q": "x"}, user=MagicMock(), db=AsyncMock()
            )
        assert is_error is True
        assert output["error"] == "RuntimeError"
        assert output["message"] == "boom"

    async def test_agent_success(self):
        from src.services.chat import _dispatch_tool

        mock_agent = MagicMock()
        mock_agent.input_schema = _DispInput
        mock_agent.run = AsyncMock(return_value=_DispOutput(answer="agent_reply"))

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {"my_agent": mock_agent}),
        ):
            output, is_error = await _dispatch_tool(
                "agent_my_agent", {"q": "what"}, user=MagicMock(), db=AsyncMock()
            )
        assert is_error is False
        assert output == {"answer": "agent_reply"}

    async def test_agent_exception_returns_error_envelope(self):
        from src.services.chat import _dispatch_tool

        mock_agent = MagicMock()
        mock_agent.input_schema = _DispInput
        mock_agent.run = AsyncMock(side_effect=ValueError("agent failed"))

        with (
            patch("src.services.chat.TOOL_REGISTRY", {}),
            patch("src.services.chat.AGENT_REGISTRY", {"my_agent": mock_agent}),
        ):
            output, is_error = await _dispatch_tool(
                "agent_my_agent", {"q": "x"}, user=MagicMock(), db=AsyncMock()
            )
        assert is_error is True
        assert output["error"] == "ValueError"
        assert output["message"] == "agent failed"


# ---------------------------------------------------------------------------
# _load_session_history
# ---------------------------------------------------------------------------


def _make_row(role: str, content: dict):
    row = MagicMock()
    row.role = role
    row.content = content
    return row


def _make_db(rows):
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=rows)
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=mock_result)
    return db


@pytest.mark.asyncio
class TestLoadSessionHistory:
    async def test_empty_rows_returns_empty(self):
        from src.services.chat import _load_session_history

        result = await _load_session_history(_make_db([]), uuid.uuid4())
        assert result == []

    async def test_user_message(self):
        from src.services.chat import _load_session_history

        rows = [_make_row("user", {"text": "Hello"})]
        result = await _load_session_history(_make_db(rows), uuid.uuid4())
        assert result == [{"role": "user", "content": "Hello"}]

    async def test_assistant_message(self):
        from src.services.chat import _load_session_history

        rows = [
            _make_row("user", {"text": "hi"}),
            _make_row("assistant", {"text": "hello back"}),
        ]
        result = await _load_session_history(_make_db(rows), uuid.uuid4())
        assert result[0] == {"role": "user", "content": "hi"}
        assert result[1] == {"role": "assistant", "content": "hello back"}

    async def test_tool_use_flushed_as_assistant_block(self):
        from src.services.chat import _load_session_history

        rows = [
            _make_row("user", {"text": "use tool"}),
            _make_row(
                "tool_use",
                {"tool_use_id": "tid_1", "tool": "my_tool", "input": {"q": "x"}},
            ),
        ]
        result = await _load_session_history(_make_db(rows), uuid.uuid4())
        # tool_use accumulates in pending blocks and is flushed at end
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        blocks = assistant_msgs[0]["content"]
        assert blocks[0]["type"] == "tool_use"
        assert blocks[0]["id"] == "tid_1"
        assert blocks[0]["name"] == "my_tool"

    async def test_tool_result_becomes_user_message(self):
        from src.services.chat import _load_session_history

        rows = [
            _make_row("user", {"text": "use tool"}),
            _make_row(
                "tool_result",
                {"tool_use_id": "tid_1", "output": {"data": 42}, "is_error": False},
            ),
        ]
        result = await _load_session_history(_make_db(rows), uuid.uuid4())
        tool_result_msgs = [
            m
            for m in result
            if m["role"] == "user" and isinstance(m.get("content"), list)
        ]
        assert len(tool_result_msgs) == 1
        block = tool_result_msgs[0]["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tid_1"
        assert block["is_error"] is False

    async def test_mixed_conversation(self):
        """Full multi-turn conversation rebuilds correct history structure."""
        from src.services.chat import _load_session_history

        rows = [
            _make_row("user", {"text": "turn 1"}),
            _make_row("assistant", {"text": "reply 1"}),
            _make_row("user", {"text": "turn 2"}),
            _make_row(
                "tool_use",
                {"tool_use_id": "t1", "tool": "search", "input": {}},
            ),
            _make_row(
                "tool_result",
                {"tool_use_id": "t1", "output": {"r": 1}, "is_error": False},
            ),
            _make_row("assistant", {"text": "final reply"}),
        ]
        result = await _load_session_history(_make_db(rows), uuid.uuid4())

        roles = [m["role"] for m in result]
        # user, assistant, user, assistant(tool_use), user(tool_result), assistant
        assert roles.count("user") >= 2
        assert roles.count("assistant") >= 2
