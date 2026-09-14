"""Skill registry use cases: register one skill, converge all of them.

Both write paths into `skill_registry` live here so they share one rule —
registration is an idempotent upsert keyed on `skill_name`. Previously the
HTTP route and the startup sync each implemented that rule their own way.

This module owns the transaction boundaries (each function documents whether
it commits) and the operational policy (mass-delete guard, never-raise-on-sync).
It knows nothing about HTTP, so the same use case is reachable from a route,
a script, a deploy hook or a test.
"""

from __future__ import annotations

import logging
from typing import Literal, Protocol, TypedDict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.skills import repository
from src.skills.manifest import load_manifest

log = logging.getLogger(__name__)

RegisterAction = Literal["registered", "updated"]

# A sync that would remove more than half the registry is treated as a
# corrupt/partial manifest rather than a legitimate mass-uninstall: upserts
# still apply, deletions are skipped, and a human gets an ERROR line. Losing
# the whole Skills tab to a truncated build artifact is far worse than
# briefly keeping a few stale rows.
MASS_DELETE_GUARD_RATIO = 0.5


class SkillFields(Protocol):
    """Structural type for anything carrying a skill's writable columns.

    A Protocol rather than an import of `RegisterSkillRequest` keeps the
    domain layer from depending on the HTTP schema layer: the route can pass
    its Pydantic body straight through, and a script can pass any object with
    the same attributes, without either becoming the other's dependency.
    """

    skill_name: str
    display_name: str
    description: str
    source_repo: str
    category: str


class SkillSyncStats(TypedDict):
    registered: int
    deleted: int


async def register_skill(db: AsyncSession, payload: SkillFields) -> RegisterAction:
    """Upsert one skill. Returns whether the row was created or refreshed.

    The check-then-write below (SELECT, then INSERT or UPDATE) is not atomic:
    two concurrent registrations of the same brand-new skill_name (e.g. the
    weekly skill sync and a manual /fetch-github-repo run racing each other)
    can both see no existing row and both attempt an INSERT, so the loser
    hits the unique constraint on skill_name. Rather than surface that as an
    unhandled 500 (leaking a raw SQL/asyncpg error to the client, which
    api.md forbids), treat it as the expected "someone else just registered
    this" case and fall back to an UPDATE.
    """
    fields = {
        "skill_name": payload.skill_name,
        "display_name": payload.display_name,
        "description": payload.description,
        "source_repo": payload.source_repo,
        "category": payload.category,
    }

    existing = await repository.get_by_name(db, payload.skill_name)
    if existing is None:
        repository.add(db, fields)
        try:
            await db.commit()
            return "registered"
        except IntegrityError:
            await db.rollback()
            existing = await repository.get_by_name(db, payload.skill_name)
            if existing is None:
                raise  # conflict wasn't on skill_name after all — a real error

    repository.apply_fields(existing, fields)
    await db.commit()
    return "updated"


async def sync_from_manifest(db: AsyncSession) -> SkillSyncStats:
    """Converge `skill_registry` to the committed manifest.

    Called on every container start / deploy so the AI Ecosystem Skills tab
    reflects what is actually on disk without manual intervention. Never
    raises and never commits: a skills-sync failure must not block startup,
    and the caller decides when the surrounding unit of work lands.

    `load_manifest()` does blocking file I/O. Today's only caller
    (`scripts/seed_from_mock.py`) runs in its own short-lived process ahead
    of `uvicorn` starting, so there is no shared event loop to stall — but
    this function is also the one documented entry point for a future
    request-scoped "resync skills" admin action, and blocking the loop from
    inside a request handler would stall every other in-flight request on
    this worker for the duration of the read. `asyncio.to_thread` keeps the
    read off the event loop unconditionally rather than relying on callers
    to remember which context is safe.
    """
    rows = await asyncio.to_thread(load_manifest)
    if rows is None:
        return {"registered": 0, "deleted": 0}

    try:
        manifest_names = {r["skill_name"] for r in rows}
        await repository.bulk_upsert(db, rows)

        existing_count = await repository.count(db)
        if existing_count and (
            len(manifest_names) < existing_count * MASS_DELETE_GUARD_RATIO
        ):
            log.error(
                "refusing mass-delete of skill_registry: manifest=%d existing=%d "
                "— upserts applied, deletion skipped",
                len(manifest_names),
                existing_count,
            )
            deleted = 0
        else:
            deleted = await repository.delete_missing(db, manifest_names)

        return {"registered": len(rows), "deleted": deleted}
    except Exception:
        log.exception("skills sync failed — rolling back partial writes")
        # bulk_upsert/count/delete_missing may have already sent statements
        # on this session before the failure. Without a rollback the
        # transaction is left aborted (Postgres refuses further commands
        # until ROLLBACK), so the caller's subsequent `await session.commit()`
        # raises an unrelated-looking error instead of the real cause above —
        # and, since this function documents "never raises", that crash would
        # escape uncaught up through the seed script.
        await db.rollback()
        return {"registered": 0, "deleted": 0}
