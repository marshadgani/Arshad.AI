#!/usr/bin/env python3
"""
Autonomous backlog executor.

Reads the next pending autonomous task from tasks/backlog.md,
executes it via Claude claude-sonnet-4-6 with file-manipulation tools,
and marks it done (or blocked).

Called by .github/workflows/autonomous-backlog.yml.
Exit codes: 0=done, 1=error, 2=blocked.
Writes /tmp/task_id.txt and /tmp/task_title.txt (empty string when no task found).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_FILE = REPO_ROOT / "tasks" / "backlog.md"
MAX_ITERATIONS = 25

TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read a file from the repository. Path is relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to repo root"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file. Path is relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a path (relative to repo root).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Grep for a pattern in the codebase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern"},
                "path": {
                    "type": "string",
                    "description": "Directory to search (relative to repo root)",
                    "default": ".",
                },
                "file_glob": {
                    "type": "string",
                    "description": "File pattern, e.g. '*.tsx'",
                    "default": "",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "task_complete",
        "description": (
            "Signal the task is finished. Call when all file changes are written. "
            "If you cannot complete it, prefix summary with 'BLOCKED: '."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "What was done (≤200 chars)",
                }
            },
            "required": ["summary"],
        },
    },
]


# ---------------------------------------------------------------------------
# Backlog parsing
# ---------------------------------------------------------------------------


def _parse_backlog() -> list[dict]:
    """Parse tasks/backlog.md into a list of task dicts.

    Returns an empty list if the file does not exist or has no task blocks.
    Each dict has at minimum an 'id' key; other keys come from '- key: val' lines.
    """
    if not BACKLOG_FILE.exists():
        return []
    content = BACKLOG_FILE.read_text(encoding="utf-8")
    tasks = []
    for m in re.finditer(
        r"^### (TASK-\d+)\n(.*?)(?=^### |\Z)", content, re.MULTILINE | re.DOTALL
    ):
        task_id, body = m.group(1), m.group(2)
        fields: dict[str, str] = {"id": task_id}
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("- ") and ": " in line:
                key, _, val = line[2:].partition(": ")
                fields[key.strip()] = val.strip()
        # Re-parse description/context to capture everything after the key
        # (single-line values already captured above; this handles edge cases)
        for key in ("description", "context"):
            mm = re.search(rf"- {key}: (.+?)(?=\n- |\Z)", body, re.DOTALL)
            if mm:
                fields[key] = mm.group(1).strip()
        tasks.append(fields)
    return tasks


def _find_next_task(tasks: list[dict]) -> dict | None:
    """Return the first pending task that does not require human input.

    Skips tasks where requires_human is 'yes' — those stay in the backlog
    until Arshad reviews them.
    """
    for t in tasks:
        if (
            t.get("status", "pending") == "pending"
            and t.get("requires_human", "no").lower() == "no"
        ):
            return t
    return None


def _mark_done(task_id: str, summary: str) -> None:
    """Update task_id status to 'done' and append completion metadata.

    Raises RuntimeError if task_id is not found in the backlog file — a
    missing match would otherwise silently write the file back unchanged,
    leaving the task perpetually pending.
    """
    content = BACKLOG_FILE.read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    short_summary = summary[:200].replace("\n", " ")

    def _replace(m: re.Match) -> str:
        block = m.group(0)
        block = re.sub(r"- status: \w+", "- status: done", block)
        block = re.sub(r"- completed: [^\n]+\n?", "", block)
        block = re.sub(r"- completion_summary: [^\n]+\n?", "", block)
        block = re.sub(
            r"(- status: done\n)",
            f"\\1- completed: {today}\n- completion_summary: {short_summary}\n",
            block,
        )
        return block

    updated, n_subs = re.subn(
        r"^### " + re.escape(task_id) + r"\n.*?(?=^### |\Z)",
        _replace,
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    if n_subs == 0:
        raise RuntimeError(
            f"_mark_done: task '{task_id}' not found in backlog — "
            "file may have been modified externally or task ID is malformed"
        )
    BACKLOG_FILE.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


def _handle_tool(name: str, inp: dict) -> str:
    """Execute a Claude tool call and return the result as a string.

    Returns an 'ERROR: ...' string on failure rather than raising — the error
    string is fed back to Claude as a tool_result so it can recover or abort.
    """
    if name == "read_file":
        p = REPO_ROOT / inp["path"]
        # Guard path traversal (SEC-001)
        try:
            p.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            return f"ERROR: path escapes repo root: {inp['path']}"
        if not p.exists():
            return f"ERROR: file not found: {inp['path']}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as exc:
            return f"ERROR reading file: {exc}"

    if name == "write_file":
        p = REPO_ROOT / inp["path"]
        # Guard path traversal: resolve symlinks then confirm still inside repo
        try:
            resolved = p.resolve()
            resolved.relative_to(REPO_ROOT.resolve())
        except ValueError:
            return f"ERROR: path escapes repo root: {inp['path']}"
        # Denylist using the resolved canonical path (immune to absolute-path bypass — SEC-NEW-001)
        _WRITE_DENYLIST = (
            ".github/",
            "tasks/last-gate-report.md",
            ".git/",
            ".claude/",
            "alembic/",
            "scripts/",
            "docker-compose.yml",
            "backend/Dockerfile",
        )
        rel_str = str(resolved.relative_to(REPO_ROOT.resolve()))
        if any(
            rel_str == d.rstrip("/") or rel_str.startswith(d) for d in _WRITE_DENYLIST
        ):
            return f"ERROR: write to protected path denied: {inp['path']}"
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(inp["content"], encoding="utf-8")
            return f"Written {inp['path']} ({len(inp['content'])} chars)"
        except Exception as exc:
            return f"ERROR writing file: {exc}"

    if name == "list_directory":
        p = REPO_ROOT / inp.get("path", ".")
        # Guard path traversal (SEC-002)
        try:
            p.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            return f"ERROR: path escapes repo root: {inp.get('path', '.')}"
        if not p.exists():
            return f"ERROR: not found: {inp.get('path', '.')}"
        try:
            lines = [
                f"{'d' if i.is_dir() else 'f'}  {i.name}" for i in sorted(p.iterdir())
            ]
            return "\n".join(lines) or "(empty)"
        except Exception as exc:
            return f"ERROR: {exc}"

    if name == "search_code":
        pattern = inp["pattern"]
        # Guard against catastrophic backtracking via oversized patterns (SEC-007)
        if len(pattern) > 200:
            return "ERROR: pattern too long (max 200 chars)"
        # Guard path traversal on search root (SEC-NEW-002)
        raw_path = inp.get("path", ".")
        sp = (REPO_ROOT / raw_path).resolve()
        try:
            sp.relative_to(REPO_ROOT.resolve())
        except ValueError:
            return f"ERROR: path escapes repo root: {raw_path}"
        search_path = str(sp)
        file_glob = inp.get("file_glob", "")
        cmd = [
            "grep",
            "-rn",
            "--include=" + file_glob if file_glob else "",
            "-E",
            "--",
            pattern,
            search_path,
        ]
        cmd = [c for c in cmd if c]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode not in (0, 1):
                return f"ERROR: grep failed (exit {res.returncode}): {res.stderr.strip()[:200]}"
            return res.stdout[:5000] or "(no matches)"
        except subprocess.TimeoutExpired:
            return "ERROR: search timed out"
        except Exception as exc:
            return f"ERROR: {exc}"

    if name == "task_complete":
        return f"ACK: {inp.get('summary', '')}"

    return f"ERROR: unknown tool {name}"


# ---------------------------------------------------------------------------
# Main execution loop
# ---------------------------------------------------------------------------


def _execute_task(task: dict) -> str:
    """Run a tool-use conversation loop to execute the given task.

    Returns the summary string from task_complete. Prefixes with 'BLOCKED:'
    if the model did not call task_complete (e.g., hit max_tokens or
    iteration limit) — this prevents silently marking a half-executed task done.
    """
    client = anthropic.Anthropic()

    system = f"""You are an autonomous software agent for the Arshad.AI project.
