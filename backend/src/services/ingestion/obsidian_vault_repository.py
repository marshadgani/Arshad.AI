"""Query layer for the Obsidian vault export — SQL only, no policy.

Every statement here filters ``visibility = 'public'`` as a bound predicate.
This is the query-layer half of the visibility invariant (the DB ratchet
trigger from FEAT-165 is the storage-layer half, the renderer's own check is
the third). Relationships are only returned when the relationship AND both of
its endpoint entities are public, so a public edge can never leak the key of
a private entity into a wikilink.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ...models.ontology import OntologyEntity, OntologyRelationship
from ...models.ontology_vocabulary import PUBLIC


async def fetch_public_entities(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    stmt = (
        select(
            OntologyEntity.id,
            OntologyEntity.entity_type,
            OntologyEntity.external_key,
            OntologyEntity.visibility,
        )
        .where(OntologyEntity.user_id == user_id, OntologyEntity.visibility == PUBLIC)
        .order_by(OntologyEntity.entity_type, OntologyEntity.external_key)
    )
    result = await db.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def fetch_public_relationships(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    src = aliased(OntologyEntity)
    dst = aliased(OntologyEntity)
    stmt = (
        select(
            src.external_key.label("source_key"),
            src.entity_type.label("source_type"),
            dst.external_key.label("target_key"),
            dst.entity_type.label("target_type"),
            OntologyRelationship.relationship_type.label("relationship_type"),
        )
        .select_from(OntologyRelationship)
        .join(
            src,
            (src.id == OntologyRelationship.source_entity_id)
            & (src.user_id == OntologyRelationship.user_id)
            & (src.visibility == PUBLIC),
        )
        .join(
            dst,
            (dst.id == OntologyRelationship.target_entity_id)
            & (dst.user_id == OntologyRelationship.user_id)
            & (dst.visibility == PUBLIC),
        )
        .where(
            OntologyRelationship.user_id == user_id,
            OntologyRelationship.visibility == PUBLIC,
        )
        .order_by(src.external_key, dst.external_key)
    )
    result = await db.execute(stmt)
    return [dict(row) for row in result.mappings().all()]
