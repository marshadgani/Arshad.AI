#!/usr/bin/env python3
"""
Autonomous backlog executor.

Reads the next pending autonomous task from tasks/backlog.md,
executes it via Claude claude-sonnet-4-6 with file-manipulation tools,
and marks it done (or blocked).

Called by .github/workflows/autonomous-backlog.yml.
Writes /tmp/task_id.txt and /tmp/task_title.txt for the commit step.
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
        # Multi-line description / context (everything after the key on first line)
        for key in ("description", "context"):
            mm = re.search(rf"- {key}: (.+?)(?=\n- |\Z)", body, re.DOTALL)
            if mm:
                fields[key] = mm.group(1).strip()
        tasks.append(fields)
    return tasks


def _find_next_task(tasks: list[dict]) -> dict | None:
    for t in tasks:
        if (
            t.get("status", "pending") == "pending"
            and t.get("requires_human", "no").lower() == "no"
        ):
            return t
    return None


def _mark_done(task_id: str, summary: str) -> None:
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

    updated = re.sub(
        r"^### " + re.escape(task_id) + r"\n.*?(?=^### |\Z)",
        _replace,
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    BACKLOG_FILE.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


def _handle_tool(name: str, inp: dict) -> str:
    if name == "read_file":
        p = REPO_ROOT / inp["path"]
        if not p.exists():
            return f"ERROR: file not found: {inp['path']}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as exc:
            return f"ERROR reading file: {exc}"

    if name == "write_file":
        p = REPO_ROOT / inp["path"]
        # Safety: stay inside repo
        try:
            p.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            return f"ERROR: path escapes repo root: {inp['path']}"
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(inp["content"], encoding="utf-8")
            return f"Written {inp['path']} ({len(inp['content'])} chars)"
        except Exception as exc:
            return f"ERROR writing file: {exc}"

    if name == "list_directory":
        p = REPO_ROOT / inp.get("path", ".")
        if not p.exists():
            return f"ERROR: not found: {inp['path']}"
        try:
            lines = [
                f"{'d' if i.is_dir() else 'f'}  {i.name}" for i in sorted(p.iterdir())
            ]
            return "\n".join(lines) or "(empty)"
        except Exception as exc:
            return f"ERROR: {exc}"

    if name == "search_code":
        pattern = inp["pattern"]
        search_path = str(REPO_ROOT / inp.get("path", "."))
        file_glob = inp.get("file_glob", "")
        cmd = [
            "grep",
            "-rn",
            "--include=" + file_glob if file_glob else "",
            "-E",
            pattern,
            search_path,
        ]
        cmd = [c for c in cmd if c]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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

    user_msg = (
        f"**Task:** {task['id']} — {task.get('title', '(no title)')}\n\n"
        f"**Description:**\n{task.get('description', '(none)')}\n\n"
        f"**Context files/dirs:** {task.get('context', 'none')}\n\n"
        "Start by reading the context files, then make the necessary changes."
    )

    messages: list[dict] = [{"role": "user", "content": user_msg}]
    completion_summary = "Task executed (no explicit completion signal)"
    max_iters = 25

    for _ in range(max_iters):
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=system,
            tools=TOOLS,  # type: ignore[arg-type]
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            break

        if resp.stop_reason != "tool_use":
            print(f"[warn] unexpected stop_reason={resp.stop_reason}")
            break

        tool_results = []
        done = False
        for block in resp.content:
            if not hasattr(block, "type") or block.type != "tool_use":
                continue
            result_text = _handle_tool(block.name, block.input)
            if block.name == "task_complete":
                completion_summary = block.input.get("summary", "done")
                done = True
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_text}
            )

        messages.append({"role": "user", "content": tool_results})
        if done:
            break

    return completion_summary


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    tasks = _parse_backlog()
    task = _find_next_task(tasks)

    if task is None:
        print("No autonomous pending tasks. Nothing to do.")
        # Signal to workflow: no task ran
        Path("/tmp/task_id.txt").write_text("")
        sys.exit(0)

    print(f"Executing {task['id']}: {task.get('title', '?')}")

    # Write task metadata for the git-commit step in the workflow
    Path("/tmp/task_id.txt").write_text(task["id"])
    Path("/tmp/task_title.txt").write_text(task.get("title", "autonomous task"))

    summary = _execute_task(task)
    _mark_done(task["id"], summary)

    blocked = summary.startswith("BLOCKED:")
    status = "BLOCKED" if blocked else "DONE"
    print(f"[{status}] {task['id']}: {summary}")

    # Exit 2 = blocked (workflow skips commit, leaves task pending)
    sys.exit(2 if blocked else 0)


if __name__ == "__main__":
    main()
