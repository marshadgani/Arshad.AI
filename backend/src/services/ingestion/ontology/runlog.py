"""Run audit trail — the whole lifecycle of one ``OntologySyncRun`` row.

Previously the run row's status, counts, finished_at and the surrounding
``db.commit()`` were mutated from six different places in the
orchestrator, which made "what does the audit trail say after outcome
X?" unanswerable without reading all of it. ``SyncRunRecorder`` owns the
row instead: each terminal outcome is one named method, and the tricky
rollback-then-reinsert rule lives in exactly one place.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.ontology import OntologyEntityNote, OntologySyncRun

logger = logging.getLogger(__name__)

DEFERRED_SYNC_STATE = "deferred"


class SyncRunRecorder:
    """Writes one run's audit row. One recorder per ``sync()`` call."""

    def __init__(
        self, *, db: AsyncSession, user_id: uuid.UUID, dry_run: bool = False
    ) -> None:
        self._db = db
        self._user_id = user_id
        self._dry_run = dry_run
        # Generated up front (not left to the column default) so the id
        # survives a rollback: on a hard failure the whole transaction is
        # rolled back — discarding this row along with any resolved
        # entities — and ``abandon()`` then re-inserts a standalone
        # terminal row under the SAME id, so the audit trail isn't
        # silently empty for every failed run.
        self._run_id = uuid.uuid4()
        self._run: OntologySyncRun | None = None

    @property
    def run_id(self) -> uuid.UUID:
        return self._run_id

    async def begin(self) -> None:
        self._run = OntologySyncRun(
            id=self._run_id,
            user_id=self._user_id,
            status="running",
            dry_run=self._dry_run,
        )
        self._db.add(self._run)
        await self._db.flush()

    async def complete(
        self,
        counts: dict[str, Any],
        *,
        commit_sha: str | None = None,
        branch: str | None = None,
    ) -> None:
        run = self._require_run()
        run.status = "succeeded"
        run.counts = counts
        run.commit_sha = commit_sha
        run.branch = branch
        run.finished_at = datetime.now(timezone.utc)
        await self._db.commit()

    async def defer(self, reason: str, rows: Iterable[OntologyEntityNote]) -> None:
        """Park this run's entities so the next run retries them."""
        run = self._require_run()
        for row in rows:
            row.sync_state = DEFERRED_SYNC_STATE
        run.status = "deferred"
        run.error_code = reason
        run.finished_at = datetime.now(timezone.utc)
        await self._db.commit()

    async def abandon(
        self,
        status: str,
        *,
        counts: dict[str, Any] | None = None,
        error_code: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Discard the run's work, then record its terminal state alone.

        Used when nothing the run did may persist: a dry run (which must
        leave no trace of its resolved entities) and a hard failure
        (which must not leave half-resolved rows behind). The rollback
        takes the "running" row flushed by ``begin()`` with it, so the
        terminal row is re-inserted standalone afterwards. Best-effort:
        failing to write an audit row must never mask the real error.
        """
        await self._db.rollback()
        self._run = None
        try:
            self._db.add(
                OntologySyncRun(
                    id=self._run_id,
                    user_id=self._user_id,
                    status=status,
                    error_code=error_code,
                    counts=counts or {},
                    dry_run=dry_run,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            await self._db.commit()
        except Exception:  # noqa: BLE001 — audit-row failure is non-fatal
            await self._db.rollback()
            logger.exception(
                "ontology sync: failed to persist terminal audit row for run %s",
                self._run_id,
            )

    def _require_run(self) -> OntologySyncRun:
        if self._run is None:
            raise RuntimeError("SyncRunRecorder.begin() was not called")
        return self._run
