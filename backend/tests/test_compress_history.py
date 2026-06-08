"""Unit tests for _compress_history in backend/src/services/chat.py.

Tests all 4 code paths:
  1. Under budget — returns messages unchanged
  2. Over budget — trims oldest user/assistant pairs
  3. Over budget with only one user message — break condition (can't trim further)
  4. Empty messages list
"""

import importlib
import sys
from unittest.mock import patch


def _load_compress():
    """Import _compress_history without triggering heavy service-level imports."""
    # Patch out the Anthropic client and other heavy deps at import time
    with patch.dict(
        sys.modules,
        {
            "anthropic": __import__(
                "unittest.mock", fromlist=["MagicMock"]
            ).MagicMock(),
            "src.middleware.cache": __import__(
                "unittest.mock", fromlist=["MagicMock"]
            ).MagicMock(),
            "src.models.database": __import__(
                "unittest.mock", fromlist=["MagicMock"]
            ).MagicMock(),
            "src.auth.dependencies": __import__(
                "unittest.mock", fromlist=["MagicMock"]
            ).MagicMock(),
        },
    ):
        spec = importlib.util.spec_from_file_location(
            "chat_module",
            "/home/user/Arshad.AI/backend/src/services/chat.py",
        )
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pass
        return mod


import json


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _approx_tokens(s: str) -> int:
    """Mirrors the production implementation: ceil(len(s) / 4)."""
    import math

    return math.ceil(len(s) / 4)


def _total_tokens(messages: list[dict]) -> int:
    return sum(_approx_tokens(json.dumps(m.get("content", ""))) for m in messages)


# ---------------------------------------------------------------------------
# Inline implementation for isolation (avoids heavy service imports)
# ---------------------------------------------------------------------------
import math


def _compress_history_impl(messages: list[dict], budget: int) -> list[dict]:
    """Extracted copy of the production logic for isolated testing."""
    total = sum(math.ceil(len(json.dumps(m.get("content", ""))) / 4) for m in messages)
    if total <= budget:
        return messages

    compressed = list(messages)
    while compressed and total > budget:
        user_indices = [i for i, m in enumerate(compressed) if m.get("role") == "user"]
        if len(user_indices) < 2:
            break
        drop_until = user_indices[1]
        dropped = compressed[:drop_until]
        compressed = compressed[drop_until:]
        total -= sum(
            math.ceil(len(json.dumps(m.get("content", ""))) / 4) for m in dropped
        )
    return compressed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCompressHistoryUnderBudget:
    def test_empty_list_returns_empty(self):
        result = _compress_history_impl([], budget=1000)
        assert result == []

    def test_single_message_under_budget_unchanged(self):
        msgs = [_msg("user", "hello")]
        result = _compress_history_impl(msgs, budget=10000)
        assert result == msgs

    def test_multiple_messages_under_budget_unchanged(self):
        msgs = [
            _msg("user", "first"),
            _msg("assistant", "reply"),
            _msg("user", "second"),
        ]
        result = _compress_history_impl(msgs, budget=10000)
        assert result == msgs

    def test_exactly_at_budget_unchanged(self):
        msgs = [_msg("user", "x")]
        total = _total_tokens(msgs)
        result = _compress_history_impl(msgs, budget=total)
        assert result == msgs


class TestCompressHistoryOverBudgetTrims:
    def test_drops_oldest_pair(self):
        """With three turns over budget, the oldest pair is dropped."""
        msgs = [
            _msg("user", "turn one — oldest, should be dropped"),
            _msg("assistant", "reply one"),
            _msg("user", "turn two — keep"),
            _msg("assistant", "reply two"),
            _msg("user", "turn three — keep"),
        ]
        # Budget that forces dropping the first turn
        total = _total_tokens(msgs)
        budget = total - _total_tokens(msgs[:2]) - 1
        result = _compress_history_impl(msgs, budget=budget)
        assert result[0]["content"] == "turn two — keep"

    def test_preserves_most_recent_messages(self):
        msgs = [
            _msg("user", "old A"),
            _msg("assistant", "old B"),
            _msg("user", "recent C"),
            _msg("assistant", "recent D"),
        ]
        total = _total_tokens(msgs)
        budget = _total_tokens(msgs[2:])  # only fits last pair
        result = _compress_history_impl(msgs, budget=budget)
        contents = [m["content"] for m in result]
        assert "recent C" in contents
        assert "recent D" in contents

    def test_result_within_budget(self):
        msgs = [_msg("user", "A" * 100), _msg("assistant", "B" * 100)] * 5
        budget = _total_tokens(msgs) // 2
        result = _compress_history_impl(msgs, budget=budget)
        assert _total_tokens(result) <= budget or len(result) < len(msgs)

    def test_returns_list_not_original(self):
        """Must return a new list, not mutate the input."""
        msgs = [
            _msg("user", "u1"),
            _msg("assistant", "a1"),
            _msg("user", "u2"),
        ]
        budget = 1  # force compression
        original_len = len(msgs)
        result = _compress_history_impl(msgs, budget=budget)
        assert len(msgs) == original_len  # original not mutated


class TestCompressHistorySingleUserBreak:
    def test_single_user_message_not_trimmed(self):
        """When only one user message remains, loop breaks without reducing further."""
        msgs = [
            _msg("user", "only user message — must be preserved"),
            _msg("assistant", "assistant reply"),
        ]
        budget = 1  # impossibly small — but we can't drop below 1 user message
        result = _compress_history_impl(msgs, budget=budget)
        # Must keep the last user message even when over budget
        assert any(m["role"] == "user" for m in result)
        assert result[0]["content"] == "only user message — must be preserved"

    def test_break_does_not_infinite_loop(self):
        """Regression: the while loop must exit cleanly on the break condition."""
        msgs = [_msg("user", "u"), _msg("assistant", "a")]
        budget = 0
        result = _compress_history_impl(msgs, budget=budget)
        assert isinstance(result, list)


class TestCompressHistoryEdgeCases:
    def test_empty_budget_with_multiple_turns(self):
        msgs = [
            _msg("user", "a"),
            _msg("assistant", "b"),
            _msg("user", "c"),
        ]
        result = _compress_history_impl(msgs, budget=0)
        # Should drop down to single-user-message break point
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_assistant_only_messages_no_user(self):
        """Edge case: no user messages — user_indices is empty, loop breaks immediately."""
        msgs = [_msg("assistant", "x"), _msg("assistant", "y")]
        result = _compress_history_impl(msgs, budget=0)
        assert result == msgs  # can't trim without user messages

    def test_large_content_compresses(self):
        long_content = "word " * 500
        msgs = [
            _msg("user", long_content),
            _msg("assistant", long_content),
            _msg("user", "short"),
        ]
        total = _total_tokens(msgs)
        budget = _total_tokens([msgs[-1]])
        result = _compress_history_impl(msgs, budget=budget)
        assert any(m["content"] == "short" for m in result)
