#!/usr/bin/env python3
"""SubagentStop hook: record every Claude Code subagent run in the AI Ecosystem page.

Reads the hook payload on stdin, summarises the subagent's own transcript
(model, tokens, duration) and POSTs one row to /api/v1/ai-ecosystem/log.

Configuration (environment):
  ARSHAD_USAGE_KEY  dedicated ingest key (same value as AGENT_USAGE_INGEST_KEY
                    on the backend). Unset means the hook does nothing.
  ARSHAD_USAGE_URL  backend origin, default https://arshad-ai.onrender.com

Never blocks a subagent from stopping: every path exits 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

DEFAULT_URL = "https://arshad-ai.onrender.com"
LOG_PATH = "/api/v1/ai-ecosystem/log"
REQUEST_TIMEOUT_SECONDS = 45  # Render free-tier cold start can take ~30s
ATTEMPTS = 2
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_FAILED_STOP_REASONS = {"max_tokens", "refusal"}
_MAX_INT = 2_000_000_000


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarise_transcript(path: str) -> dict:
    """Return model, tokens_used, duration_ms and success for one subagent transcript.

    One API response can be written as several transcript lines that share a
    message id, so usage is taken once per id (the last line wins). Cache reads
    are excluded from tokens_used: they re-count the whole context every turn
    and would swamp the figure that reflects work the agent actually did.
    """
    usage_by_id: dict[str, dict] = {}
    model: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    last_stop_reason: str | None = None

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(entry.get("timestamp"))
            if ts is not None:
                first_ts = first_ts or ts
                last_ts = ts
            message = entry.get("message")
            if entry.get("type") != "assistant" or not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if isinstance(usage, dict):
                usage_by_id[
                    message.get("id") or entry.get("uuid") or str(len(usage_by_id))
                ] = usage
            if message.get("model"):
                model = message["model"]
            if message.get("stop_reason"):
                last_stop_reason = message["stop_reason"]

    tokens = 0
    for usage in usage_by_id.values():
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value > 0:
                tokens += value

    duration_ms = None
    if first_ts is not None and last_ts is not None:
        duration_ms = max(0, int((last_ts - first_ts).total_seconds() * 1000))

    return {
        "model": model,
        "tokens_used": min(tokens, _MAX_INT),
        "duration_ms": None if duration_ms is None else min(duration_ms, _MAX_INT),
        "success": last_stop_reason not in _FAILED_STOP_REASONS,
    }


def build_payload(hook_input: dict) -> dict | None:
    """Turn a SubagentStop hook payload into a /log request body, or None to skip."""
    agent_type = (hook_input.get("agent_type") or "").strip()
    if not agent_type:
        return None  # internal agents (prompt suggestions, /btw) have no name

    body: dict = {"agent_name": agent_type}
    transcript = hook_input.get("agent_transcript_path")
    if isinstance(transcript, str) and os.path.isfile(transcript):
        body.update(summarise_transcript(transcript))
    session_id = hook_input.get("session_id")
    if isinstance(session_id, str) and _UUID_RE.match(session_id):
        body["session_id"] = session_id
    return {k: v for k, v in body.items() if v is not None}


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def post(base_url: str, key: str, body: dict) -> bool:
    request = urllib.request.Request(
        base_url.rstrip("/") + LOG_PATH,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Usage-Key": key},
        method="POST",
    )
    for _ in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as resp:
                if 200 <= resp.status < 300:
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403, 422, 503):
                print(
                    f"usage hook: server rejected the row ({exc.code})", file=sys.stderr
                )
                return False  # retrying cannot fix a rejected request
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
    return False


def main() -> int:
    key = os.environ.get("ARSHAD_USAGE_KEY", "")
    if not key:
        return 0
    base_url = os.environ.get("ARSHAD_USAGE_URL", DEFAULT_URL)
    if not _is_safe_url(base_url):
        print("usage hook: ARSHAD_USAGE_URL must be https", file=sys.stderr)
        return 0
    try:
        body = build_payload(json.load(sys.stdin))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"usage hook: bad hook input ({exc})", file=sys.stderr)
        return 0
    if body is not None and not post(base_url, key, body):
        print("usage hook: could not record this subagent run", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
