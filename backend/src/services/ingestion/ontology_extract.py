"""ontology_extractor — orchestrates the GitHub person/project graph build.

Sweeps ``ingested_github_activity`` for one user, derives person/project
entities and ``contributed_to`` edges, and upserts them into
``ontology_entities`` / ``ontology_relationships``.

This module owns only orchestration, payload validation, and
observability. The two heavier concerns live in siblings:

  * ``ontology_graph``      — derivation. Pure, synchronous, no DB.
  * ``ontology_repository`` — persistence. Every SQL statement, no policy.

so the sequence ``extract()`` performs is readable end to end in one
screen, and each collaborator is testable on its own (the graph without
Postgres, the repository without payload-parsing rules).

Called from ``runner.run(dag_id="ontology_extractor", ...)``, which is in
turn triggered by a ``dag_trigger_queue`` row inserted by
``scripts/ontology_extract.py`` (the CLI) — there is no HTTP endpoint for
this in this slice.

Never calls ``set_config('app.allow_visibility_promotion', ...)``: see
the migration docstring for why every write the repository performs is
already exempt from the visibility ratchet.

TRANSACTION OWNERSHIP — THIS MODULE COMMITS
----------------------------------------------
``extract()`` calls ``db.commit()`` itself, exactly like every sibling
ingestion module (calendar, email, github, analytics, obsidian all do).
This is NOT optional bookkeeping — neither caller commits:

  * ``services/queue_worker.py::_process`` runs the runner inside
    ``async with AsyncSessionLocal() as runner_db:`` and never commits.
    ``AsyncSession.__aexit__`` closes the session, which ROLLS BACK any
    open transaction.
  * ``data-pipelines/ingestion/_ingestion_helpers.py::run_ingest_for_row``
    has the identical shape.

An earlier revision of this module deferred the commit to "the caller,
matching every sibling" — that premise was false in both halves, and the
result was total silent data loss in production: the sweep ran, the
upserts ran, the summary reported ``entities_written > 0``, the worker
marked the queue row ``completed``, and then every ontology row was
discarded on session close. Do not remove the commit below.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from . import ontology_repository as repo
from .errors import IngestionError
from .ontology_graph import MAX_EXTERNAL_KEY_LEN, derive_graph

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 5000
_MAX_ROWS_CEILING = 50000


@dataclass(frozen=True)
class ExtractOptions:
    """Validated sweep window. Parsing the untrusted payload into this
    happens once, up front, so the rest of ``extract()`` deals only in
    known-good values instead of re-reading raw dict keys."""

    max_rows: int
    #: UPPER bound on ``occurred_at`` (``occurred_at < since``) — the
    #: backwards-paging cursor for walking past a truncated run, NOT an
    #: incremental "changed since last run" watermark. Passing a
    #: last-run timestamp here processes everything OLDER than it and
    #: skips every new row. Always timezone-aware (see ``_parse_since``).
    since: datetime | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ExtractOptions:
        return cls(max_rows=_clamp_max_rows(payload), since=_parse_since(payload))


@dataclass(frozen=True)
class ExtractionSummary:
    """Outcome of one run. A typed record rather than a bare dict so the
    truncation and staleness signals are part of the contract and cannot
    be dropped by a later edit without a type error — ``extract()`` still
    returns ``as_dict()`` to honour the runner's ``dict`` contract."""

    # Rows ACTUALLY PROCESSED — equals max_rows when truncated is True.
    # The sweep fetches max_rows+1 as a truncation probe, but that extra
    # row is never derived from.
    rows_scanned: int
    truncated: bool
    entities_written: int
    relationships_written: int
    skipped_no_author: int
    #: Rows dropped because a GitHub login or repo name exceeded
    #: ``ontology_entities.external_key``'s 255-char column. Non-zero
    #: means third-party data is being silently excluded from the graph.
    skipped_oversized_key: int
    stale_classifications: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp_max_rows(payload: dict[str, Any]) -> int:
    raw_value = payload.get("max_rows")
    try:
        max_rows = int(raw_value) if raw_value is not None else _DEFAULT_MAX_ROWS
    except (TypeError, ValueError):
        # raw_value was present but not coercible to int (e.g. "abc", a
        # list) — this is caller error, not "no preference given". Silently
        # substituting the default here would hide a broken caller behind
        # what looks like a normal extraction run. Surface it.
        logger.warning(
            "Ignoring invalid max_rows payload value %r (not an int); "
            "falling back to default %d.",
            raw_value,
            _DEFAULT_MAX_ROWS,
        )
        max_rows = _DEFAULT_MAX_ROWS

    max_rows = max(1, min(max_rows, _MAX_ROWS_CEILING))
    if max_rows > _DEFAULT_MAX_ROWS:
        logger.warning(
            "max_rows=%d exceeds default cap; ensure this is intentional.",
            max_rows,
        )
    return max_rows


