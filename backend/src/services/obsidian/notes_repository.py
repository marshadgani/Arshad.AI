"""Queries backing the vault-browsing endpoints.

Kept out of the router so the raw `text()` tsvector fragment — the one
place in this feature that isn't ORM-expressed — sits next to its bound
parameter rather than in the middle of a route handler.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import cast as sa_cast
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian import IngestedObsidianNote
from ...models.obsidian_export import ObsidianExportState
from ...models.user import User

_FTS_PREDICATE = (
    "to_tsvector('english', "
    "coalesce(title, '') || ' ' || coalesce(content, '')) "
    "@@ plainto_tsquery('english', :q)"
)


async def search_notes(
    db: AsyncSession,
    user: User,
    q: str | None,
    tags: str | None,
    limit: int,
    offset: int,
) -> tuple[list[IngestedObsidianNote], int]:
    """Returns (page_of_notes, total_matching)."""
    stmt = select(IngestedObsidianNote).where(IngestedObsidianNote.user_id == user.id)

    if q and q.strip():
        stmt = stmt.where(text(_FTS_PREDICATE).bindparams(q=q.strip()))

    if tags:
        for tag in (t.strip() for t in tags.split(",") if t.strip()):
            # json.dumps escapes; sa_cast gives Postgres the right JSONB type.
            stmt = stmt.where(
                IngestedObsidianNote.tags.op("@>")(sa_cast(json.dumps([tag]), JSONB))
            )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    page = (
        stmt.order_by(IngestedObsidianNote.last_modified_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(await db.scalars(page)), total


async def get_note(
    db: AsyncSession, user: User, note_id: uuid.UUID
) -> IngestedObsidianNote | None:
    return await db.scalar(
        select(IngestedObsidianNote).where(
            IngestedObsidianNote.id == note_id,
            IngestedObsidianNote.user_id == user.id,
        )
    )


async def vault_stats(db: AsyncSession, user: User) -> dict[str, Any]:
    total_notes = await db.scalar(
        select(func.count()).where(IngestedObsidianNote.user_id == user.id)
    )
    total_words = await db.scalar(
        select(func.sum(IngestedObsidianNote.word_count)).where(
            IngestedObsidianNote.user_id == user.id
        )
    )
    last_sync = await db.scalar(
        select(IngestedObsidianNote.ingested_at)
        .where(IngestedObsidianNote.user_id == user.id)
        .order_by(IngestedObsidianNote.ingested_at.desc())
        .limit(1)
    )
    return {
        "total_notes": total_notes or 0,
        "total_words": total_words or 0,
        "last_synced_at": last_sync.isoformat() if last_sync else None,
    }


async def export_state_by_domain(
    db: AsyncSession, user: User
) -> dict[str, ObsidianExportState]:
    rows = await db.scalars(
        select(ObsidianExportState).where(ObsidianExportState.user_id == user.id)
    )
    return {row.domain: row for row in rows}


__all__ = ["export_state_by_domain", "get_note", "search_notes", "vault_stats"]
