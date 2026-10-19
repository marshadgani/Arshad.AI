#!/usr/bin/env python3
"""SubagentStop hook: record every Claude Code subagent run in the AI Ecosystem page.

Reads the hook payload on stdin, summarises the subagent's own transcript
(model, tokens, duration) and POSTs one row to /api/v1/ai-ecosystem/log.

Configuration (environment):
  ARSHAD_USAGE_KEY  dedicated ingest key (same value as AGENT_USAGE_INGEST_KEY
                    on the backend). Unset means the hook does nothing.
  ARSHAD_USAGE_URL  backend origin, default https://arshad-ai.onrender.com

Never blocks a subagent from stopping: every path exits 0. The hook runs
async, so stderr is probably never shown. Failures are therefore also
appended to .claude/hooks/.usage-hook.log (gitignored) so a silent zero on the
AI Ecosystem page can be traced.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

DEFAULT_URL = "https://arshad-ai.onrender.com"
LOG_PATH = "/api/v1/ai-ecosystem/log"
FAILURE_LOG = os.path.join(".claude", "hooks", ".usage-hook.log")
REQUEST_TIMEOUT_SECONDS = 45  # Render free-tier cold start can take ~30s
ATTEMPTS = 2  # 2 x 45s stays inside the 100s hook timeout in settings.json
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_FAILED_STOP_REASONS = {"max_tokens", "refusal"}
# Mirrors the LogRequest caps in backend/src/schemas/ai_ecosystem.py. Keep equal.
_MAX_TOKENS = 10_000_000
_MAX_DURATION_MS = 604_800_000
_REJECTED_CODES = (400, 401, 403, 422)  # retrying cannot fix a rejected request


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Mixed naive and aware stamps cannot be subtracted. Treat naive as UTC.
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


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

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
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
                key = str(message.get("id") or entry.get("uuid") or len(usage_by_id))
                usage_by_id[key] = usage
            if isinstance(message.get("model"), str) and message["model"]:
                model = message["model"]
            if isinstance(message.get("stop_reason"), str):
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
        "tokens_used": min(tokens, _MAX_TOKENS),
        "duration_ms": None
        if duration_ms is None
        else min(duration_ms, _MAX_DURATION_MS),
        "success": last_stop_reason not in _FAILED_STOP_REASONS,
    }


def build_payload(hook_input: object) -> dict | None:
    """Turn a SubagentStop hook payload into a /log request body, or None to skip."""
    if not isinstance(hook_input, dict):
        return None
    agent_type = hook_input.get("agent_type")
    if not isinstance(agent_type, str) or not agent_type.strip():
        return None  # internal agents (prompt suggestions, /btw) have no name

    body: dict = {"agent_name": agent_type.strip()}
    transcript = hook_input.get("agent_transcript_path")
    if isinstance(transcript, str) and os.path.isfile(transcript):
        try:
            body.update(summarise_transcript(transcript))
        except OSError as exc:
            # Still record the run, just without token data.
            record_failure(f"could not read transcript for {agent_type}: {exc}")
    session_id = hook_input.get("session_id")
    if isinstance(session_id, str) and _UUID_RE.match(session_id):
        body["session_id"] = session_id
    return {k: v for k, v in body.items() if v is not None}


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def record_failure(message: str) -> None:
    """Print to stderr and append to the local failure log. Best effort."""
    print(f"usage hook: {message}", file=sys.stderr)
    base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        with open(os.path.join(base, FAILURE_LOG), "a", encoding="utf-8") as fh:
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass


def post(base_url: str, key: str, body: dict) -> str | None:
    """POST one row. Return None on success, otherwise a short reason."""
    request = urllib.request.Request(
        base_url.rstrip("/") + LOG_PATH,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Usage-Key": key},
        method="POST",
    )
    reason = "no attempt made"
    for _ in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as resp:
                if 200 <= resp.status < 300:
                    return None
                reason = f"unexpected status {resp.status}"
        except urllib.error.HTTPError as exc:
            reason = f"server answered {exc.code}"
            if exc.code in _REJECTED_CODES:
                return reason
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
    return reason


def main() -> int:
    key = os.environ.get("ARSHAD_USAGE_KEY", "")
    if not key:
        return 0
    base_url = os.environ.get("ARSHAD_USAGE_URL", DEFAULT_URL)
    if not _is_safe_url(base_url):
        record_failure("ARSHAD_USAGE_URL must be https")
        return 0
    try:
        body = build_payload(json.load(sys.stdin))
        if body is None:
            return 0
        error = post(base_url, key, body)
        if error:
            record_failure(f"could not record {body['agent_name']}: {error}")
    except Exception as exc:  # a logger must never fail a subagent
        record_failure(f"unexpected {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
