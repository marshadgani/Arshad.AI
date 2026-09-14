"""Obsidian vault endpoints — sync, export, browse, create, and update notes.

This module is routing and wire shape only. The work it coordinates lives
in src/services/obsidian/: queue plumbing in jobs.py, browse queries in
notes_repository.py, the exportable-domain registry in domains.py. Response
shapes are in obsidian_serializers.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import get_current_user
from ...models.database import get_db
from ...models.user import User
from ...services.obsidian import jobs, notes_repository
from ...services.obsidian.domains import DOMAIN_NAMES
from ...tools.base import ToolError
from ..errors import http_error
from .obsidian_serializers import domain_export_status, note_full, note_summary

router = APIRouter(
    prefix="/api/v1/obsidian",
    tags=["obsidian"],
    dependencies=[Depends(get_current_user)],
)


# ── Sync (inbound: vault -> Arshad.AI) ─────────────────────────────


@router.post("/sync", summary="Trigger vault sync from GitHub")
async def trigger_sync(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job = await jobs.enqueue(db, user, jobs.INGEST_DAG_ID, {})
    return {"data": {"job_id": str(job.id), "status": "pending"}}


@router.get("/sync/status", summary="Latest sync job status")
async def sync_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job = await jobs.latest_job(db, user, jobs.INGEST_DAG_ID)
    return {"data": jobs.job_summary(job) if job else None}


# ── Export (outbound: Arshad.AI -> vault) ─────────────────────────


class TriggerExportRequest(BaseModel):
    domains: list[str] | None = None
    since: datetime | None = None


@router.post(
    "/export",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger outbound export of ingested records to the vault",
)
async def trigger_export(
    body: TriggerExportRequest = TriggerExportRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    domains = body.domains or list(DOMAIN_NAMES)
    invalid = [d for d in domains if d not in DOMAIN_NAMES]
    if invalid:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_domain",
            f"Unknown domain(s): {', '.join(invalid)}. "
            f"Valid domains: {', '.join(DOMAIN_NAMES)}.",
        )

    payload: dict[str, Any] = {"domains": domains}
    if body.since is not None:
        payload["since"] = body.since.isoformat()

    job = await jobs.enqueue(db, user, jobs.EXPORT_DAG_ID, payload)
    return {"data": {"job_id": str(job.id), "status": "pending", "domains": domains}}


@router.get("/export/status", summary="Per-domain export state for the current user")
async def export_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    by_domain = await notes_repository.export_state_by_domain(db, user)
    latest = await jobs.latest_job(db, user, jobs.EXPORT_DAG_ID)
    return {
        "data": {
            "domains": {
                name: domain_export_status(by_domain.get(name)) for name in DOMAIN_NAMES
            },
            "latest_job": jobs.job_summary(latest) if latest else None,
        }
    }


# ── Stats ──────────────────────────────────────────────────────────


@router.get("/stats", summary="Vault statistics")
async def stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"data": await notes_repository.vault_stats(db, user)}


# ── Notes list + search ────────────────────────────────────────────


@router.get("/notes", summary="List or search vault notes")
async def list_notes(
    q: str | None = None,
    tags: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if q and len(q) > 1000:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "query_too_long",
            "Search query must be ≤ 1000 characters.",
        )

    rows, total = await notes_repository.search_notes(db, user, q, tags, limit, offset)
    return {"data": {"notes": [note_summary(n) for n in rows], "total": total}}


# ── Single note ────────────────────────────────────────────────────


@router.get("/notes/{note_id}", summary="Get a single note")
async def get_note(
    note_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        note_uuid = uuid.UUID(note_id)
    except ValueError as exc:
        raise http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_id",
            "note_id must be a UUID.",
        ) from exc

    note = await notes_repository.get_note(db, user, note_uuid)
    if note is None:
        raise http_error(
            status.HTTP_404_NOT_FOUND, "note_not_found", f"No note with id '{note_id}'."
        )
    return {"data": note_full(note)}


# ── Create note ────────────────────────────────────────────────────


class CreateNoteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)


@router.post("/notes", status_code=status.HTTP_201_CREATED, summary="Create a new note")
async def create_note(
    body: CreateNoteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from ...tools.obsidian.create_note import CreateNoteInput, ObsidianCreateNote

    try:
        result = await ObsidianCreateNote()(
            user=user,
            db=db,
            payload=CreateNoteInput(path=body.path, content=body.content),
        )
    except ToolError as exc:
        raise http_error(status.HTTP_400_BAD_REQUEST, exc.code, exc.message) from exc
    return {"data": result.model_dump()}


# ── Update note ────────────────────────────────────────────────────


class UpdateNoteRequest(BaseModel):
    content: str = Field(max_length=500_000)


@router.patch("/notes/{note_id}", summary="Update a note's content")
async def update_note(
    note_id: str,
    body: UpdateNoteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from ...tools.obsidian.update_note import ObsidianUpdateNote, UpdateNoteInput

    try:
        result = await ObsidianUpdateNote()(
            user=user,
            db=db,
            payload=UpdateNoteInput(note_id=note_id, content=body.content),
        )
    except ToolError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "note_not_found"
            else status.HTTP_400_BAD_REQUEST
        )
        raise http_error(status_code, exc.code, exc.message) from exc
    return {"data": result.model_dump()}
