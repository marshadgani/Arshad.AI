"""Backward-compatible re-export shim.

The implementation has moved to ``src.services.drive``. This module exists
solely so callers that already import from ``src.services.google_drive``
continue to work without any changes.

Prefer the package path for new code:

    from src.services.drive import DriveAuditService
"""

from __future__ import annotations

from src.services.drive import (  # noqa: F401
    DriveAuditResult,
    DriveAuditService,
    FileAuditResult,
    KnowledgeSuggestionsResult,
)

__all__ = [
    "DriveAuditService",
    "DriveAuditResult",
    "FileAuditResult",
    "KnowledgeSuggestionsResult",
]
