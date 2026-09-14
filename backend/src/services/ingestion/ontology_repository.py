"""Persistence layer for the ontology extractor — every statement that
touches Postgres, and nothing else.

One concern per module across the extractor:

  * ``ontology_graph``       — derivation (pure, no DB)
  * ``ontology_repository``  — persistence (this module, no policy)
  * ``ontology_extract``     — orchestration, options, observability

Nothing here decides *whether* to run, *how much* to sweep, or *what to
log* — callers pass an already-validated row cap and window, and get
back plain data. That is what makes the SQL reviewable in isolation:
a reader auditing the visibility ratchet can read this file alone and
see every write the extractor is capable of performing.

VISIBILITY RATCHET — WHY NOTHING HERE SETS THE GUC
-----------------------------------------------------
No statement in this module writes ``visibility``, and none calls
``set_config('app.allow_visibility_promotion', ...)``. The entity upsert
omits ``visibility`` on INSERT (so ``server_default='private'`` applies)
and excludes it from the ``DO UPDATE SET`` clause (so the trigger's
``OLD.visibility = NEW.visibility`` arm passes without the GUC); the
relationship upsert is ``DO NOTHING`` and never updates at all. Adding
``visibility`` to either statement, or adding a ``set_config`` call,
would disable the ratchet across the only writer path in a slice whose
entire purpose is that ratchet. See the migration docstring.

This module never commits: the commit belongs to ``ontology_extract``,
which owns the run boundary and knows when the whole graph is written.
Note that the commit must happen *somewhere in this package* — neither
the queue worker nor the Airflow helper commits the session they hand
in, so anything left uncommitted is silently rolled back on session
close. See ``ontology_extract``'s docstring.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.ontology import OntologyEntity, OntologyRelationship
from ...models.ontology_vocabulary import GITHUB_CONTRIBUTION
from .ontology_graph import EdgeTuple

logger = logging.getLogger(__name__)

#: ``(entity_type, external_key) -> ontology_entities.id``, the lookup
#: the relationship upsert needs to resolve an edge's endpoints.
EntityKeyMap = dict[tuple[str, str], uuid.UUID]

# Sweep fetches max_rows+1 (never derived from) purely as a truncation
# probe: if we get back more than max_rows, older rows exist that this
# run did not process. ORDER BY occurred_at DESC means the cap drops the
# OLDEST rows, so a truncated run still keeps recent data current.
# Both variants are fully-formed, immutable ``text()`` constants built at
# import time. Nothing is str.format()-ed, f-string-ed or concatenated at
# request time, so there is no runtime code path where a value could
# become SQL syntax — every input is a bound parameter
# (.claude/rules/database.md: "Never use string interpolation in
# queries"). If a third window predicate is ever needed, add a third
# constant here; do not reintroduce a formatted template.
_SWEEP_SELECT = """
    SELECT id, occurred_at, provider_id, raw
    FROM ingested_github_activity
    WHERE user_id = :user_id
"""
_SWEEP_ORDER = """
    ORDER BY occurred_at DESC, id DESC
    LIMIT :fetch_limit
"""

_SWEEP_ALL_SQL = text(_SWEEP_SELECT + _SWEEP_ORDER)
_SWEEP_BEFORE_SQL = text(
    _SWEEP_SELECT + "    AND occurred_at < :since\n" + _SWEEP_ORDER
)

# Entity/relationship writes are batched multi-row upserts below, not one
# round-trip per row. A single 5000-row sweep can resolve to hundreds of
# unique persons/projects and thousands of edges (one row per issue/PR a
# person touched — ontology_graph does not dedupe edges), and a per-row
# `await db.execute()` loop turned that into hundreds-to-thousands of
# sequential network round-trips on the hot path of every extraction run.
# Chunking keeps each statement comfortably under Postgres's 65535
# bind-parameter limit (500 rows * 5 params max = 2500) while cutting
# round-trips by roughly two to three orders of magnitude.
_UPSERT_BATCH_SIZE = 500


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


# The only query against ix_ontology_entities_stale — without it that
# partial index has no consumer in this slice.
_STALE_CLASSIFICATIONS_SQL = text(
    """
    SELECT count(*) FROM ontology_entities
    WHERE user_id = :user_id
      AND visibility <> 'private'
      AND (classification_checked_at IS NULL
           OR classification_checked_at < now() - interval '30 days')
    """
)


async def sweep(
    db: AsyncSession,
    user_id: uuid.UUID,
    max_rows: int,
    since: datetime | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return ``(rows, truncated)`` — newest-first GitHub activity rows,
    and whether older rows exist beyond the cap that this run did not
    process.

    ``since`` is an UPPER bound (``occurred_at < since``), not a lower
    one — it is the backwards-paging cursor for walking past a truncated
    run, not an incremental-since-last-run watermark. See
    ``ontology_extract.ExtractOptions``.
    """
    params: dict[str, Any] = {"user_id": user_id, "fetch_limit": max_rows + 1}
    if since is None:
        sql = _SWEEP_ALL_SQL
    else:
        sql = _SWEEP_BEFORE_SQL
        params["since"] = since

    result = await db.execute(sql, params)
    fetched = [dict(row._mapping) for row in result]

    truncated = len(fetched) > max_rows
    rows = fetched[:max_rows] if truncated else fetched
    return rows, truncated