Complete the assigned development task by reading files, making changes, and calling task_complete.

Tech stack:
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 async, Pydantic v2, asyncpg, PostgreSQL
- Frontend: React 18, TypeScript 5 (jsx=react-jsx — never import React namespace), Vite 5, CSS Modules
- noUnusedLocals=true in tsconfig — never leave unused imports or variables
- UUID PKs, async DB sessions, no inline secrets
- Commit style: type(scope): description

Rules:
- Minimal change — only what the task requires
- Match existing code style (read neighbouring files first)
- If the task is ambiguous or requires a human decision, call task_complete with "BLOCKED: <reason>"
- Always call task_complete when done

Repo root: {REPO_ROOT}
"""

    # Wrap task content in XML delimiters so the model treats it as data,
    # not as additional instructions (SEC-008 — prompt injection mitigation).
    user_msg = (
        f"**Task ID:** {task['id']}\n"
        f"**Title:** {task.get('title', '(no title)')}\n\n"
        "<task_description>\n"
        f"{task.get('description', '(none)')}\n"
        "</task_description>\n\n"
        "<context_files>\n"
        f"{task.get('context', 'none')}\n"
        "</context_files>\n\n"
        "Read the context files first, then make the minimal changes the task requires. "
        "Only write to paths inside the repository. "
        "Call task_complete when done."
    )

    messages: list[dict] = [{"role": "user", "content": user_msg}]
    task_complete_called = False
    completion_summary = ""
    last_stop_reason = "unknown"

    for _ in range(MAX_ITERATIONS):
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=system,
            tools=TOOLS,  # type: ignore[arg-type]
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        last_stop_reason = resp.stop_reason or "unknown"

        if resp.stop_reason == "end_turn":
            break

        if resp.stop_reason != "tool_use":
            # max_tokens, stop_sequence, etc. — do not mark done
            print(f"[warn] unexpected stop_reason={resp.stop_reason}")
            break

        tool_results = []
        done = False
        for block in resp.content:
            if not hasattr(block, "type") or block.type != "tool_use":
                continue
            result_text = _handle_tool(block.name, block.input)
            if block.name == "task_complete":
                task_complete_called = True
                completion_summary = block.input.get("summary", "done")
                done = True
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_text}
            )

        # Anthropic API rejects an empty content array on a user turn.
        # If stop_reason was tool_use but no ToolUseBlock was in the response
        # (an edge case the API can produce), skip appending rather than crash.
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if done:
            break

    if not task_complete_called:
        # Model ran out of iterations or tokens without signalling completion.
        # Treat as blocked so _mark_done is NOT called and the task is retried.
        return f"BLOCKED: model did not call task_complete (stop_reason={last_stop_reason})"

    return completion_summary


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Always write the tmp files so the workflow never reads a stale value
    # from a previous run on the same runner.
    _task_id_file = Path("/tmp/task_id.txt")
    _task_title_file = Path("/tmp/task_title.txt")
    _task_id_file.write_text("")
    _task_title_file.write_text("")

    tasks = _parse_backlog()
    task = _find_next_task(tasks)

    if task is None:
        print("No autonomous pending tasks. Nothing to do.")
        sys.exit(0)

    print(f"Executing {task['id']}: {task.get('title', '?')}")
    _task_id_file.write_text(task["id"])
    _task_title_file.write_text(task.get("title", "autonomous task"))

    summary = _execute_task(task)
    blocked = summary.startswith("BLOCKED:")

    if not blocked:
        # Only mark done for completed tasks; blocked tasks stay pending for retry.
        _mark_done(task["id"], summary)

    status = "BLOCKED" if blocked else "DONE"
    print(f"[{status}] {task['id']}: {summary}")

    # Exit 2 = blocked (workflow skips commit, task stays pending for retry)
    sys.exit(2 if blocked else 0)


if __name__ == "__main__":
    main()
