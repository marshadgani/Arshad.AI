"""Deployment-wide project-integration lookups shared by the infra routes."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.integration import Integration
from src.services.integrations.state import ACTIVE_STATUSES


async def find_infra_integrations(
    user_id: str, db: AsyncSession
) -> tuple[Integration | None, Integration | None]:
    """The caller's Render and Supabase rows, else the shared deployment row.

    Project API-key integrations are stored with user_id NULL (one per
    deployment), the same predicate the integrations router uses. The caller's
    own row sorts first; another user's row can never match. Reads the stored
    snapshot only, never the API key and never the provider.

    Known limit: a shared (user_id NULL) row is visible to every signed-in
    user. That is safe while the login allowlist admits only the owner. Gate
    these rows behind a role before any second account is allowed.
    """
    rows = (
        await db.scalars(
            select(Integration)
            .where(
                Integration.slug.in_(("render", "supabase")),
                or_(
                    Integration.user_id == user_id,
                    Integration.user_id.is_(None),
                ),
                Integration.status.in_(ACTIVE_STATUSES),
            )
            .order_by(Integration.user_id.is_(None).asc(), Integration.id)
        )
    ).all()
    by_slug: dict[str, Integration] = {}
    for row in rows:
        by_slug.setdefault(row.slug, row)
    return by_slug.get("render"), by_slug.get("supabase")
