"""Pass 1 — Identity resolution.

Assigns every EntityRecord its final vault_path (filenames are the
human display name, slugged; the stable_entity_id lives only in
frontmatter — never in the path), upserts the DB row keyed by
(user_id, stable_entity_id), builds link_map for the renderer, and
detects renames when an already-known entity's display name changed.

Zero vault/network I/O in this pass — everything here is Postgres only.
Path *policy* (folders, slugging, collision suffixes) lives in
``paths.py``; this module only decides WHICH entity gets a path and when
that path is allowed to move.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.ontology import OntologyEntityNote
from ....models.user import User
from .models import EntityRecord
from .paths import note_path, resolve_collision

# An entity absent from this many consecutive in-scope runs is archived
# rather than tracked (and re-rendered) forever.
_ARCHIVE_AFTER_MISSED_RUNS = 3

# Person entities are derived off whichever of calendar/email/github
# mentioned them, so a person seen only via a domain outside this run's
# scope would look "missing" and eventually be archived incorrectly.
_SWEEP_EXEMPT_DOMAINS = frozenset({"people"})


@dataclass(frozen=True)
class ResolveResult:
    link_map: dict[str, tuple[str, str]]
    rename_ops: list[tuple[str, str]]
    db_rows: list[OntologyEntityNote]
    dropped_duplicates: int
    dropped_relationships: int = 0


def _dedupe(entities: list[EntityRecord]) -> tuple[dict[str, EntityRecord], int]:
    """Collapse to one record per stable_entity_id.

    A Person seen via both calendar and github collapses to one record.
    Ties are broken by "more recent source_updated_at wins", so the
    outcome does not depend on extractor execution order.
    """
    by_id: dict[str, EntityRecord] = {}
    for rec in entities:
        existing = by_id.get(rec.stable_entity_id)
        if existing is None:
            by_id[rec.stable_entity_id] = rec
            continue
        newer = (
            rec.source_updated_at
            and existing.source_updated_at
            and rec.source_updated_at > existing.source_updated_at
        )
        if newer:
            by_id[rec.stable_entity_id] = rec
    return by_id, len(entities) - len(by_id)


def _is_renaming(row: OntologyEntityNote, rec: EntityRecord) -> bool:
    return bool(row.vault_path) and row.display_name != rec.display_name


def _claimed_paths(
    existing_by_id: dict[str, OntologyEntityNote],
    by_id: dict[str, EntityRecord],
) -> set[str]:
    """Paths that are genuinely unavailable to this run.

    Entities being renamed this run vacate their old path — excluding
    those paths up front lets another entity in the same batch claim a
    just-freed path instead of being pushed into a " (2)" suffix it
    doesn't need. Without this pre-pass, the path set (loaded before any
    renames are known) would still block on paths that are about to
    become free.
    """
    return {
        row.vault_path
        for stable_id, row in existing_by_id.items()
        if stable_id not in by_id or not _is_renaming(row, by_id[stable_id])
    }


def _sweep_missing(
    existing_by_id: dict[str, OntologyEntityNote],
    by_id: dict[str, EntityRecord],
    domains: tuple[str, ...] | None,
) -> None:
    """Age out entities tracked before but not extracted this run.

    They fell outside the lookback window, or the source row was deleted.
    ``missed_runs`` exists precisely so these get archived instead of
    accumulating in the vault/table forever — nothing else in this
    pipeline increments it. Scoped to ``domains`` (the run's
    cfg.domains): an entity from a domain this run didn't touch at all
    (e.g. a scoped "github only" run) was never a candidate for
    extraction and must not be penalised for it.
    """
    swept_domains = set(domains) if domains else None
    for stable_id, row in existing_by_id.items():
        if stable_id in by_id or row.sync_state == "archived":
            continue
        if row.domain in _SWEEP_EXEMPT_DOMAINS:
            continue
        if swept_domains is not None and row.domain not in swept_domains:
            continue
        row.missed_runs = (row.missed_runs or 0) + 1
        if row.missed_runs >= _ARCHIVE_AFTER_MISSED_RUNS:
            row.sync_state = "archived"


def _assign_path(
    rec: EntityRecord, prior: OntologyEntityNote | None, taken: set[str]
) -> str:
    # Keep the existing path unless the display name actually changed —
    # avoids churning paths for entities whose title is stable across runs.
    if (
        prior is not None
        and prior.vault_path
        and prior.display_name == rec.display_name
    ):
        return prior.vault_path
    return resolve_collision(note_path(rec.entity_type, rec.display_name), taken)


def _apply_record(
    row: OntologyEntityNote,
    rec: EntityRecord,
    *,
    path: str,
    now: datetime,
    resolvable_ids: set[str],
) -> int:
    """Copy an extracted record onto its tracking row.

    Returns the number of relationships dropped as unresolvable.
    """
    row.domain = rec.domain
    row.entity_type = rec.entity_type
    row.display_name = rec.display_name
    row.vault_path = path
    row.source_updated_at = rec.source_updated_at
    row.last_seen_at = now
    row.missed_runs = 0
    if row.sync_state in (None, "archived"):
        row.sync_state = "pending"
    row.tags = rec.tags
    # An edge to anything outside the set this run will render cannot be
    # turned into a wikilink, so it is dropped HERE — that is what makes
    # ``MissingLinkError`` the renderer-bug signal its docstring claims
    # it is. The common cause is the run's ``max_entities`` ceiling
    # cutting a Person that a retained Event still references; without
    # this filter the renderer raises and the caller drops the ENTIRE
    # event note, not just the one unresolvable edge.
    kept_rels = [r for r in rec.relationships if r.target_entity_id in resolvable_ids]
    row.relationships = [
        {"rel": r.rel, "target_entity_id": r.target_entity_id} for r in kept_rels
    ]
    return len(rec.relationships) - len(kept_rels)


async def _load_tracked(db: AsyncSession, user: User) -> list[OntologyEntityNote]:
    rows = await db.scalars(
        select(OntologyEntityNote).where(OntologyEntityNote.user_id == user.id)
    )
    return list(rows)


async def resolve(
    entities: list[EntityRecord],
    db: AsyncSession,
    user: User,
    domains: tuple[str, ...] | None = None,
) -> ResolveResult:
    by_id, dropped_duplicates = _dedupe(entities)

    existing_by_id = {
        row.stable_entity_id: row for row in await _load_tracked(db, user)
    }
    taken_paths = _claimed_paths(existing_by_id, by_id)

    _sweep_missing(existing_by_id, by_id, domains)

    link_map: dict[str, tuple[str, str]] = {}
    rename_ops: list[tuple[str, str]] = []
    db_rows: list[OntologyEntityNote] = []
    dropped_relationships = 0
    now = datetime.now(timezone.utc)
    resolvable_ids = set(by_id)

    # Deterministic order so collision-suffix assignment is stable run
    # to run: ascending stable_entity_id.
    for stable_id in sorted(by_id.keys()):
        rec = by_id[stable_id]
        prior = existing_by_id.get(stable_id)

        path = _assign_path(rec, prior, taken_paths)
        taken_paths.add(path)

        if prior is not None and prior.vault_path != path:
            rename_ops.append((prior.vault_path, path))

        link_map[stable_id] = (path, rec.display_name)

        is_new = prior is None
        row = prior or OntologyEntityNote(
            id=uuid.uuid4(), user_id=user.id, stable_entity_id=stable_id
        )
        dropped_relationships += _apply_record(
            row, rec, path=path, now=now, resolvable_ids=resolvable_ids
        )
        if is_new:
            # Must be added to the session here — the persist pass
            # mutates blob_sha/last_synced_at/sync_state on these same
            # objects after the commit lands, and relies on
            # `await db.commit()` to persist that. Without `db.add()`, a
            # freshly-constructed instance is transient: SQLAlchemy
            # tracks no changes on it, so those updates silently vanish,
            # blob_sha never leaves its default "", and every subsequent
            # run re-diffs and re-commits every new entity forever — a
            # direct break of the idempotent-upsert requirement
            # (FEAT-141 point 5). `prior` rows loaded via the `select()`
            # above are already session-attached, so no `db.add()` is
            # needed for them.
            db.add(row)
        db_rows.append(row)

    if db_rows:
        await db.flush()

    return ResolveResult(
        link_map=link_map,
        rename_ops=rename_ops,
        db_rows=db_rows,
        dropped_duplicates=dropped_duplicates,
        dropped_relationships=dropped_relationships,
    )
