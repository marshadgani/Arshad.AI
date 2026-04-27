"""Developer agent — generates feature code from the SDD.

Validates every output file path against the path denylist BEFORE handing
back to the pipeline. Bad paths cause the pipeline to halt.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel

from ..artifacts import SDD, FeatureCode
from .base import DevAgent

# Denylist patterns. A path matches if any pattern is a prefix or
# fnmatch-style glob match.
_DENIED_PATHS = (
    "backend/src/main.py",
    "backend/src/auth/",
    "backend/alembic/env.py",
    ".github/workflows/",
    "render.yaml",
    "vercel.json",
    "Dockerfile",
    "CLAUDE.md",
    "tasks/process-hierarchy.md",
    "tasks/last-gate-report.md",
    "tasks/lessons.md",
    "tasks/.feature-counter",
)


def is_path_allowed(rel_path: str) -> tuple[bool, str | None]:
    """Returns (allowed, denial_reason). Reason is None on success."""
    if not rel_path:
        return False, "empty path"
    p = PurePosixPath(rel_path)
    if p.is_absolute():
        return False, "absolute paths are forbidden"
    if ".." in p.parts:
        return False, "'..' in path is forbidden"
    norm = p.as_posix()
    for denied in _DENIED_PATHS:
        if norm == denied or norm.startswith(denied):
            return False, f"path matches denylist: {denied}"
    # Allow new alembic migrations under versions/, but only NEW files —
    # the orchestrator double-checks no clobber.
    return True, None


class DevRequest(BaseModel):
    sdd: SDD


class Developer(DevAgent):
    name = "dev"
    output_dir = "dev"
    input_schema = DevRequest
    output_schema = FeatureCode
    prompt_file = "developer.md"
