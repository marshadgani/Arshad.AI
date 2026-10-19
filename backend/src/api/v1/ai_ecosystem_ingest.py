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
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.usage_ingest import require_usage_writer
from src.middleware.rate_limit import enforce_rate_limit
from src.models.ai_ecosystem import AgentRegistry, AgentUsageLog
from src.models.database import get_db
from src.schemas.ai_ecosystem import LogRequest

router = APIRouter(
    prefix="/api/v1/ai-ecosystem",
    tags=["ai-ecosystem"],
    dependencies=[Depends(require_usage_writer)],
)

_DEFAULT_MODEL = "claude-sonnet-4-6"
AUTO_REGISTER_PURPOSE = "Auto-registered from recorded usage."
# Bounds how many registry rows a leaked key could create by inventing names.
MAX_AUTO_REGISTERED_AGENTS = 100
# One subagent run is one request. A busy pipeline stays far below this.
_RATE_LIMIT = 300
_RATE_WINDOW_SECONDS = 60


async def _register_if_unknown(body: LogRequest, db: AsyncSession) -> None:
    """Add a registry row for an agent the page has never seen.

    An agent missing from the registry would be logged but never rendered,
    because the page lists registry rows. ON CONFLICT keeps this safe when
    two hook calls for the same new agent race. Rows stay is_active so they
    show on the page. The cap above is what limits registry flooding.
    """
    auto_count = await db.scalar(
        select(func.count())
        .select_from(AgentRegistry)
        .where(AgentRegistry.purpose == AUTO_REGISTER_PURPOSE)
    )
    if (auto_count or 0) >= MAX_AUTO_REGISTERED_AGENTS:
        return
    await db.execute(
        pg_insert(AgentRegistry)
        .values(
            id=uuid.uuid4(),
            agent_name=body.agent_name,
            display_name=body.agent_name.replace("-", " ").replace("_", " ").title(),
            purpose=AUTO_REGISTER_PURPOSE,
            model=body.model or _DEFAULT_MODEL,
            category="other",
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=["agent_name"])
    )


@router.post("/log", summary="Record one agent invocation", status_code=201)
async def log_invocation(
    body: LogRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await enforce_rate_limit(
        bucket="usage_ingest",
        identity="global",
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
        message="Too many usage log requests. Retry in a minute.",
    )
    await _register_if_unknown(body, db)

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
