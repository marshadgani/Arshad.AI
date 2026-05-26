"""
Self-healing loop for Render deployments.

1. Checks the service health endpoint.
2. If unhealthy: fetches the latest Render logs.
3. Sends logs + relevant source files to Claude API for diagnosis.
4. Applies Claude's fix to the codebase.
5. Commits and pushes — triggering a fresh Render deploy.
6. Repeats up to MAX_HEAL_ATTEMPTS times.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import httpx

# ── Config ────────────────────────────────────────────────────────────────────
RENDER_API_KEY = os.environ["RENDER_API_KEY"]
SERVICE_ID = os.environ["RENDER_SERVICE_ID"]
HEALTH_URL = os.environ["RENDER_HEALTH_URL"]
MAX_ATTEMPTS = int(os.environ.get("MAX_HEAL_ATTEMPTS", 3))

HEADERS = {"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"}
REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FILE = Path("/tmp/heal_summary.md")

# Source files Claude will read when diagnosing
CONTEXT_FILES = [
    "backend/src/main.py",
    "backend/src/models/database.py",
    "backend/alembic/env.py",
    "backend/requirements.txt",
    "backend/Dockerfile",
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(msg, flush=True)


def append_summary(text: str) -> None:
    with open(SUMMARY_FILE, "a") as f:
        f.write(text + "\n")


def is_healthy() -> bool:
    """Return True if the health endpoint returns 2xx."""
    try:
        r = httpx.get(HEALTH_URL, timeout=30, follow_redirects=True)
        log(f"  Health check → HTTP {r.status_code}")
        return r.status_code < 400
    except Exception as e:
        log(f"  Health check failed: {e}")
        return False


def fetch_render_logs(lines: int = 200) -> str:
    """Fetch the most recent log lines from Render."""
    url = f"https://api.render.com/v1/services/{SERVICE_ID}/logs?limit={lines}"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        entries = r.json()
        return "\n".join(e.get("message", "") for e in entries)
    except Exception as e:
        return f"(Could not fetch logs: {e})"


def read_source_files() -> str:
    """Read relevant source files to give Claude context."""
    parts = []
    for rel_path in CONTEXT_FILES:
        full = REPO_ROOT / rel_path
        if full.exists():
            content = full.read_text(errors="replace")
            parts.append(f"### {rel_path}\n```\n{content}\n```")
    return "\n\n".join(parts)


def ask_claude_for_fix(logs: str, source_context: str) -> list[dict]:
    """
    Call Claude API with the error logs and source files.
    Returns a list of file fixes: [{"path": "...", "content": "..."}]
    Returns None if ANTHROPIC_API_KEY is not configured.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log("  ⚠️ ANTHROPIC_API_KEY not set — skipping AI fix, logging only.")
        return None  # type: ignore[return-value]

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are a senior backend engineer debugging a production deployment failure. "
        "You give minimal, precise fixes — never refactor beyond what is needed to restore the service."
    )

    user_prompt = f"""The Render service health check is failing. Here are the recent logs:

<logs>
{logs}
</logs>

Here are the relevant source files:

<source_files>
{source_context}
</source_files>

Diagnose the root cause of the failure and provide the minimal fix.

Respond with ONLY a JSON array of file changes. Each item must have:
- "path": relative path from repo root (e.g. "backend/src/main.py")
- "content": the complete new file content (not a diff — full file)

Example format:
[
  {{
    "path": "backend/src/models/database.py",
    "content": "... full file content ..."
  }}
]

If no code change can fix this (e.g. it is a missing env var or external service issue),
return an empty array [] and I will alert the developer.

Return ONLY the JSON array — no explanation, no markdown wrapping."""

    log("  Asking Claude to diagnose and fix...")
    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=8096,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                # Cache the system prompt — source files are large and reused across attempts
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    log(
        f"  Tokens used — input: {message.usage.input_tokens}, output: {message.usage.output_tokens}"
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wrapped the response
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        fixes = json.loads(raw)
        if not isinstance(fixes, list):
            raise ValueError("Expected a JSON array")
        return fixes
    except Exception as e:
        log(f"  ⚠️ Could not parse Claude's response: {e}")
        log(f"  Raw response: {raw[:500]}")
        return []


def apply_fixes(fixes: list[dict]) -> list[str]:
    """Write fixed file contents to disk. Returns list of paths changed."""
    changed = []
    for fix in fixes:
        path = fix.get("path", "").strip()
        content = fix.get("content", "")
        if not path or not content:
            continue
        full = REPO_ROOT / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        log(f"  ✏️  Applied fix to: {path}")
        changed.append(path)
    return changed


def git_commit_and_push(changed_files: list[str], attempt: int) -> bool:
    """Commit changed files and push to trigger a new Render deploy."""
    try:
        subprocess.run(
            ["git", "config", "user.email", "claude-heal@arshad.ai"],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Claude Self-Heal"],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(["git", "add"] + changed_files, cwd=REPO_ROOT, check=True)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"fix: auto-heal attempt {attempt} — Claude diagnosed and patched deployment failure",
            ],
            cwd=REPO_ROOT,
            check=True,
        )

        # Set remote URL with token for push
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if token and repo:
            remote = f"https://x-access-token:{token}@github.com/{repo}.git"
            subprocess.run(
                ["git", "remote", "set-url", "origin", remote],
                cwd=REPO_ROOT,
                check=True,
            )

        branch = (
            subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO_ROOT)
            .decode()
            .strip()
        )

        subprocess.run(["git", "push", "origin", branch], cwd=REPO_ROOT, check=True)
        log(f"  📤 Pushed fix to {branch}")
        return True
    except subprocess.CalledProcessError as e:
        log(f"  ❌ Git error: {e}")
        return False


