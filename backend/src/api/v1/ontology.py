"""Ontology entity visibility API — list entities and publish/unpublish them."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import get_current_user
from ...models.database import get_db
from ...models.ontology import OntologyEntity
from ...models.user import User
from ...services.ingestion.ontology_visibility import (
    MAX_BULK_IDS,
    EntityNotFoundError,
    set_entity_visibility,
)

router = APIRouter(
    prefix="/api/v1/ontology",
    tags=["ontology"],
    dependencies=[Depends(get_current_user)],
)

# ── Pydantic schemas ──────────────────────────────────────────────────────────


class EntityItem(BaseModel):
    id: uuid.UUID
    entity_type: Literal["person", "project"]
    external_key: str
    visibility: Literal["public", "private"]


class EntityListData(BaseModel):
    entities: list[EntityItem]
    total: int


class EntityListResponse(BaseModel):
    data: EntityListData


class SetVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=MAX_BULK_IDS)
    visibility: Literal["public", "private"]


class SetVisibilityCounts(BaseModel):
    updated: int
    unchanged: int


class SetVisibilityResponse(BaseModel):
    data: SetVisibilityCounts


# ── Private query helpers ─────────────────────────────────────────────────────


async def _fetch_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    type_filter: Literal["person", "project"] | None,
    visibility_filter: Literal["public", "private"] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return ``(rows, total)`` for the user's entities matching the filters.

    Separating the query from the route handler keeps HTTP concerns (request
    parsing, response shaping) and data-access concerns (conditions, ordering,
    pagination) in distinct units.
    """
    conditions = [OntologyEntity.user_id == user_id]
    if type_filter is not None:
        conditions.append(OntologyEntity.entity_type == type_filter)
    if visibility_filter is not None:
        conditions.append(OntologyEntity.visibility == visibility_filter)

    total: int = (
        await db.scalar(
            select(func.count()).select_from(OntologyEntity).where(*conditions)
        )
        or 0
    )

    rows = (
        await db.execute(
            select(
                OntologyEntity.id,
                OntologyEntity.entity_type,
                OntologyEntity.external_key,
                OntologyEntity.visibility,
            )
            .where(*conditions)
            .order_by(OntologyEntity.entity_type, OntologyEntity.external_key)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    entities = [
        {
            "id": r.id,
            "entity_type": r.entity_type,
            "external_key": r.external_key,
            "visibility": r.visibility,
        }
        for r in rows
    ]
    return entities, total


# ── Route handlers ────────────────────────────────────────────────────────────


@router.get(
    "/entities", response_model=EntityListResponse, summary="List my ontology entities"
)
async def list_entities(
    entity_type: Literal["person", "project"] | None = Query(
        default=None, alias="type"
    ),
    visibility: Literal["public", "private"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    entities, total = await _fetch_entities(
        db, user.id, entity_type, visibility, limit, offset
    )
    return {"data": {"entities": entities, "total": total}}


@router.patch(
    "/entities/visibility",
    response_model=SetVisibilityResponse,
    summary="Publish or unpublish my ontology entities",
)
async def set_visibility(
    body: SetVisibilityRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await set_entity_visibility(db, user.id, body.ids, body.visibility)
    except EntityNotFoundError:
        await db.rollback()
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "entity_not_found",
                    "message": "One or more entities were not found.",
                    "details": {},
                }
            },
        ) from None
    await db.commit()
    return {"data": result}
