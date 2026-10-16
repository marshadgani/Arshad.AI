"""AI Ecosystem usage ingest.

  POST /api/v1/ai-ecosystem/log   record one agent invocation

Lives in its own router because the rest of /ai-ecosystem is behind the user
JWT, while this route also accepts the dedicated ingest key a Claude Code hook
sends (see src/auth/usage_ingest.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.usage_ingest import require_usage_writer
from src.models.ai_ecosystem import AgentRegistry, AgentUsageLog
from src.models.database import get_db
from src.schemas.ai_ecosystem import LogRequest

router = APIRouter(
    prefix="/api/v1/ai-ecosystem",
    tags=["ai-ecosystem"],
    dependencies=[Depends(require_usage_writer)],
)

_DEFAULT_MODEL = "claude-sonnet-4-6"


@router.post("/log", summary="Record one agent invocation", status_code=201)
async def log_invocation(
    body: LogRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # An agent the registry has never seen (a built-in subagent type, or a new
    # .md file not yet registered) would be logged but never rendered, because
    # the page lists registry rows. ON CONFLICT keeps this safe when two hook
    # calls for the same new agent race.
    await db.execute(
        pg_insert(AgentRegistry)
        .values(
            id=uuid.uuid4(),
            agent_name=body.agent_name,
            display_name=body.agent_name.replace("-", " ").replace("_", " ").title(),
            purpose="Auto-registered from recorded usage.",
            model=body.model or _DEFAULT_MODEL,
            category="other",
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=["agent_name"])
    )

    entry = AgentUsageLog(
        id=uuid.uuid4(),
        agent_name=body.agent_name,
        model=body.model,
        tokens_used=body.tokens_used,
        duration_ms=body.duration_ms,
        success=body.success,
        session_id=body.session_id,
        invoked_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.commit()
    return {"data": {"id": str(entry.id)}}
