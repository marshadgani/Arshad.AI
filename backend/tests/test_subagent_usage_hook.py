"""Tests for the SubagentStop usage hook (.claude/hooks/subagent_usage_log.py).

Regression guard for the AI Ecosystem page showing zero usage: nothing ever
wrote to agent_usage_log, so every agent looked unused.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HOOK = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "subagent_usage_log.py"
)
_spec = importlib.util.spec_from_file_location("subagent_usage_log", _HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

SESSION = "5fbda8fb-626b-58c9-b80c-42eb22244577"


def _assistant(msg_id, ts, usage, model="claude-sonnet-5-5", stop="end_turn"):
    return {
        "type": "assistant",
        "timestamp": ts,
        "uuid": f"u-{msg_id}-{ts}",
        "message": {
            "id": msg_id,
            "model": model,
            "stop_reason": stop,
            "usage": usage,
        },
    }


def _write(tmp_path, entries):
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(path)


class TestSummariseTranscript:
    def test_sums_input_output_and_cache_creation_but_not_cache_reads(self, tmp_path):
        path = _write(
            tmp_path,
            [
                _assistant(
                    "m1",
                    "2026-10-16T10:00:00Z",
                    {
                        "input_tokens": 10,
                        "output_tokens": 20,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 9999,
                    },
                ),
                _assistant(
                    "m2",
                    "2026-10-16T10:00:05Z",
                    {"input_tokens": 1, "output_tokens": 2},
                ),
            ],
        )
        result = hook.summarise_transcript(path)
        assert result["tokens_used"] == 133

    def test_counts_a_response_split_over_several_lines_once(self, tmp_path):
        usage = {"input_tokens": 5, "output_tokens": 7}
        path = _write(
            tmp_path,
            [
                _assistant("m1", "2026-10-16T10:00:00Z", usage),
                _assistant("m1", "2026-10-16T10:00:01Z", usage),
            ],
        )
        assert hook.summarise_transcript(path)["tokens_used"] == 12

    def test_duration_and_model(self, tmp_path):
        path = _write(
            tmp_path,
            [
                _assistant(
                    "m1", "2026-10-16T10:00:00Z", {"output_tokens": 1}, model="a"
                ),
                _assistant(
                    "m2", "2026-10-16T10:00:02.500Z", {"output_tokens": 1}, model="b"
                ),
            ],
        )
        result = hook.summarise_transcript(path)
        assert result["duration_ms"] == 2500
        assert result["model"] == "b"

    @pytest.mark.parametrize(
        "stop,expected", [("end_turn", True), ("max_tokens", False), ("refusal", False)]
    )
    def test_success_reflects_final_stop_reason(self, tmp_path, stop, expected):
        path = _write(
            tmp_path,
            [_assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 1}, stop=stop)],
        )
        assert hook.summarise_transcript(path)["success"] is expected

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "agent.jsonl"
        good = json.dumps(
            _assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 4})
        )
        path.write_text("not json\n" + good + "\n")
        assert hook.summarise_transcript(str(path))["tokens_used"] == 4


class TestBuildPayload:
    def test_uses_agent_type_as_agent_name(self, tmp_path):
        path = _write(
            tmp_path, [_assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 3})]
        )
        body = hook.build_payload(
            {
                "agent_type": "ai-engineer",
                "agent_transcript_path": path,
                "session_id": SESSION,
            }
        )
        assert body["agent_name"] == "ai-engineer"
        assert body["tokens_used"] == 3
        assert body["session_id"] == SESSION

    @pytest.mark.parametrize("agent_type", ["", "   ", None])
    def test_skips_unnamed_internal_agents(self, agent_type):
        assert hook.build_payload({"agent_type": agent_type}) is None

    def test_drops_session_id_that_is_not_a_uuid(self):
        body = hook.build_payload({"agent_type": "Explore", "session_id": "not-a-uuid"})
        assert "session_id" not in body

    def test_missing_transcript_still_records_the_run(self):
        body = hook.build_payload(
            {
                "agent_type": "Explore",
                "agent_transcript_path": "/nonexistent/agent.jsonl",
            }
        )
        assert body == {"agent_name": "Explore"}


class TestMain:
    def test_does_nothing_without_a_key(self, monkeypatch, capsys):
        monkeypatch.delenv("ARSHAD_USAGE_KEY", raising=False)
        calls = []
        monkeypatch.setattr(hook, "post", lambda *a: calls.append(a) or True)
        assert hook.main() == 0
        assert calls == []

    def test_refuses_plain_http_to_a_remote_host(self, monkeypatch, capsys):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", "k" * 32)
        monkeypatch.setenv("ARSHAD_USAGE_URL", "http://example.com")
        calls = []
        monkeypatch.setattr(hook, "post", lambda *a: calls.append(a) or True)
        assert hook.main() == 0
        assert calls == []
        assert "https" in capsys.readouterr().err

    def test_exits_zero_even_when_the_post_fails(self, monkeypatch, io_stdin):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", "k" * 32)
        monkeypatch.setattr(hook, "post", lambda *a: False)
        io_stdin({"agent_type": "Explore"})
        assert hook.main() == 0

    def test_posts_the_built_body_with_the_key(self, monkeypatch, io_stdin):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", "k" * 32)
        monkeypatch.delenv("ARSHAD_USAGE_URL", raising=False)
        sent = []
        monkeypatch.setattr(
            hook, "post", lambda url, key, body: sent.append((url, key, body)) or True
        )
        io_stdin({"agent_type": "Explore"})
        hook.main()
        assert sent == [(hook.DEFAULT_URL, "k" * 32, {"agent_name": "Explore"})]


@pytest.fixture
def io_stdin(monkeypatch):
    import io
    import sys

    def _set(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    return _set