def _parse_since(payload: dict[str, Any]) -> datetime | None:
    since_raw = payload.get("since")
    if since_raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(since_raw))
    except ValueError as exc:
        raise IngestionError(f"invalid_since: {since_raw!r}") from exc
    if parsed.tzinfo is None:
        # occurred_at is timestamptz. A naive value is silently reinterpreted
        # by Postgres in the session TimeZone, shifting the sweep window by
        # the server's UTC offset and quietly including or excluding rows the
        # caller did not intend. Reject rather than guess.
        raise IngestionError(
            f"invalid_since: {since_raw!r} has no timezone offset; "
            "pass an explicit offset (e.g. '2026-09-01T00:00:00+00:00')"
        )
    return parsed


def _emit_observability(
    summary: ExtractionSummary, options: ExtractOptions, user_id: uuid.UUID
) -> None:
    """All logging for a run, in one place. Kept out of the orchestration
    body so the sequence of work stays legible, and out of the repository
    so SQL can be audited without wading through log strings."""
    if summary.truncated:
        logger.warning(
            "Extraction truncated: scanned newest %d of >%d GitHub rows for "
            "user %s; older rows are NOT processed and will remain "
            "unprocessed until per-source watermarking ships (follow-up "
            "slice). Use payload since=<oldest_occurred_at> to walk "
            "backwards in windows.",
            options.max_rows,
            options.max_rows,
            user_id,
        )
    if summary.skipped_oversized_key > 0:
        logger.warning(
            "Dropped %d GitHub activity rows for user %s: login or repo name "
            "exceeded ontology_entities.external_key's %d-char limit. Those "
            "entities and their edges are absent from the graph.",
            summary.skipped_oversized_key,
            user_id,
            MAX_EXTERNAL_KEY_LEN,
        )
    if summary.stale_classifications > 0:
        logger.warning(
            "Found %d stale classifications for user %s. Follow-up slice "
            "should re-classify.",
            summary.stale_classifications,
            user_id,
        )
    logger.info(
        "Ontology extraction complete for user %s: %s", user_id, summary.as_dict()
    )


async def extract(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    options = ExtractOptions.from_payload(payload)

    rows, truncated = await repo.sweep(db, user.id, options.max_rows, options.since)
    graph = derive_graph(rows)

    key_map, entities_written = await repo.upsert_entities(
        db, user.id, graph.persons, graph.projects
    )
    relationships_written = await repo.upsert_relationships(
        db, user.id, graph.edges, key_map
    )
    # Neither caller commits (see this module's docstring) — without this
    # the worker reports success and every row above is rolled back on
    # session close. Under the pg_session test fixture this only releases
    # a savepoint, so test isolation is preserved.
    await db.commit()

    stale_classifications = await repo.count_stale_classifications(db, user.id)

    summary = ExtractionSummary(
        rows_scanned=len(rows),
        truncated=truncated,
        entities_written=entities_written,
        relationships_written=relationships_written,
        skipped_no_author=graph.skipped_no_author,
        skipped_oversized_key=graph.skipped_oversized_key,
        stale_classifications=stale_classifications,
    )
    _emit_observability(summary, options, user.id)
    return summary.as_dict()
