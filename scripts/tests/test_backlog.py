"""Tests for backlog_run.py and backlog_add.py.

Run with: python -m pytest scripts/tests/test_backlog.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts/ to path so the modules import without installation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backlog_add
import backlog_run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SINGLE_TASK = """\
# Arshad.AI Autonomous Backlog

---

### TASK-001
- status: pending
- requires_human: no
- title: Test task
- added: 2026-06-01
- description: Do something.
- context: scripts/
"""

_MULTI_TASK = """\
# Arshad.AI Autonomous Backlog

---

### TASK-001
- status: done
- requires_human: no
- title: Already done
- added: 2026-06-01
- description: Finished.
- context: none

### TASK-002
- status: pending
- requires_human: yes
- title: Needs human
- added: 2026-06-01
- description: Decide something.
- context: none

### TASK-003
- status: pending
- requires_human: no
- title: Autonomous task
- added: 2026-06-01
- description: Build it.
- context: backend/
"""

_BLOCKED_ONLY = """\
# Arshad.AI Autonomous Backlog

---

### TASK-001
- status: pending
- requires_human: yes
- title: Human required
- added: 2026-06-01
- description: Make a decision.
- context: none
"""


# ---------------------------------------------------------------------------
# _parse_backlog
# ---------------------------------------------------------------------------


def test_parse_backlog_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text("# Arshad.AI Autonomous Backlog\n\n---\n", encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        tasks = backlog_run._parse_backlog()
    assert tasks == []


def test_parse_backlog_missing_file(tmp_path: Path) -> None:
    with patch.object(backlog_run, "BACKLOG_FILE", tmp_path / "nonexistent.md"):
        tasks = backlog_run._parse_backlog()
    assert tasks == []


def test_parse_backlog_extracts_fields(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_SINGLE_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        tasks = backlog_run._parse_backlog()
    assert len(tasks) == 1
    t = tasks[0]
    assert t["id"] == "TASK-001"
    assert t["status"] == "pending"
    assert t["requires_human"] == "no"
    assert t["title"] == "Test task"


def test_parse_backlog_multi_task(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_MULTI_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        tasks = backlog_run._parse_backlog()
    assert len(tasks) == 3
    assert tasks[0]["id"] == "TASK-001"
    assert tasks[2]["id"] == "TASK-003"


# ---------------------------------------------------------------------------
# _find_next_task — autonomy filter (safety property)
# ---------------------------------------------------------------------------


def test_find_next_task_returns_first_pending_autonomous(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_MULTI_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        tasks = backlog_run._parse_backlog()
    result = backlog_run._find_next_task(tasks)
    assert result is not None
    assert result["id"] == "TASK-003"


def test_find_next_task_skips_requires_human_yes() -> None:
    """Safety property: human-flagged tasks are never returned."""
    tasks = [
        {"id": "TASK-001", "status": "pending", "requires_human": "yes"},
        {"id": "TASK-002", "status": "pending", "requires_human": "YES"},
        {"id": "TASK-003", "status": "pending", "requires_human": "Yes"},
    ]
    result = backlog_run._find_next_task(tasks)
    assert result is None


def test_find_next_task_skips_done_tasks() -> None:
    tasks = [
        {"id": "TASK-001", "status": "done", "requires_human": "no"},
        {"id": "TASK-002", "status": "pending", "requires_human": "no"},
    ]
    result = backlog_run._find_next_task(tasks)
    assert result is not None
    assert result["id"] == "TASK-002"


def test_find_next_task_all_human_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_BLOCKED_ONLY, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        tasks = backlog_run._parse_backlog()
    result = backlog_run._find_next_task(tasks)
    assert result is None


def test_find_next_task_empty_list() -> None:
    assert backlog_run._find_next_task([]) is None


def test_find_next_task_missing_requires_human_defaults_skip() -> None:
    """Tasks with no requires_human field default to 'no' — they ARE auto-executable."""
    tasks = [{"id": "TASK-001", "status": "pending"}]
    result = backlog_run._find_next_task(tasks)
    assert result is not None
    assert result["id"] == "TASK-001"


# ---------------------------------------------------------------------------
# _mark_done
# ---------------------------------------------------------------------------


def test_mark_done_updates_status(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_SINGLE_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        backlog_run._mark_done("TASK-001", "Implemented X")
    content = f.read_text(encoding="utf-8")
    assert "- status: done" in content
    assert "- status: pending" not in content


def test_mark_done_adds_completed_and_summary(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_SINGLE_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        backlog_run._mark_done("TASK-001", "Implemented X successfully")
    content = f.read_text(encoding="utf-8")
    assert "- completed:" in content
    assert "- completion_summary: Implemented X successfully" in content


def test_mark_done_completed_task_not_re_selected(tmp_path: Path) -> None:
    """After _mark_done, _find_next_task must not select the same task again."""
    f = tmp_path / "backlog.md"
    f.write_text(_SINGLE_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        backlog_run._mark_done("TASK-001", "Done")
        tasks = backlog_run._parse_backlog()
    result = backlog_run._find_next_task(tasks)
    assert result is None


def test_mark_done_raises_for_missing_task_id(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_SINGLE_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        with pytest.raises(RuntimeError, match="not found in backlog"):
            backlog_run._mark_done("TASK-999", "oops")


def test_mark_done_does_not_bleed_into_adjacent_tasks(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text(_MULTI_TASK, encoding="utf-8")
    with patch.object(backlog_run, "BACKLOG_FILE", f):
        backlog_run._mark_done("TASK-003", "Built it")
    content = f.read_text(encoding="utf-8")
    # TASK-002 must still be pending
    assert "### TASK-002" in content
    task002_block = content[content.index("### TASK-002") :]
    task002_block = task002_block[: task002_block.index("### TASK-003")]
    assert "- status: pending" in task002_block


# ---------------------------------------------------------------------------
# _handle_tool — path traversal guards
# ---------------------------------------------------------------------------


def test_handle_tool_read_file_path_traversal_blocked() -> None:
    result = backlog_run._handle_tool("read_file", {"path": "../../etc/passwd"})
    assert result.startswith("ERROR")


def test_handle_tool_write_file_path_traversal_blocked() -> None:
    result = backlog_run._handle_tool(
        "write_file", {"path": "/etc/passwd", "content": "x"}
    )
    assert result.startswith("ERROR")


def test_handle_tool_write_file_github_dir_blocked() -> None:
    result = backlog_run._handle_tool(
        "write_file", {"path": ".github/workflows/malicious.yml", "content": "x"}
    )
    assert result.startswith("ERROR")


def test_handle_tool_write_file_gate_report_blocked() -> None:
    result = backlog_run._handle_tool(
        "write_file", {"path": "tasks/last-gate-report.md", "content": "GATE PASSED"}
    )
    assert result.startswith("ERROR")


def test_handle_tool_list_directory_traversal_blocked() -> None:
    result = backlog_run._handle_tool("list_directory", {"path": "../../etc"})
    assert result.startswith("ERROR")


def test_handle_tool_search_code_pattern_too_long() -> None:
    long_pattern = "a" * 201
    result = backlog_run._handle_tool("search_code", {"pattern": long_pattern})
    assert result.startswith("ERROR")


# ---------------------------------------------------------------------------
# backlog_add — _next_id
# ---------------------------------------------------------------------------


def test_next_id_empty_file() -> None:
    assert backlog_add._next_id("# no tasks here") == "TASK-001"


def test_next_id_increments_max() -> None:
    content = "### TASK-001\n### TASK-003\n### TASK-002\n"
    assert backlog_add._next_id(content) == "TASK-004"


def test_next_id_numeric_max_not_lexicographic() -> None:
    content = "### TASK-009\n### TASK-010\n"
    assert backlog_add._next_id(content) == "TASK-011"


# ---------------------------------------------------------------------------
# backlog_add — add_task
# ---------------------------------------------------------------------------


def test_add_task_creates_file_if_missing(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    with patch.object(backlog_add, "BACKLOG_FILE", f):
        task_id = backlog_add.add_task(
            title="First task",
            description="Do X",
            context="backend/",
            autonomous=True,
        )
    assert task_id == "TASK-001"
    assert f.exists()
    content = f.read_text(encoding="utf-8")
    assert "### TASK-001" in content
    assert "- status: pending" in content
    assert "- requires_human: no" in content


def test_add_task_requires_human_no_when_autonomous_true(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    with patch.object(backlog_add, "BACKLOG_FILE", f):
        backlog_add.add_task("T", "D", "", autonomous=True)
    content = f.read_text(encoding="utf-8")
    assert "- requires_human: no" in content


def test_add_task_requires_human_yes_when_autonomous_false(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    with patch.object(backlog_add, "BACKLOG_FILE", f):
        backlog_add.add_task("T", "D", "", autonomous=False)
    content = f.read_text(encoding="utf-8")
    assert "- requires_human: yes" in content


def test_add_task_sequential_ids(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    with patch.object(backlog_add, "BACKLOG_FILE", f):
        id1 = backlog_add.add_task("First", "D", "", autonomous=True)
        id2 = backlog_add.add_task("Second", "D", "", autonomous=True)
    assert id1 == "TASK-001"
    assert id2 == "TASK-002"


def test_add_task_returns_assigned_id(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    f.write_text("# H\n---\n### TASK-005\n- status: done\n", encoding="utf-8")
    with patch.object(backlog_add, "BACKLOG_FILE", f):
        task_id = backlog_add.add_task("New", "D", "", autonomous=True)
    assert task_id == "TASK-006"


# ---------------------------------------------------------------------------
# Contract test: add_task output is parseable by _parse_backlog
# ---------------------------------------------------------------------------


def test_add_then_parse_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "backlog.md"
    with (
        patch.object(backlog_add, "BACKLOG_FILE", f),
        patch.object(backlog_run, "BACKLOG_FILE", f),
    ):
        backlog_add.add_task(
            title="Roundtrip task",
            description="Check that add_task output is parseable.",
            context="scripts/",
            autonomous=True,
        )
        tasks = backlog_run._parse_backlog()

    assert len(tasks) == 1
    t = tasks[0]
    assert t["id"] == "TASK-001"
    assert t["status"] == "pending"
    assert t["requires_human"] == "no"
    assert t["title"] == "Roundtrip task"
    # After parse, _find_next_task must select it
    result = backlog_run._find_next_task(tasks)
    assert result is not None
    assert result["id"] == "TASK-001"
