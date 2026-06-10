"""Unit tests for intent_classifier._fast_path and .classify.

Tests all code paths:
  1. _fast_path — calendar, email, github, no-match, case-insensitivity, ' agenda' spacing
  2. classify — fast-path short-circuit (no LLM), LLM valid intent, LLM unknown → general,
                LLM empty → general, history trimmed to last 4 messages
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# _fast_path
# ---------------------------------------------------------------------------


class TestFastPath:
    def test_calendar_keywords(self):
        from src.services.intent_classifier import _fast_path

        assert _fast_path("What's on my calendar today?") == "calendar"
        assert _fast_path("Schedule a meeting with Alice") == "calendar"
        assert _fast_path("Do I have any free slots this week?") == "calendar"
        assert _fast_path("Book an appointment") == "calendar"
        assert _fast_path("Check my availability") == "calendar"

    def test_email_keywords(self):
        from src.services.intent_classifier import _fast_path

        assert _fast_path("Check my email") == "email"
        assert _fast_path("Search my inbox for the invoice") == "email"
        assert _fast_path("Any unread messages?") == "email"
        assert _fast_path("Draft a reply to Alice") == "email"

    def test_github_keywords(self):
        from src.services.intent_classifier import _fast_path

        assert _fast_path("Open a GitHub issue") == "github"
        assert _fast_path("Review this pull request") == "github"
        assert _fast_path("Show me the latest commit") == "github"
        assert _fast_path("What's in the diff?") == "github"
        assert _fast_path("What issues are open?") == "github"

    def test_no_match_returns_none(self):
        from src.services.intent_classifier import _fast_path

        assert _fast_path("Hello, how are you?") is None
        assert _fast_path("What's 2 + 2?") is None
        assert _fast_path("") is None
        assert _fast_path("Tell me a joke") is None

    def test_case_insensitive(self):
        from src.services.intent_classifier import _fast_path

        assert _fast_path("CALENDAR event") == "calendar"
        assert _fast_path("EMAIL me something") == "email"
        assert _fast_path("GITHUB repo") == "github"

    def test_agenda_leading_space_matches(self):
        """' agenda' has a leading space — _fast_path pads the text with spaces."""
        from src.services.intent_classifier import _fast_path

        # ' agenda' keyword should match when 'agenda' is a standalone word
        assert _fast_path("Show me my agenda for tomorrow") == "calendar"
        # Works even when 'agenda' is the whole input (padded by _fast_path)
        assert _fast_path("agenda") == "calendar"

    def test_pr_keyword_has_spaces(self):
        """' pr ' keyword requires spaces — 'apr' should not match."""
        from src.services.intent_classifier import _fast_path

        # ' pr ' has surrounding spaces
        assert _fast_path("review my pr please") == "github"
        # 'apr' should NOT match (no surrounding spaces)
        assert _fast_path("april fools") is None


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestClassify:
    async def test_fast_path_skips_llm_call(self):
        """classify() returns immediately when keyword matches — ai.call never invoked."""
        from src.services.intent_classifier import classify

        with patch("src.services.intent_classifier.ai") as mock_ai:
            result = await classify("schedule a meeting")
        mock_ai.call.assert_not_called()
        assert result == "calendar"

    async def test_llm_path_valid_calendar(self):
        """Falls back to LLM for ambiguous input; valid LLM response used directly."""
        from src.services.intent_classifier import classify

        mock_response = {"content": [{"type": "text", "text": "calendar"}]}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await classify("What should I do next?")
        assert result == "calendar"

    async def test_llm_path_valid_general(self):
        from src.services.intent_classifier import classify

        mock_response = {"content": [{"type": "text", "text": "general"}]}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await classify("Tell me about the weather")
        assert result == "general"

    async def test_llm_path_unknown_intent_falls_back(self):
        """LLM returns an unrecognised word → 'general'."""
        from src.services.intent_classifier import classify

        mock_response = {"content": [{"type": "text", "text": "sports"}]}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await classify("Something completely random")
        assert result == "general"

    async def test_llm_path_empty_content_falls_back(self):
        """LLM returns empty content list → 'general'."""
        from src.services.intent_classifier import classify

        mock_response = {"content": []}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await classify("hmm")
        assert result == "general"

    async def test_llm_path_whitespace_only_falls_back(self):
        """LLM returns whitespace text → 'general'."""
        from src.services.intent_classifier import classify

        mock_response = {"content": [{"type": "text", "text": "   "}]}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await classify("??")
        assert result == "general"

    async def test_llm_receives_last_4_history_items(self):
        """Only the last 4 history messages are sent to the LLM."""
        from src.services.intent_classifier import classify

        history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        mock_response = {"content": [{"type": "text", "text": "github"}]}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ) as mock_call:
            # Use a message that has no fast-path keyword
            await classify("what do you think?", history=history)

        # The call should have received a messages list of length 5
        # (4 history items + the current user message)
        call_args = mock_call.call_args
        messages_sent = call_args.kwargs["messages"]
        assert len(messages_sent) == 5  # last 4 + current message

    async def test_none_history_treated_as_empty(self):
        """classify() with history=None doesn't crash."""
        from src.services.intent_classifier import classify

        mock_response = {"content": [{"type": "text", "text": "email"}]}
        with patch(
            "src.services.intent_classifier.ai.call",
            new=AsyncMock(return_value=mock_response),
        ):
            result = await classify("talk to me", history=None)
        assert result == "email"
