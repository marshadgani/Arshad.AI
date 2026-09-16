#!/usr/bin/env python3
"""CLI: trigger an ontology_extractor run.

Inserts one ``dag_trigger_queue`` row with ``dag_id='ontology_extractor'``,
mirroring ``backend/src/api/v1/obsidian.py``'s ``POST /sync`` insert
pattern. No HTTP router, no frontend affordance — a CLI script inserting
a queue row is sufficient for this slice.

Usage:
    python scripts/ontology_extract.py [--user-id UUID]

User resolution order: --user-id arg -> ONTOLOGY_USER_ID env var ->
exactly-one-row-in-users shortcut (prints which user was auto-selected
before committing) -> otherwise exits non-zero asking for --user-id.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
)

from sqlalchemy import select  # noqa: E402
from src.models.dag_trigger import DagTriggerQueue  # noqa: E402
from src.models.database import AsyncSessionLocal  # noqa: E402
from src.models.user import User  # noqa: E402


async def _resolve_user_id(explicit: str | None) -> uuid.UUID:
    if explicit:
        return uuid.UUID(explicit)

    env_value = os.getenv("ONTOLOGY_USER_ID")
    if env_value:
        return uuid.UUID(env_value)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.id, User.email))
        rows = result.all()

    if len(rows) == 1:
        user_id, email = rows[0]
        print(f"Auto-selected user: {user_id} ({email})")
        return user_id

    print(
        "Cannot resolve target user: pass --user-id, set ONTOLOGY_USER_ID, "
        "or ensure exactly one row exists in the users table.",
        file=sys.stderr,
    )
    sys.exit(2)


async def _insert_job(user_id: uuid.UUID) -> uuid.UUID:
    job = DagTriggerQueue(
        id=uuid.uuid4(),
        dag_id="ontology_extractor",
        user_id=user_id,
        payload={},
        status="pending",
        requested_at=datetime.now(timezone.utc),
    )
    async with AsyncSessionLocal() as db:
        db.add(job)
        await db.commit()
    return job.id


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default=None, help="Target user UUID")
    args = parser.parse_args()

    user_id = await _resolve_user_id(args.user_id)
    job_id = await _insert_job(user_id)
    print(job_id)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
