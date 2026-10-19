"""Response models for the Drive permissions audit and knowledge suggestions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DriveFile(BaseModel):
    id: str
    name: str
    web_view_link: str
    modified_time: str
    anyone_with_link: bool | None = Field(
        None, description="None means Drive did not return permissions (unknown)."
    )
    stale_sharing: bool | None = Field(
        None, description="None means Drive did not return permissions (unknown)."
    )
    permissions_visible: bool


class DriveAuditResponse(BaseModel):
    data: list[DriveFile]
    total: int
    connected: bool
    needs_reauth: bool
    truncated: bool
    partial_failures: list[str]


class KnowledgeSuggestionsResponse(BaseModel):
    data: list[str]
    total: int
    connected: bool
    needs_reauth: bool
    truncated: bool
    partial_failures: list[str]
