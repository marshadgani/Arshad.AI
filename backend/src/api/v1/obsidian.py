"""Obsidian vault API — sync, browse, create, and update notes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import get_current_user
from ...models.dag_trigger import DagTriggerQueue
from ...models.database import get_db
from ...models.obsidian import IngestedObsidianNote
from ...models.user import User
from ...tools.base import ToolError

router = APIRouter(
    prefix="/api/v1/obsidian",
    tags=["obsidian"],
    dependencies=[Depends(get_current_user)],
)


def _err(code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"error": {"code": error_code, "message": message, "details": {}}},
    )


# ── Sync ───────────────────────────────────────────────────────────


@router.post("/sync", summary="Trigger vault sync from GitHub")
async def trigger_sync(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job = DagTriggerQueue(
        id=uuid.uuid4(),
        dag_id="obsidian_ingestor",
        user_id=user.id,
        payload={},
        status="pending",
        requested_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    return {"data": {"job_id": str(job.id), "status": "pending"}}


@router.get("/sync/status", summary="Latest sync job status")
async def sync_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(DagTriggerQueue)
        .where(
            DagTriggerQueue.user_id == user.id,
            DagTriggerQueue.dag_id == "obsidian_ingestor",
        )
        .order_by(DagTriggerQueue.requested_at.desc())
        .limit(1)
    )
    if row is None:
        return {"data": None}
    return {
        "data": {
            "job_id": str(row.id),
            "status": row.status,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "error": row.error_text,
        }
    }


# ── Stats ──────────────────────────────────────────────────────────


@router.get("/stats", summary="Vault statistics")
async def stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    total_notes = await db.scalar(
        select(func.count()).where(IngestedObsidianNote.user_id == user.id)
    )
    total_words = await db.scalar(
        select(func.sum(IngestedObsidianNote.word_count)).where(
            IngestedObsidianNote.user_id == user.id
        )
    )
    last_sync_row = await db.scalar(
        select(IngestedObsidianNote.ingested_at)
        .where(IngestedObsidianNote.user_id == user.id)
        .order_by(IngestedObsidianNote.ingested_at.desc())
        .limit(1)
    )
    return {
        "data": {
            "total_notes": total_notes or 0,
            "total_words": total_words or 0,
            "last_synced_at": last_sync_row.isoformat() if last_sync_row else None,
        }
    }


# ── Notes list + search ────────────────────────────────────────────


@router.get("/notes", summary="List or search vault notes")
async def list_notes(
    q: str | None = None,
    tags: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if limit > 100:
        limit = 100

    stmt = select(IngestedObsidianNote).where(IngestedObsidianNote.user_id == user.id)

    if q and q.strip():
        stmt = stmt.where(
            text(
                "to_tsvector('english', "
                "coalesce(title, '') || ' ' || coalesce(content, '')) "
                "@@ plainto_tsquery('english', :q)"
            ).bindparams(q=q.strip())
        )

    if tags:
        for tag in (t.strip() for t in tags.split(",") if t.strip()):
            stmt = stmt.where(
                IngestedObsidianNote.tags.op("@>")(func.cast(f'["{tag}"]', type_=None))
            )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt) or 0

    stmt = (
        stmt.order_by(IngestedObsidianNote.last_modified_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "data": [_note_summary(n) for n in rows],
        "total": total,
    }


# ── Single note ────────────────────────────────────────────────────


@router.get("/notes/{note_id}", summary="Get a single note")
async def get_note(
    note_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        note_uuid = uuid.UUID(note_id)
    except ValueError:
        raise _err(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_id",
            "note_id must be a UUID.",
        )

    note = await db.scalar(
        select(IngestedObsidianNote).where(
            IngestedObsidianNote.id == note_uuid,
            IngestedObsidianNote.user_id == user.id,
        )
    )
    if note is None:
        raise _err(
            status.HTTP_404_NOT_FOUND, "note_not_found", f"No note with id '{note_id}'."
        )
    return {"data": _note_full(note)}


# ── Create note ────────────────────────────────────────────────────


class CreateNoteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str


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
        raise _err(status.HTTP_400_BAD_REQUEST, exc.code, exc.message)
    return {"data": result.model_dump()}


# ── Update note ────────────────────────────────────────────────────


class UpdateNoteRequest(BaseModel):
    content: str


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
        raise _err(status_code, exc.code, exc.message)
    return {"data": result.model_dump()}


# ── Serialisers ────────────────────────────────────────────────────


def _note_summary(note: IngestedObsidianNote) -> dict[str, Any]:
    return {
        "id": str(note.id),
        "title": note.title,
        "path": note.github_path,
        "excerpt": note.content[:200].strip(),
        "tags": note.tags if isinstance(note.tags, list) else [],
        "word_count": note.word_count,
        "last_modified_at": note.last_modified_at.isoformat(),
    }


def _note_full(note: IngestedObsidianNote) -> dict[str, Any]:
    return {
        **_note_summary(note),
        "content": note.content,
        "frontmatter": note.frontmatter,
        "blob_sha": note.blob_sha,
        "ingested_at": note.ingested_at.isoformat(),
    }