def wait_for_deploy(timeout: int = 600) -> None:
    """Wait for Render to pick up and complete the new deploy."""
    log("  ⏳ Waiting 60s for Render to pick up the new deploy...")
    time.sleep(60)  # Give Render time to detect the push

    elapsed = 60
    while elapsed < timeout:
        url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys?limit=1"
        try:
            r = httpx.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            deploys = r.json()
            if deploys:
                status = deploys[0]["deploy"].get("status", "unknown")
                log(f"  [{elapsed}s] Deploy status: {status}")
                if status in ("live", "deactivated", "build_failed", "update_failed"):
                    break
        except Exception as e:
            log(f"  (Could not poll deploy status: {e})")
        time.sleep(20)
        elapsed += 20


# ── Main loop ─────────────────────────────────────────────────────────────────


def main() -> None:
    append_summary("## 🔧 Render Self-Heal Log\n")

    # Initial health check
    log(f"\n🏥 Checking health: {HEALTH_URL}")
    if is_healthy():
        log("✅ Service is healthy. Nothing to do.")
        append_summary("✅ **Service was healthy on first check — no action needed.**")
        sys.exit(0)

    log("❌ Service is unhealthy. Starting self-heal loop...")
    append_summary("❌ **Service unhealthy — starting self-heal loop.**\n")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"\n{'=' * 60}")
        log(f"🔁 Heal attempt {attempt} / {MAX_ATTEMPTS}")
        log(f"{'=' * 60}")
        append_summary(f"\n### Attempt {attempt}\n")

        # 1. Fetch logs
        log("  📋 Fetching Render logs...")
        logs = fetch_render_logs()
        log(f"  Got {len(logs.splitlines())} log lines")
        append_summary(f"**Logs fetched:** {len(logs.splitlines())} lines\n")

        # 2. Read source files
        source_context = read_source_files()

        # 3. Ask Claude
        fixes = ask_claude_for_fix(logs, source_context)

        if not fixes:
            log(
                "  ⚠️ Claude returned no fixes — may be an infrastructure/env var issue."
            )
            append_summary(
                "⚠️ **Claude returned no code fixes** — likely an env var or external service issue. Manual intervention needed.\n"
            )
            break

        log(f"  Claude suggested {len(fixes)} file fix(es):")
        for f in fixes:
            log(f"    - {f.get('path', '?')}")
            append_summary(f"- Fixed: `{f.get('path', '?')}`\n")

        # 4. Apply fixes
        changed = apply_fixes(fixes)
        if not changed:
            log("  ⚠️ No files were changed.")
            break

        # 5. Commit and push
        pushed = git_commit_and_push(changed, attempt)
        if not pushed:
            log("  ❌ Push failed. Stopping.")
            append_summary("❌ **Git push failed.**\n")
            break

        # 6. Wait for Render to redeploy
        wait_for_deploy()

        # 7. Check health again
        log(f"\n🏥 Re-checking health after attempt {attempt}...")
        if is_healthy():
            log(f"✅ Service is healthy after attempt {attempt}!")
            append_summary(f"\n✅ **Service recovered after attempt {attempt}!**")
            sys.exit(0)

        log(f"  Still unhealthy after attempt {attempt}.")
        append_summary(f"❌ Still unhealthy after attempt {attempt}.\n")

    # All attempts exhausted
    log(
        f"\n🚨 Service still down after {MAX_ATTEMPTS} heal attempts. Manual intervention required."
    )
    append_summary(
        f"\n🚨 **All {MAX_ATTEMPTS} attempts exhausted. Manual intervention required.**"
    )
    sys.exit(1)  # Fail the workflow so GitHub notifies you


if __name__ == "__main__":
    main()
