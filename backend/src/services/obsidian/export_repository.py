"""Database access for the outbound exporter.

Every SELECT, INSERT and watermark mutation the export run performs is
here; export_service.py performs none of its own, so the orchestrator
reads as a sequence of decisions rather than a sequence of queries.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian_export import ObsidianExportedNote, ObsidianExportState
from ...models.user import User
from .domains import ExportDomain
from .export_planner import NotePlan


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_or_create_state(
    db: AsyncSession, user: User, domain: str
) -> ObsidianExportState:
    state = await db.scalar(
        select(ObsidianExportState).where(
            ObsidianExportState.user_id == user.id,
            ObsidianExportState.domain == domain,
        )
    )
    if state is None:
        state = ObsidianExportState(
            id=uuid.uuid4(), user_id=user.id, domain=domain, notes_written=0
        )
        db.add(state)
        await db.flush()
    return state


async def fetch_watermarked_rows(
    db: AsyncSession,
    user: User,
    domain: ExportDomain,
    watermark_ts: datetime | None,
    watermark_id: uuid.UUID | None,
    limit: int,
) -> list[Any]:
    """Rows after the (ingested_at, id) watermark, oldest first.

    Fetches `limit + 1` so the caller can detect that more remain without
    a second COUNT query.
    """
    model = domain.model
    stmt = select(model).where(model.user_id == user.id)
    if watermark_ts is not None:
        if watermark_id is not None:
            stmt = stmt.where(
                (model.ingested_at > watermark_ts)
                | ((model.ingested_at == watermark_ts) & (model.id > watermark_id))
            )
        else:
            stmt = stmt.where(model.ingested_at > watermark_ts)
    stmt = stmt.order_by(model.ingested_at.asc(), model.id.asc()).limit(limit + 1)
    return list(await db.scalars(stmt))


async def fetch_existing_exported(
    db: AsyncSession, user: User, paths: list[str]
) -> dict[str, ObsidianExportedNote]:
    """One batched lookup of every ObsidianExportedNote this run could touch.

    Must stay a single `github_path IN (...)` query: a per-note lookup
    here costs up to 2 * MAX_NOTES_PER_RUN * len(domains) round trips
    (~3,000 on a full 3-domain, 500-note-per-domain run).
    """
    if not paths:
        return {}
    rows = await db.scalars(
        select(ObsidianExportedNote).where(
            ObsidianExportedNote.user_id == user.id,
            ObsidianExportedNote.github_path.in_(paths),
        )
    )
    return {row.github_path: row for row in rows}


def stage_ledger(
    db: AsyncSession,
    user: User,
    domain: ExportDomain,
    plans: list[NotePlan],
    commit_sha: str,
    now: datetime,
) -> list[ObsidianExportedNote]:
    """Apply a previously-built export plan to the session.

    Only called after the vault write (create_commit_batch) has
    succeeded — commit_sha is real by the time this runs, so a note is
    never recorded as exported before it's actually in the vault.

    Returns only the notes this run actually wrote. Unchanged notes are
    left alone: re-stamping them would overwrite the commit_sha that
    genuinely produced them (with "" on a run that committed nothing at
    all, since commit_sha is empty when `files` is empty) and would
    inflate ObsidianExportState.notes_written on every no-op run.
    """
    written: list[ObsidianExportedNote] = []
    for plan in plans:
        if not plan.changed:
            continue
        if plan.existing is not None:
            plan.existing.content_hash = plan.content_hash
            plan.existing.source_row_id = plan.row_id
            plan.existing.exported_at = now
            plan.existing.commit_sha = commit_sha
            written.append(plan.existing)
        else:
            new_row = ObsidianExportedNote(
                id=uuid.uuid4(),
                user_id=user.id,
                github_path=plan.path,
                domain=domain.name,
                source_table=domain.source_table,
                source_row_id=plan.row_id,
                content_hash=plan.content_hash,
                commit_sha=commit_sha,
                exported_at=now,
            )
            db.add(new_row)
            written.append(new_row)
    return written


def advance_watermark(
    state: ObsidianExportState,
    new_ts: datetime | None,
    new_id: uuid.UUID | None,
) -> None:
    """Move the watermark forward, never backward.

    A caller-supplied `since` older than the stored watermark (a targeted
    backfill) would otherwise rewind it, making every later scheduled run
    re-scan history it had already passed — the one thing
    ObsidianExportState.last_exported_at is documented never to do.
    """
    prev_ts = as_utc(state.last_exported_at)
    if new_ts is not None and (prev_ts is None or new_ts >= prev_ts):
        state.last_exported_at = new_ts
        state.last_exported_id = new_id


__all__ = [
    "advance_watermark",
    "as_utc",
    "fetch_existing_exported",
    "fetch_watermarked_rows",
    "get_or_create_state",
    "stage_ledger",
]
