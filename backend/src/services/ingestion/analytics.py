"""Analytics processor — aggregates ingested_* tables into metrics.

Computes per-user, per-window metrics and upserts into
``ingested_analytics_summary`` keyed by (user_id, metric_key, occurred_at).
``occurred_at`` is the END of the analysis window so time-series queries
can ORDER BY it.

Metrics computed (Phase F starter set):
  - calendar_events_count   — events whose occurred_at falls in the window
  - gmail_threads_count     — threads ingested in the window
  - github_issues_open      — issues with kind='issue' and raw.state='open' in window
  - github_prs_open         — PRs with kind='pr' and raw.state='open' in window
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ingested import (
    IngestedAnalyticsSummary,
    IngestedCalendarEvent,
    IngestedGitHubActivity,
    IngestedGmailThread,
)
from ...models.user import User
from .. import event_bus

_DEFAULT_WINDOW_DAYS = 7


async def compute(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    window_days = int(payload.get("window_days", _DEFAULT_WINDOW_DAYS))
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)
    window_end = now

    metrics: dict[str, Decimal] = {}

    metrics["calendar_events_count"] = Decimal(
        await db.scalar(
            select(func.count())
            .select_from(IngestedCalendarEvent)
            .where(
                IngestedCalendarEvent.user_id == user.id,
                IngestedCalendarEvent.occurred_at >= window_start,
                IngestedCalendarEvent.occurred_at < window_end,
            )
        )
        or 0
    )

    metrics["gmail_threads_count"] = Decimal(
        await db.scalar(
            select(func.count())
            .select_from(IngestedGmailThread)
            .where(
                IngestedGmailThread.user_id == user.id,
                IngestedGmailThread.ingested_at >= window_start,
                IngestedGmailThread.ingested_at < window_end,
            )
        )
        or 0
    )

    for kind, key in (("issue", "github_issues_open"), ("pr", "github_prs_open")):
        metrics[key] = Decimal(
            await db.scalar(
                select(func.count())
                .select_from(IngestedGitHubActivity)
                .where(
                    and_(
                        IngestedGitHubActivity.user_id == user.id,
                        IngestedGitHubActivity.kind == kind,
                        IngestedGitHubActivity.raw["state"].astext == "open",
                        IngestedGitHubActivity.occurred_at >= window_start,
                        IngestedGitHubActivity.occurred_at < window_end,
                    )
                )
            )
            or 0
        )

    rows = [
        {
            "user_id": user.id,
            "occurred_at": window_end,
            "metric_key": key,
            "metric_value": value,
            "raw": {
                "window_start": window_start.isoformat(),
                "window_days": window_days,
            },
        }
        for key, value in metrics.items()
    ]
    if rows:
        stmt = pg_insert(IngestedAnalyticsSummary).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "metric_key", "occurred_at"],
            set_={
                "metric_value": stmt.excluded.metric_value,
                "raw": stmt.excluded.raw,
                "ingested_at": now,
            },
        )
        await db.execute(stmt)
        await db.commit()

    await event_bus.publish(
        "events.analytics.computed",
        {
            "user_id": str(user.id),
            "metric_count": len(metrics),
            "window_days": window_days,
        },
    )
    return {
        "metric_count": len(metrics),
        "window_days": window_days,
        "metrics": {k: int(v) for k, v in metrics.items()},
    }
