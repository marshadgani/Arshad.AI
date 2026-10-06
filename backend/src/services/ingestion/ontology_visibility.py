"""User-controlled visibility changes for ontology entities.

This is the only code path that sets ``app.allow_visibility_promotion``. The
GUC is set with ``is_local=true`` so it is scoped to the current transaction and
cleared by Postgres at COMMIT/ROLLBACK; it is never reset explicitly because the
relationship derivation in the same transaction needs it. Nothing here commits.
Entity external keys are never logged.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_BULK_IDS = 200


class EntityNotFoundError(LookupError):
    """One or more ids are not entities owned by the user.

    Deliberately identical for missing and foreign ids so the API cannot be
    used to probe for other users' entities. Carries no ids or keys.
    """


# Locks the requested entities AND their direct neighbours in id order. Without
# the neighbour locks, a concurrent demote of A and promote of B (edge A-B) can
# each miss the other's uncommitted change and leave a public edge on a private
# endpoint. Sorted acquisition keeps concurrent calls from deadlocking; under
# READ COMMITTED the waiter re-reads the committed state after the lock.
_LOCK_CLOSURE = text(
    "SELECT e.id FROM ontology_entities e WHERE e.user_id = :uid AND ("
    "e.id = ANY(:ids) "
    "OR e.id IN (SELECT r.target_entity_id FROM ontology_relationships r "
    "WHERE r.user_id = :uid AND r.source_entity_id = ANY(:ids)) "
    "OR e.id IN (SELECT r.source_entity_id FROM ontology_relationships r "
    "WHERE r.user_id = :uid AND r.target_entity_id = ANY(:ids))) "
    "ORDER BY e.id FOR UPDATE OF e"
)

_SET_PROMOTION_GUC = text(
    "SELECT set_config('app.allow_visibility_promotion', 'true', true)"
)

_UPDATE_ENTITIES = text(
    "UPDATE ontology_entities SET visibility = :target, updated_at = now() "
    "WHERE user_id = :uid AND id = ANY(:ids) AND visibility <> :target "
    "RETURNING id"
)

_PROMOTE_RELATIONSHIPS = text(
    "UPDATE ontology_relationships r SET visibility = 'public', updated_at = now() "
    "WHERE r.user_id = :uid AND r.visibility = 'private' "
    "AND (r.source_entity_id = ANY(:ids) OR r.target_entity_id = ANY(:ids)) "
    "AND EXISTS (SELECT 1 FROM ontology_entities s "
    "WHERE s.id = r.source_entity_id AND s.user_id = :uid AND s.visibility = 'public') "
    "AND EXISTS (SELECT 1 FROM ontology_entities t "
    "WHERE t.id = r.target_entity_id AND t.user_id = :uid AND t.visibility = 'public')"
)

_DEMOTE_RELATIONSHIPS = text(
    "UPDATE ontology_relationships SET visibility = 'private', updated_at = now() "
    "WHERE user_id = :uid AND visibility = 'public' "
    "AND (source_entity_id = ANY(:ids) OR target_entity_id = ANY(:ids))"
)


async def _derive_relationship_visibility(
    db: AsyncSession,
    user_id: uuid.UUID,
    changed_entity_ids: list[uuid.UUID],
    direction: Literal["promote", "demote"],
) -> int:
    """Promote edges whose endpoints are now both public; demote every edge
    touching a demoted entity. For 'promote' the caller must already have set
    the transaction-local GUC."""
    if not changed_entity_ids:
        return 0
    stmt = _PROMOTE_RELATIONSHIPS if direction == "promote" else _DEMOTE_RELATIONSHIPS
    result = await db.execute(stmt, {"uid": user_id, "ids": changed_entity_ids})
    return result.rowcount or 0


async def set_entity_visibility(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_ids: list[uuid.UUID],
    visibility: Literal["public", "private"],
) -> dict[str, int]:
    """Set visibility for the user's own entities; never commits.

    Raises ``EntityNotFoundError`` if any id is missing or not the user's
    (indistinguishable by design); ids already at the target count as
    ``unchanged``.
    """
    if visibility not in ("public", "private"):
        raise ValueError("visibility must be 'public' or 'private'")
    if len(entity_ids) > MAX_BULK_IDS:
        raise ValueError(f"at most {MAX_BULK_IDS} ids per call")
    unique_ids = list(dict.fromkeys(entity_ids))
    if not unique_ids:
        return {"updated": 0, "unchanged": 0}

    owned = {
        row[0]
        for row in (
            await db.execute(_LOCK_CLOSURE, {"uid": user_id, "ids": unique_ids})
        ).fetchall()
    }
    if not set(unique_ids) <= owned:
        logger.warning(
            "ontology visibility rejected user_id=%s requested=%d not_owned=%d",
            user_id,
            len(unique_ids),
            len(set(unique_ids) - owned),
        )
        raise EntityNotFoundError("one or more entities were not found")

    promote = visibility == "public"
    if promote:
        await db.execute(_SET_PROMOTION_GUC)

    result = await db.execute(
        _UPDATE_ENTITIES, {"uid": user_id, "ids": unique_ids, "target": visibility}
    )
    changed_count = len(result.fetchall())

    # Derive from every requested id, not only rows that changed, so an edge
    # left inconsistent with its endpoints is repaired and a demote can never
    # leave a public edge touching a private entity.
    await _derive_relationship_visibility(
        db, user_id, unique_ids, "promote" if promote else "demote"
    )

    logger.info(
        "ontology visibility change user_id=%s count=%d direction=%s",
        user_id,
        len(unique_ids),
        "promote" if promote else "demote",
    )
    return {
        "updated": changed_count,
        "unchanged": len(unique_ids) - changed_count,
    }
