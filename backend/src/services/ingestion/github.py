"""GitHub activity ingestion runner.

Pulls issues + PRs for each repo in ``payload.repos`` (default empty —
caller must supply at least one). Both go into ingested_github_activity
keyed by (user_id, kind, provider_id) so issue#3 and pr#3 don't collide.

provider_id stored as ``"<repo>#<number>"`` so it's unique across repos
the user has linked. occurred_at = updated_at from GitHub.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ingested import IngestedGitHubActivity
from ...models.user import User
from ...tools.github.list_issues import GitHubListIssues, ListIssuesInput
from ...tools.github.list_prs import GitHubListPrs, ListPrsInput
from .. import event_bus
from .runner import IngestionError


def _max_batch() -> int:
    try:
        return max(1, int(os.getenv("MAX_INGEST_BATCH_SIZE", "100")))
    except ValueError:
        return 100


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    repos: list[str] = payload.get("repos") or []
    if not repos:
        raise IngestionError(
            "github_repos_required: payload.repos must list at least one owner/name"
        )

    state = "all" if payload.get("full_refresh") else "open"
    batch_size = _max_batch()

    issues_rows: list[dict[str, Any]] = []
    pr_rows: list[dict[str, Any]] = []

    for repo in repos:
        issues_result = await GitHubListIssues()(
            user=user,
            db=db,
            payload=ListIssuesInput(repo=repo, state=state, max_results=batch_size),
        )
        for item in issues_result.data:
            number = item.get("number")
            if number is None:
                continue
            issues_rows.append(
                {
                    "user_id": user.id,
                    "occurred_at": _parse_iso(item.get("updated_at")),
                    "provider_id": f"{repo}#{number}",
                    "kind": "issue",
                    "raw": item,
                }
            )

        prs_result = await GitHubListPrs()(
            user=user,
            db=db,
            payload=ListPrsInput(repo=repo, state=state, max_results=batch_size),
        )
        for item in prs_result.data:
            number = item.get("number")
            if number is None:
                continue
            pr_rows.append(
                {
                    "user_id": user.id,
                    "occurred_at": _parse_iso(item.get("updated_at")),
                    "provider_id": f"{repo}#{number}",
                    "kind": "pr",
                    "raw": item,
                }
            )

    now = datetime.now(timezone.utc)
    for rows in (issues_rows, pr_rows):
        if not rows:
            continue
        stmt = pg_insert(IngestedGitHubActivity).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "kind", "provider_id"],
            set_={
                "raw": stmt.excluded.raw,
                "occurred_at": stmt.excluded.occurred_at,
                "ingested_at": now,
            },
        )
        await db.execute(stmt)
    if issues_rows or pr_rows:
        await db.commit()

    await event_bus.publish(
        "events.github.ingested",
        {
            "user_id": str(user.id),
            "ingested_count": len(issues_rows) + len(pr_rows),
            "issue_count": len(issues_rows),
            "pr_count": len(pr_rows),
            "repos": repos,
        },
    )
    return {
        "ingested_count": len(issues_rows) + len(pr_rows),
        "issue_count": len(issues_rows),
        "pr_count": len(pr_rows),
    }
