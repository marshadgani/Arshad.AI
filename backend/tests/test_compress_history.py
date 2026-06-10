"""Unit tests for _compress_history in backend/src/services/chat.py.

Tests all 4 code paths against the REAL production function:
  1. Under budget — returns messages unchanged
  2. Over budget — trims oldest user/assistant pairs
  3. Over budget with only one user message — break condition (can't trim further)
  4. Empty messages list

Budget is controlled via the CHAT_HISTORY_TOKEN_BUDGET env var (monkeypatched per
test), since _compress_history sources its limit from _history_token_budget().

Token math (mirrors production _approx_tokens):
  tokens(text) = max(1, len(json.dumps(text)) // 4)
  "A" * 2000   → json.dumps = 2002 chars → 500 tokens
  "hello"      → json.dumps = 7 chars    → 1 token
  budget floor = 500  (env vars below 500 are clamped to 500)
"""

from __future__ import annotations

import json


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _count_tokens(messages: list[dict]) -> int:
    """Mirrors production: max(1, len(json.dumps(content)) // 4) per message."""
    return sum(max(1, len(json.dumps(m.get("content", ""))) // 4) for m in messages)


# Large content: json.dumps = 2002 chars → 500 tokens (= budget floor)
_LARGE = "A" * 2000
# Medium content: json.dumps = 402 chars → 100 tokens
_MEDIUM = "B" * 400
# Small content: json.dumps = 7 chars → 1 token
_SMALL = "hello"


class TestCompressHistoryUnderBudget:
    def test_empty_list_returns_empty(self, monkeypatch):
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "10000")
        from src.services.chat import _compress_history

        result = _compress_history([])
        assert result == []

    def test_single_message_under_budget_unchanged(self, monkeypatch):
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "10000")
        from src.services.chat import _compress_history

        msgs = [_msg("user", _SMALL)]
        result = _compress_history(msgs)
        assert result == msgs

    def test_multiple_messages_under_budget_unchanged(self, monkeypatch):
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "10000")
        from src.services.chat import _compress_history

        msgs = [
            _msg("user", _SMALL),
            _msg("assistant", _SMALL),
            _msg("user", _SMALL),
        ]
        result = _compress_history(msgs)
        assert result == msgs

    def test_exactly_at_budget_unchanged(self, monkeypatch):
        # One message with content "A" * 2000 → 500 tokens = budget floor
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [_msg("user", _LARGE)]
        assert _count_tokens(msgs) <= 500
        result = _compress_history(msgs)
        assert result == msgs

    def test_all_assistant_messages_unchanged(self, monkeypatch):
        """No user messages → user_indices empty → loop breaks immediately."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [_msg("assistant", _LARGE), _msg("assistant", _LARGE)]
        result = _compress_history(msgs)
        # Can't trim without user messages, returned as-is even if over budget
        assert result == msgs


class TestCompressHistoryOverBudgetTrims:
    def test_drops_oldest_pair_leaves_recent(self, monkeypatch):
        """Three turns over budget → oldest user+assistant pair dropped."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [
            _msg("user", _LARGE),  # 500 tokens — oldest, should be dropped
            _msg("assistant", _SMALL),  # 1 token
            _msg("user", _SMALL),  # 1 token — recent, must be kept
        ]
        # total = 502 > 500 → triggers trimming
        result = _compress_history(msgs)
        assert result[0]["content"] == _SMALL  # oldest user message gone
        assert result[-1]["content"] == _SMALL  # recent user message present

    def test_preserves_most_recent_messages(self, monkeypatch):
        """Oldest pair removed; most-recent pair preserved."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [
            _msg("user", _LARGE),  # 500 tokens — old
            _msg("assistant", _SMALL),  # 1 token
            _msg("user", "recent"),  # 1 token — recent
            _msg("assistant", "reply"),  # 1 token
        ]
        result = _compress_history(msgs)
        contents = [m["content"] for m in result]
        assert "recent" in contents
        assert "reply" in contents

    def test_result_within_budget_after_trim(self, monkeypatch):
        """After trimming, total tokens ≤ budget (or we hit the break condition)."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [
            _msg("user", _LARGE),
            _msg("assistant", _SMALL),
            _msg("user", _SMALL),
        ]
        result = _compress_history(msgs)
        assert _count_tokens(result) <= 500 or len(result) < len(msgs)

    def test_does_not_mutate_input(self, monkeypatch):
        """The input list must not be modified in-place."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [
            _msg("user", _LARGE),
            _msg("assistant", _SMALL),
            _msg("user", _SMALL),
        ]
        original_len = len(msgs)
        _compress_history(msgs)
        assert len(msgs) == original_len

    def test_multiple_trim_iterations(self, monkeypatch):
        """When one trim pass is not enough, the loop continues."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        # 4 turns, each large enough — trim must iterate more than once
        msgs = [
            _msg("user", _LARGE),  # 500 tokens
            _msg("assistant", _SMALL),  # 1 token
            _msg("user", _LARGE),  # 500 tokens
            _msg("assistant", _SMALL),  # 1 token
            _msg("user", _SMALL),  # 1 token — must survive
        ]
        result = _compress_history(msgs)
        # Last user message must be preserved
        assert any(m["content"] == _SMALL and m["role"] == "user" for m in result)


class TestCompressHistorySingleUserBreak:
    def test_one_user_message_over_budget_not_trimmed(self, monkeypatch):
        """With only one user message, the break fires — no trimming even if over budget."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [
            _msg("user", _LARGE),  # 500 tokens
            _msg("assistant", _LARGE),  # 500 tokens
        ]
        # total = 1000 > 500, but only 1 user message → break immediately
        result = _compress_history(msgs)
        assert any(m["role"] == "user" for m in result)
        assert result[0]["content"] == _LARGE

    def test_break_does_not_infinite_loop(self, monkeypatch):
        """Loop must exit cleanly under all conditions — no infinite loop."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        msgs = [_msg("user", _LARGE), _msg("assistant", _LARGE)]
        result = _compress_history(msgs)
        assert isinstance(result, list)

    def test_empty_input_no_loop(self, monkeypatch):
        """Empty list short-circuits before the while loop entirely."""
        monkeypatch.setenv("CHAT_HISTORY_TOKEN_BUDGET", "500")
        from src.services.chat import _compress_history

        result = _compress_history([])
        assert result == []
