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
from src.schemas.ai_ecosystem import RegisterSkillRequest, SkillResponse

router = APIRouter(
    prefix="/api/v1/ai-ecosystem",
    tags=["ai-ecosystem"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/skills", summary="List all registered skills")
async def list_skills(db: AsyncSession = Depends(get_db)) -> dict:
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
    return {
        "data": [SkillResponse.model_validate(r).model_dump() for r in rows],
        "total": len(rows),
    }


@router.post(
    "/skills/register",
    summary="Register or update a skill in the ecosystem",
    status_code=201,
)
async def register_skill(
    body: RegisterSkillRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert a skill into the registry. Called automatically after every skill installation."""
    existing = await db.scalar(
        select(SkillRegistry).where(SkillRegistry.skill_name == body.skill_name)
    )
    if existing:
        existing.display_name = body.display_name
        existing.description = body.description
        existing.source_repo = body.source_repo
        existing.category = body.category
        action = "updated"
    else:
        db.add(
            SkillRegistry(
                id=uuid.uuid4(),
                skill_name=body.skill_name,
                display_name=body.display_name,
                description=body.description,
                source_repo=body.source_repo,
                category=body.category,
            )
        )
        action = "registered"
    await db.commit()
    return {"data": {"skill_name": body.skill_name, "action": action}}
