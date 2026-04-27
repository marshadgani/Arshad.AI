"""Filesystem helpers for dev-team artifacts.

Every agent output is written to:
    tasks/agent-outputs/<agent_dir>/<FEAT-NNN>_<timestamp>.json

Helpers:
    repo_root()       — absolute path to the repo root (search up from cwd)
    write_artifact()  — JSON-dumps a Pydantic model, returns the path
    log_pipeline_run() — append a row to tasks/pipeline-runs.md
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


def repo_root() -> Path:
    """Walk upward from this file's location until we find pyproject/render.yaml."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "render.yaml").exists() or (parent / ".git").exists():
            return parent
    # Fallback: assume repo layout is backend/src/dev_team/storage.py
    return here.parents[3]


def _ts_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_artifact(
    *,
    agent_dir: str,
    feature_id: str,
    payload: BaseModel,
    suffix: str = "",
) -> Path:
    """Write a Pydantic artifact to tasks/agent-outputs/<agent_dir>/.

    Returns the absolute Path. Suffix is inserted between feature_id and
    timestamp (e.g., 'pre' / 'post' for EA, 'iter1' for tester, etc.).
    """
    out_dir = repo_root() / "tasks" / "agent-outputs" / agent_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = [feature_id]
    if suffix:
        parts.append(suffix)
    parts.append(_ts_for_filename())
    filename = "_".join(parts) + ".json"
    path = out_dir / filename
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload.model_dump_json(indent=2))
    os.replace(tmp, path)
    return path


def relative_to_repo(path: Path) -> str:
    try:
        return str(path.relative_to(repo_root()))
    except ValueError:
        return str(path)


def log_pipeline_run_row(
    *,
    started: str,
    feature_id: str,
    requirement: str,
    status: str,
    bug_fix_iterations: int,
    ea_post_decision: str,
    duration_seconds: float,
) -> None:
    """Append one row to tasks/pipeline-runs.md (preserves existing rows)."""
    path = repo_root() / "tasks" / "pipeline-runs.md"
    if not path.exists():
        path.write_text(
            "# Pipeline Runs\n\nAppend-only log of every dev-team pipeline invocation.\n\n"
            "| Started | Feature ID | Requirement | Status | Bug-fix iterations | EA post-build | Duration |\n"
            "|---|---|---|---|---|---|---|\n"
        )
    # Markdown-safe — strip pipes from the requirement
    safe_req = requirement.replace("|", "/").strip()
    if len(safe_req) > 80:
        safe_req = safe_req[:77] + "..."
    row = (
        f"| {started} | {feature_id} | {safe_req} | {status} "
        f"| {bug_fix_iterations} | {ea_post_decision} | {duration_seconds:.1f}s |\n"
    )
    with path.open("a") as f:
        f.write(row)


def now_iso() -> str:
    return _ts_iso()
