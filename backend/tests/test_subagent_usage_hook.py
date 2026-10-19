"""Tests for the SubagentStop usage hook (.claude/hooks/subagent_usage_log.py).

Regression guard for the AI Ecosystem page showing zero usage: nothing ever
wrote to agent_usage_log, so every agent looked unused.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

_HOOK = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "subagent_usage_log.py"
)
_spec = importlib.util.spec_from_file_location("subagent_usage_log", _HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

SESSION = "5fbda8fb-626b-58c9-b80c-42eb22244577"
KEY = "k" * 32


def _assistant(msg_id, ts, usage, model="claude-sonnet-5-5", stop="end_turn"):
    return {
        "type": "assistant",
        "timestamp": ts,
        "uuid": f"u-{msg_id}-{ts}",
        "message": {"id": msg_id, "model": model, "stop_reason": stop, "usage": usage},
    }


def _write(tmp_path, entries):
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(path)


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


def _failure_log(project_dir) -> str:
    path = project_dir / ".claude" / "hooks" / ".usage-hook.log"
    return path.read_text() if path.exists() else ""


@pytest.fixture
def set_stdin(monkeypatch):
    def _set(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    return _set


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
        assert hook.summarise_transcript(path)["tokens_used"] == 133

    def test_last_line_wins_for_a_response_split_over_several_lines(self, tmp_path):
        path = _write(
            tmp_path,
            [
                _assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 1}),
                _assistant("m1", "2026-10-16T10:00:01Z", {"output_tokens": 9}),
            ],
        )
        assert hook.summarise_transcript(path)["tokens_used"] == 9

    def test_lines_without_a_message_id_are_each_counted(self, tmp_path):
        entries = [
            {
                "type": "assistant",
                "uuid": f"u{i}",
                "message": {"usage": {"output_tokens": 5}},
            }
            for i in range(3)
        ]
        assert hook.summarise_transcript(_write(tmp_path, entries))["tokens_used"] == 15

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
        "stop,expected",
        [("end_turn", True), ("max_tokens", False), ("refusal", False)],
    )
    def test_success_reflects_final_stop_reason(self, tmp_path, stop, expected):
        path = _write(
            tmp_path,
            [_assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 1}, stop=stop)],
        )
        assert hook.summarise_transcript(path)["success"] is expected

    def test_a_final_end_turn_after_an_earlier_max_tokens_is_success(self, tmp_path):
        path = _write(
            tmp_path,
            [
                _assistant(
                    "m1",
                    "2026-10-16T10:00:00Z",
                    {"output_tokens": 1},
                    stop="max_tokens",
                ),
                _assistant("m2", "2026-10-16T10:00:01Z", {"output_tokens": 1}),
            ],
        )
        assert hook.summarise_transcript(path)["success"] is True

    def test_token_total_is_capped_to_what_the_backend_accepts(self, tmp_path):
        path = _write(
            tmp_path,
            [_assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 99_000_000})],
        )
        assert hook.summarise_transcript(path)["tokens_used"] == hook._MAX_TOKENS

    def test_duration_is_capped_to_what_the_backend_accepts(self, tmp_path):
        path = _write(
            tmp_path,
            [
                _assistant("m1", "2026-01-01T00:00:00Z", {"output_tokens": 1}),
                _assistant("m2", "2026-12-31T00:00:00Z", {"output_tokens": 1}),
            ],
        )
        assert hook.summarise_transcript(path)["duration_ms"] == hook._MAX_DURATION_MS

    def test_skips_malformed_and_non_object_lines(self, tmp_path):
        path = tmp_path / "agent.jsonl"
        good = json.dumps(
            _assistant("m1", "2026-10-16T10:00:00Z", {"output_tokens": 4})
        )
        path.write_text("not json\n123\nnull\n[1]\n" + good + "\n")
        assert hook.summarise_transcript(str(path))["tokens_used"] == 4

    def test_mixed_naive_and_aware_timestamps_do_not_crash(self, tmp_path):
        path = _write(
            tmp_path,
            [
                _assistant("m1", "2026-10-16T10:00:00", {"output_tokens": 1}),
                _assistant("m2", "2026-10-16T10:00:01Z", {"output_tokens": 1}),
            ],
        )
        assert hook.summarise_transcript(path)["duration_ms"] == 1000

    def test_unhashable_message_id_does_not_crash(self, tmp_path):
        entry = _assistant("x", "2026-10-16T10:00:00Z", {"output_tokens": 3})
        entry["message"]["id"] = ["not", "a", "string"]
        assert hook.summarise_transcript(_write(tmp_path, [entry]))["tokens_used"] == 3

    def test_binary_transcript_does_not_crash(self, tmp_path):
        path = tmp_path / "agent.jsonl"
        path.write_bytes(b"\xff\xfe\x00\x01 garbage \xff\n")
        assert hook.summarise_transcript(str(path))["tokens_used"] == 0

    def test_empty_transcript_gives_no_model_or_duration(self, tmp_path):
        path = tmp_path / "agent.jsonl"
        path.write_text("")
        result = hook.summarise_transcript(str(path))
        assert result == {
            "model": None,
            "tokens_used": 0,
            "duration_ms": None,
            "success": True,
        }


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

    @pytest.mark.parametrize("agent_type", ["", "   ", None, 5, ["x"]])
    def test_skips_unnamed_or_malformed_agent_types(self, agent_type):
        assert hook.build_payload({"agent_type": agent_type}) is None

    @pytest.mark.parametrize("payload", [[], None, "text", 7])
    def test_skips_a_payload_that_is_not_an_object(self, payload):
        assert hook.build_payload(payload) is None

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

    def test_unreadable_transcript_still_records_the_run_and_logs_why(
        self, tmp_path, project_dir, monkeypatch
    ):
        transcript = tmp_path / "agent.jsonl"
        transcript.write_text("{}")

        def _boom(_path):
            raise PermissionError("denied")

        monkeypatch.setattr(hook, "summarise_transcript", _boom)
        body = hook.build_payload(
            {"agent_type": "Explore", "agent_transcript_path": str(transcript)}
        )
        assert body == {"agent_name": "Explore"}
        assert "could not read transcript for Explore" in _failure_log(project_dir)


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code):
    return urllib.error.HTTPError("https://x.test", code, "msg", {}, None)


class TestPost:
    URL = "https://x.test"

    def test_sends_the_key_header_url_and_json_body(self, monkeypatch):
        seen = []

        def _urlopen(request, timeout):
            seen.append((request, timeout))
            return _Resp(201)

        monkeypatch.setattr(hook.urllib.request, "urlopen", _urlopen)
        assert hook.post(self.URL, KEY, {"agent_name": "Explore"}) is None
        request, timeout = seen[0]
        assert request.full_url == "https://x.test/api/v1/ai-ecosystem/log"
        assert request.get_method() == "POST"
        assert request.get_header("X-usage-key") == KEY
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data) == {"agent_name": "Explore"}
        assert timeout == hook.REQUEST_TIMEOUT_SECONDS

    def test_trailing_slash_on_the_base_url_is_handled(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            hook.urllib.request,
            "urlopen",
            lambda request, timeout: seen.append(request.full_url) or _Resp(201),
        )
        hook.post("https://x.test/", KEY, {})
        assert seen == ["https://x.test/api/v1/ai-ecosystem/log"]

    def test_retries_a_network_error_then_succeeds(self, monkeypatch):
        calls = []

        def _urlopen(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError("boom")
            return _Resp(201)

        monkeypatch.setattr(hook.urllib.request, "urlopen", _urlopen)
        assert hook.post(self.URL, KEY, {}) is None
        assert len(calls) == 2

    @pytest.mark.parametrize("code", [400, 401, 403, 422])
    def test_a_rejected_request_is_not_retried(self, monkeypatch, code):
        calls = []

        def _urlopen(request, timeout):
            calls.append(1)
            raise _http_error(code)

        monkeypatch.setattr(hook.urllib.request, "urlopen", _urlopen)
        assert hook.post(self.URL, KEY, {}) == f"server answered {code}"
        assert len(calls) == 1

    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
    def test_a_server_error_is_retried_then_reported(self, monkeypatch, code):
        calls = []

        def _urlopen(request, timeout):
            calls.append(1)
            raise _http_error(code)

        monkeypatch.setattr(hook.urllib.request, "urlopen", _urlopen)
        assert hook.post(self.URL, KEY, {}) == f"server answered {code}"
        assert len(calls) == hook.ATTEMPTS

    def test_a_timeout_is_reported_with_its_type(self, monkeypatch):
        def _urlopen(request, timeout):
            raise TimeoutError("slow")

        monkeypatch.setattr(hook.urllib.request, "urlopen", _urlopen)
        assert "TimeoutError" in hook.post(self.URL, KEY, {})

    def test_an_unexpected_success_status_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            hook.urllib.request, "urlopen", lambda request, timeout: _Resp(302)
        )
        assert "302" in hook.post(self.URL, KEY, {})


class TestIsSafeUrl:
    @pytest.mark.parametrize(
        "url",
        ["https://arshad-ai.onrender.com", "http://localhost:8000", "http://127.0.0.1"],
    )
    def test_allowed(self, url):
        assert hook._is_safe_url(url) is True

    @pytest.mark.parametrize(
        "url", ["http://example.com", "ftp://x.test", "file:///etc/passwd", "x.test"]
    )
    def test_refused(self, url):
        assert hook._is_safe_url(url) is False


class TestRecordFailure:
    def test_appends_to_the_local_log(self, project_dir, capsys):
        hook.record_failure("first")
        hook.record_failure("second")
        lines = _failure_log(project_dir).splitlines()
        assert [line.split(" ", 1)[1] for line in lines] == ["first", "second"]
        assert "usage hook: first" in capsys.readouterr().err

    def test_an_unwritable_log_location_never_raises(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/nonexistent/dir")
        hook.record_failure("still fine")


class TestMain:
    def test_does_nothing_without_a_key(self, monkeypatch):
        monkeypatch.delenv("ARSHAD_USAGE_KEY", raising=False)
        calls = []
        monkeypatch.setattr(hook, "post", lambda *a: calls.append(a))
        assert hook.main() == 0
        assert calls == []

    def test_refuses_plain_http_to_a_remote_host(self, monkeypatch, project_dir):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", KEY)
        monkeypatch.setenv("ARSHAD_USAGE_URL", "http://example.com")
        calls = []
        monkeypatch.setattr(hook, "post", lambda *a: calls.append(a))
        assert hook.main() == 0
        assert calls == []
        assert "https" in _failure_log(project_dir)

    def test_posts_the_built_body_with_the_key(self, monkeypatch, set_stdin):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", KEY)
        monkeypatch.delenv("ARSHAD_USAGE_URL", raising=False)
        sent = []
        monkeypatch.setattr(
            hook, "post", lambda url, key, body: sent.append((url, key, body))
        )
        set_stdin({"agent_type": "Explore"})
        assert hook.main() == 0
        assert sent == [(hook.DEFAULT_URL, KEY, {"agent_name": "Explore"})]

    def test_a_failed_post_exits_zero_and_leaves_a_trace(
        self, monkeypatch, set_stdin, project_dir
    ):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", KEY)
        monkeypatch.setattr(hook, "post", lambda *a: "server answered 401")
        set_stdin({"agent_type": "Explore"})
        assert hook.main() == 0
        assert "could not record Explore: server answered 401" in _failure_log(
            project_dir
        )

    def test_an_unnamed_agent_posts_nothing(self, monkeypatch, set_stdin):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", KEY)
        calls = []
        monkeypatch.setattr(hook, "post", lambda *a: calls.append(a))
        set_stdin({"agent_type": ""})
        assert hook.main() == 0
        assert calls == []

    def test_invalid_json_on_stdin_exits_zero_and_leaves_a_trace(
        self, monkeypatch, project_dir
    ):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", KEY)
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert hook.main() == 0
        assert "unexpected JSONDecodeError" in _failure_log(project_dir)

    def test_any_unexpected_error_exits_zero_and_leaves_a_trace(
        self, monkeypatch, set_stdin, project_dir
    ):
        monkeypatch.setenv("ARSHAD_USAGE_KEY", KEY)

        def _boom(_payload):
            raise RuntimeError("bug")

        monkeypatch.setattr(hook, "build_payload", _boom)
        set_stdin({"agent_type": "Explore"})
        assert hook.main() == 0
        assert "unexpected RuntimeError" in _failure_log(project_dir)
