#!/usr/bin/env python3
"""One-off remediation for credentials orphaned by the pre-FEAT-156 bug.

Before FEAT-156, IntegrationProvider.disconnect()'s default only flipped
Integration.status — every provider that relied on the default left a
live, encrypted-at-rest credential (an OAuth token, an API key) in
Postgres for every integration a user had already "disconnected" prior
to the fix shipping. This script finds and scrubs those pre-existing
orphans; it is not part of the ongoing disconnect() code path, which is
now correct by itself for every disconnect from this point forward.

Usage (run from repo root, with DATABASE_URL pointed at the target DB):

    python3 scripts/scrub_orphaned_integration_credentials.py    # dry-run (default)
    python3 scripts/scrub_orphaned_integration_credentials.py \
        --apply                                                 # actually scrub

Idempotent — safe to re-run. Logs row counts only, never credential
material. Not wired into any schedule; run once per environment after
deploying FEAT-156.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_SRC))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)
from src.models.integration import Integration  # noqa: E402
from src.services.integration_credentials import (  # noqa: E402
    count_live_credentials,
    scrub_credentials,
)

# Every integration the user has already "disconnected" — under the old
# default that flipped `status` and nothing else, precisely the set whose
# credentials were left live.
DISCONNECTED_INTEGRATION_IDS = select(Integration.id).where(
    Integration.status == "disconnected"
)


async def scrub(apply: bool) -> None:
    """Report — and optionally clear — credentials left on disconnected rows.

    Which tables count as credentials and how each is cleared is not
    decided here: it comes from src/services/integration_credentials.py,
    the same module the live disconnect path uses. That shared dependency is
    the point of this script's shape — a second, hand-rolled copy of the
    policy could drift from the real one and quietly miss a table, which
    is the exact failure mode this remediation exists to clean up after.
    """
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            counts = await count_live_credentials(
                db, scope=DISCONNECTED_INTEGRATION_IDS
            )
            print(
                f"Orphaned credentials on disconnected integrations: "
                f"api_key_credentials={counts.api_key_rows}, "
                f"integration_oauth_tokens={counts.oauth_rows}, "
                f"integration_ingest_tokens_unrevoked={counts.ingest_rows}"
            )

            if not apply:
                print("Dry run — no changes made. Re-run with --apply to scrub.")
                return

            scrubbed = await scrub_credentials(db, scope=DISCONNECTED_INTEGRATION_IDS)
            await db.commit()
            print(
                f"Scrubbed: api_key_rows_deleted={scrubbed.api_key_rows}, "
                f"oauth_rows_deleted={scrubbed.oauth_rows}, "
                f"ingest_rows_revoked={scrubbed.ingest_rows}"
            )
    finally:
        # The early `return` on a dry run used to skip engine.dispose()
        # entirely, leaking the connection pool on the common path.
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete/revoke rows. Without this flag, only reports counts.",
    )
    args = parser.parse_args()
    asyncio.run(scrub(apply=args.apply))


if __name__ == "__main__":
    main()
