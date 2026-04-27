"""Atomic FEAT-NNN counter.

Reads `tasks/.feature-counter` (single int line), increments, writes back
atomically. Format: `FEAT-NNN` 3-digit minimum, expands naturally past 999.
"""

from __future__ import annotations

import os
from pathlib import Path

from .storage import repo_root

_COUNTER_FILE = "tasks/.feature-counter"


def _counter_path() -> Path:
    return repo_root() / _COUNTER_FILE


def next_feature_id() -> str:
    """Increment the on-disk counter and return the new FEAT-NNN string."""
    path = _counter_path()
    if not path.exists():
        path.write_text("0\n")
    current = int(path.read_text().strip() or "0")
    nxt = current + 1
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"{nxt}\n")
    os.replace(tmp, path)
    return format_feature_id(nxt)


def format_feature_id(n: int) -> str:
    return f"FEAT-{n:03d}" if n < 1000 else f"FEAT-{n}"


def slug_from_requirement(requirement: str, max_len: int = 32) -> str:
    """Cheap slug for branch names. Keeps a-z 0-9, replaces other → '-'."""
    cleaned: list[str] = []
    for ch in requirement.lower():
        if ch.isalnum():
            cleaned.append(ch)
        elif cleaned and cleaned[-1] != "-":
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    return slug[:max_len].rstrip("-") or "feature"
