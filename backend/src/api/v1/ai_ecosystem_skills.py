"""AI Ecosystem Skills API — skill registry endpoints.

Endpoints:
  GET  /api/v1/ai-ecosystem/skills           list all registered skills
  POST /api/v1/ai-ecosystem/skills/register  upsert a skill (idempotent)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.models.database import get_db
from src.models.skill import SkillRegistry
from src.schemas.ai_ecosystem import (
    RegisterSkillRequest,
    SkillListResponse,
    SkillRegisterResponse,
    SkillResponse,
)

router = APIRouter(
    prefix="/api/v1/ai-ecosystem",
    tags=["ai-ecosystem"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/skills",
    summary="List all registered skills",
    response_model=SkillListResponse,
)
async def list_skills(db: AsyncSession = Depends(get_db)) -> SkillListResponse:
    rows = (
        (
            await db.execute(
                select(SkillRegistry).order_by(
                    SkillRegistry.category,
                    SkillRegistry.display_name,
                )
            )
        )
        .scalars()
        .all()
    )
    skills = [SkillResponse.model_validate(r) for r in rows]
    return SkillListResponse(data=skills, total=len(skills))


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
    """Upsert a skill into the registry. Called automatically after every skill installation.

    Uses a single atomic INSERT .. ON CONFLICT DO UPDATE rather than a
    read-then-write (SELECT to check existence, then INSERT or UPDATE):
    the read-then-write form has a TOCTOU race under concurrent calls for
    the same skill_name (e.g. two skill-install hooks firing back to back)
    — both requests can see "no existing row", both attempt INSERT, and
    the second fails with an unhandled IntegrityError on the skill_name
    unique constraint instead of upserting. ON CONFLICT makes the whole
    operation a single statement the database resolves atomically.
    """
    existed = await db.scalar(
        select(SkillRegistry.id).where(SkillRegistry.skill_name == body.skill_name)
    )
    stmt = (
        pg_insert(SkillRegistry)
        .values(
            id=uuid.uuid4(),
            skill_name=body.skill_name,
            display_name=body.display_name,
            description=body.description,
            source_repo=body.source_repo,
            category=body.category,
        )
        .on_conflict_do_update(
            index_elements=[SkillRegistry.skill_name],
            set_={
                "display_name": body.display_name,
                "description": body.description,
                "source_repo": body.source_repo,
                "category": body.category,
                # onupdate= does not fire for Core INSERT..ON CONFLICT —
                # must be set explicitly. created_at is deliberately
                # absent so it survives every subsequent upsert.
                "updated_at": func.now(),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    return SkillRegisterResponse(
        skill_name=body.skill_name,
        action="updated" if existed else "registered",
    )