async def upsert_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    persons: set[str],
    projects: set[str],
) -> tuple[EntityKeyMap, int]:
    """Upsert person/project entities in batched multi-row statements,
    returning their key map and the number written."""
    rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "entity_type": GITHUB_CONTRIBUTION.source_entity_type,
            "external_key": key,
        }
        for key in sorted(persons)
    ] + [
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "entity_type": GITHUB_CONTRIBUTION.target_entity_type,
            "external_key": key,
        }
        for key in sorted(projects)
    ]
    if not rows:
        return {}, 0

    key_map: EntityKeyMap = {}
    for batch in _chunks(rows, _UPSERT_BATCH_SIZE):
        stmt = (
            pg_insert(OntologyEntity)
            .values(batch)
            .on_conflict_do_update(
                index_elements=["user_id", "entity_type", "external_key"],
                set_={"updated_at": func.now()},
            )
            .returning(
                OntologyEntity.id,
                OntologyEntity.entity_type,
                OntologyEntity.external_key,
            )
        )
        result = await db.execute(stmt)
        returned = result.all()
        for row in returned:
            key_map[(row.entity_type, row.external_key)] = row.id

        if len(returned) != len(batch):
            # INSERT ... ON CONFLICT DO UPDATE ... RETURNING should return
            # exactly one row per input row — this branch should be
            # unreachable. If it ever fires, silently dropping the entity
            # would desync key_map from the table and make
            # upsert_relationships skip every edge touching it with no
            # trace of why.
            missing = {(r["entity_type"], r["external_key"]) for r in batch} - {
                (row.entity_type, row.external_key) for row in returned
            }
            logger.warning(
                "Ontology entity batch upsert returned %d/%d rows for "
                "user_id=%s — missing keys: %s. Those entities were NOT "
                "added to the key map; edges touching them will be "
                "silently dropped by upsert_relationships.",
                len(returned),
                len(batch),
                user_id,
                missing,
            )

    return key_map, len(key_map)


async def upsert_relationships(
    db: AsyncSession,
    user_id: uuid.UUID,
    edges: list[EdgeTuple],
    key_map: EntityKeyMap,
) -> int:
    """Resolve edges to entity ids and upsert them in batched multi-row
    statements, returning the number of genuinely new rows."""
    rows: list[dict[str, Any]] = []
    # dedupe first: one contributor can touch the same project dozens of
    # times in a single sweep (one activity row per issue/PR, and
    # ontology_graph does not dedupe edges) — without this, every
    # duplicate still round-trips through the upsert below.
    for edge in sorted(set(edges)):
        source_id = key_map.get(
            (GITHUB_CONTRIBUTION.source_entity_type, edge.person_key)
        )
        target_id = key_map.get(
            (GITHUB_CONTRIBUTION.target_entity_type, edge.project_key)
        )
        if source_id is None or target_id is None:
            # Should not happen in normal operation: every person/project in
            # `edges` came from the same sweep that fed upsert_entities, so
            # both endpoints should already be in key_map. If one is missing
            # (e.g. the RETURNING-row anomaly above), a silent `continue`
            # would drop the edge with zero signal — the run would report
            # success with a lower-than-expected relationships_written and
            # nobody could tell why.
            logger.warning(
                "Skipping ontology edge for user_id=%s: unresolved endpoint "
                "(person=%s -> project=%s, source_id=%s, target_id=%s). "
                "Entity upsert did not produce a key for one or both "
                "endpoints.",
                user_id,
                edge.person_key,
                edge.project_key,
                source_id,
                target_id,
            )
            continue
        rows.append(
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "source_entity_id": source_id,
                "relationship_type": edge.relationship,
                "target_entity_id": target_id,
            }
        )

    if not rows:
        return 0

    written = 0
    for batch in _chunks(rows, _UPSERT_BATCH_SIZE):
        stmt = (
            pg_insert(OntologyRelationship)
            .values(batch)
            .on_conflict_do_nothing(
                index_elements=[
                    "user_id",
                    "source_entity_id",
                    "relationship_type",
                    "target_entity_id",
                ],
            )
        )
        result = await db.execute(stmt)
        written += result.rowcount or 0

    return written


async def count_stale_classifications(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Count non-private entities whose classification has never been
    checked, or was last checked over 30 days ago."""
    result = await db.execute(_STALE_CLASSIFICATIONS_SQL, {"user_id": user_id})
    return int(result.scalar_one())
