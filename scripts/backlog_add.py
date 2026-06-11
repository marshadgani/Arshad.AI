#!/usr/bin/env python3
"""CLI to add tasks to tasks/backlog.md.

Usage:
    python scripts/backlog_add.py \\
        --title "Add dark mode toggle" \\
        --description "Add dark/light mode toggle to TopBar, persist in localStorage." \\
        --context "frontend/src/components/TopBar/" \\
        --autonomous yes

    python scripts/backlog_add.py \\
        --title "Decide on rate-limiting strategy" \\
        --description "Choose between token-bucket and sliding-window for the API." \\
        --autonomous no
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_FILE = REPO_ROOT / "tasks" / "backlog.md"


def _next_id(content: str) -> str:
    """Return the next TASK-NNN id, one higher than the current max."""
    ids = re.findall(r"### (TASK-(\d+))", content)
    if not ids:
        return "TASK-001"
    max_n = max(int(n) for _, n in ids)
    return f"TASK-{max_n + 1:03d}"


def add_task(
    title: str,
    description: str,
    context: str,
    autonomous: bool,
    status: str = "pending",
) -> str:
    """Append a task to backlog.md and return the assigned task ID."""
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not BACKLOG_FILE.exists():
        BACKLOG_FILE.write_text(
            "# Arshad.AI Autonomous Backlog\n\n---\n\n",
            encoding="utf-8",
        )

    content = BACKLOG_FILE.read_text(encoding="utf-8")
    task_id = _next_id(content)
    requires = "no" if autonomous else "yes"
    today = date.today().isoformat()

    block = (
        f"\n### {task_id}\n"
        f"- status: {status}\n"
        f"- requires_human: {requires}\n"
        f"- title: {title}\n"
        f"- added: {today}\n"
        f"- description: {description}\n"
        f"- context: {context or 'none'}\n"
    )

    # Append before the final newline
    updated = content.rstrip("\n") + "\n" + block + "\n"
    BACKLOG_FILE.write_text(updated, encoding="utf-8")
    return task_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a task to tasks/backlog.md")
    parser.add_argument("--title", required=True, help="Short task title")
    parser.add_argument("--description", required=True, help="Full task description")
    parser.add_argument(
        "--context", default="", help="Relevant files/dirs (space-separated)"
    )
    parser.add_argument(
        "--autonomous",
        choices=["yes", "no"],
        default="yes",
        help="yes = no human input needed (auto-executable); no = requires Arshad",
    )
    args = parser.parse_args()

    task_id = add_task(
        title=args.title,
        description=args.description,
        context=args.context,
        autonomous=args.autonomous == "yes",
    )
    print(f"Added {task_id}: {args.title}")
    print(f"  autonomous: {args.autonomous}")
    print(f"  file: {BACKLOG_FILE}")


if __name__ == "__main__":
    main()
