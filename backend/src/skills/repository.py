"""Data access for `skill_registry` — every SQL statement against
SkillRegistry lives here and nowhere else.

The same table used to be queried from two unrelated places that each
hand-rolled their own statements: the HTTP route (filters, paging and a
check-then-write upsert inline) and the seed script (a chunked
`INSERT ... ON CONFLICT`). Column lists, the ILIKE escaping rule and the
conflict target were duplicated across both.

Statement construction only — transaction boundaries belong to the caller
(`src.skills.service`), so a repository call can be composed into a larger
unit of work without committing someone else's half-finished write.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.skill import SkillRegistry

# Postgres caps a statement at 65535 bound parameters; at 5 columns per row a
# 500-row chunk stays an order of magnitude clear of that ceiling while still
# collapsing the ~1.3k-row manifest sync into a handful of round trips.
CHUNK_SIZE = 500

# Columns refreshed when an upsert hits an existing skill_name. `skill_name`
# is the conflict key and `id`/`created_at` are write-once, so neither is
# listed.
_UPSERT_FIELDS = ("display_name", "description", "source_repo", "category")


def _filters(category: str | None, q: str | None) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if category is not None:
        filters.append(SkillRegistry.category == category)
    if q:
        # LIKE wildcards in user input are escaped so a query of `100%`
        # searches for that literal text rather than matching every row.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                SkillRegistry.skill_name.ilike(pattern, escape="\\"),
                SkillRegistry.display_name.ilike(pattern, escape="\\"),
            )
        )
    return filters


async def list_page(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    category: str | None = None,
    q: str | None = None,
) -> tuple[Sequence[SkillRegistry], int]:
    """Return one page of skills plus the total row count for the same filters.

    Ordering matches ix_skill_registry_category_display_name so the composite
    index serves the ORDER BY (see migration n1k2l3m4a5b6); skill_name is the
    tiebreaker that makes paging deterministic when two skills share a
    category and display name.
    """
    filters = _filters(category, q)

    total = await db.scalar(
        select(func.count()).select_from(SkillRegistry).where(*filters)
    )
    rows = (
        await db.execute(
            select(SkillRegistry)
            .where(*filters)
            .order_by(
                SkillRegistry.category,
                SkillRegistry.display_name,
                SkillRegistry.skill_name,
            )
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return rows.all(), total or 0


async def get_by_name(db: AsyncSession, skill_name: str) -> SkillRegistry | None:
    return await db.scalar(
        select(SkillRegistry).where(SkillRegistry.skill_name == skill_name)
    )


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(SkillRegistry)) or 0


def add(db: AsyncSession, fields: dict[str, Any]) -> None:
    """Stage a new skill row. The caller commits."""
    db.add(SkillRegistry(**fields))


def apply_fields(skill: SkillRegistry, fields: dict[str, Any]) -> None:
    """Overwrite the mutable columns of an existing row. The caller commits."""
    for name in _UPSERT_FIELDS:
        setattr(skill, name, fields[name])


async def bulk_upsert(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """INSERT ... ON CONFLICT (skill_name) DO UPDATE, in bounded chunks.

    `updated_at` is set explicitly because `onupdate=` only fires for ORM-level
    updates, and this is a Core statement.
    """
    for i in range(0, len(rows), CHUNK_SIZE):
        stmt = pg_insert(SkillRegistry).values(rows[i : i + CHUNK_SIZE])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["skill_name"],
                set_={
                    **{name: getattr(stmt.excluded, name) for name in _UPSERT_FIELDS},
                    "updated_at": func.now(),
                },
            )
        )


async def delete_missing(db: AsyncSession, keep_names: Iterable[str]) -> int:
    """Delete every skill whose name is not in `keep_names`. Returns row count."""
    result = await db.execute(
        delete(SkillRegistry).where(SkillRegistry.skill_name.notin_(keep_names))
    )
    return result.rowcount or 0
