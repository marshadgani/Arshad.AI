"""AI Ecosystem Skills API — HTTP adapter over the skill registry.

Endpoints:
  GET  /api/v1/ai-ecosystem/skills           list all registered skills
  POST /api/v1/ai-ecosystem/skills/register  upsert a skill (idempotent)

This module is deliberately thin: request validation, status codes and
response shaping only. Query construction lives in `src.skills.repository`
and the upsert rule in `src.skills.service`, so the same behaviour is
reachable from the startup sync and from scripts without going through HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models.database import get_db
from src.schemas.ai_ecosystem import (
    RegisterSkillRequest,
    SkillCategory,
    SkillListResponse,
    SkillRegisterResponse,
    SkillResponse,
)
from src.skills import repository, service

router = APIRouter(
    prefix="/api/v1/ai-ecosystem",
    tags=["ai-ecosystem"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/skills",
    summary="List registered skills (paginated, filterable, searchable)",
    response_model=SkillListResponse,
)
async def list_skills(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: SkillCategory | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> SkillListResponse:
    rows, total = await repository.list_page(
        db, limit=limit, offset=offset, category=category, q=q
    )
    return SkillListResponse(
        data=[SkillResponse.model_validate(r) for r in rows], total=total
    )


@router.post(
    "/skills/register",
    summary="Register or update a skill in the ecosystem",
    status_code=201,
    response_model=SkillRegisterResponse,
)
async def register_skill(
    body: RegisterSkillRequest,
    db: AsyncSession = Depends(get_db),
) -> SkillRegisterResponse:
    """Upsert a skill into the registry. Called after every skill installation."""
    action = await service.register_skill(db, body)
    return SkillRegisterResponse(skill_name=body.skill_name, action=action)
