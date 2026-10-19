"""Internal result dataclasses for the Drive service.

These are service-layer types, not HTTP response schemas.
The schemas in src/schemas/drive.py are the HTTP boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FileAuditResult:
    id: str
    name: str
    web_view_link: str
    modified_time: str
    anyone_with_link: bool | None
    stale_sharing: bool | None
    permissions_visible: bool


@dataclass
class DriveAuditResult:
    files: list[FileAuditResult] = field(default_factory=list)
    total: int = 0
    connected: bool = False
    needs_reauth: bool = False
    truncated: bool = False
    partial_failures: list[str] = field(default_factory=list)


@dataclass
class KnowledgeSuggestionsResult:
    names: list[str] = field(default_factory=list)
    total: int = 0
    connected: bool = False
    needs_reauth: bool = False
    truncated: bool = False
    partial_failures: list[str] = field(default_factory=list)
