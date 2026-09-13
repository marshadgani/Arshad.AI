"""FEAT-141 — Obsidian Ontology Layer orchestrator.

Push-syncs Arshad.AI's already-ingested domain data into the vault as
linked entity notes + per-domain MOCs. This module is wiring only: every
pass below is implemented by its own module, and the rule for this file
is that it decides *sequence and transaction boundaries*, never policy.

  0. Extract  — per-domain pure-DB readers ....... ``extract/``
  1. Resolve  — stable identity + vault paths .... ``resolve.py`` / ``paths.py``
  2. Compose  — byte-deterministic note text ..... ``compose.py`` / ``render.py``
  3. Diff     — local blob-SHA comparison ........ ``diff.py``
  3.5 Preserve — fetch + reattach user tails ..... here (see below)
  4. Publish  — one Git Data API commit .......... ``vault_writer.py``
  5. Persist  — blob_sha / sync_state + event .... here + ``runlog.py``

Concurrency: the trigger endpoint (api/v1/obsidian.py) refuses to
enqueue a second job while one is pending/picked for this dag_id, and
the Git Data ``update_ref`` call is itself optimistic-concurrency-safe
(a concurrent push yields 422, retried once, then deferred) — no
advisory lock needed on top of that.

Pass 3.5 exists to close SEC-002 (security audit, 2026-09-13): ``compose()``
always renders entity notes with ``user_tail=None`` because it has no
network access to know what a note currently holds. Committing that
verbatim would silently delete anything Arshad appended below the
``MANAGED_END`` marker every time an entity's managed metadata changes
(which is most runs — e.g. any bump to ``source_updated_at``). Before
publishing, every entity note this run is about to REWRITE (not create —
``row.blob_sha`` is only non-empty once we've written it before) has its
live content fetched via the Contents API and its tail reattached. Notes
that aren't being rewritten this run are never touched, so no fetch is
needed for them — the cost of this pass is bounded by ``plan.written_count``
for pre-existing notes, the same quantity the diff pass already exists to
minimise, not by vault size. A pre-flight rate check (mirroring
``VaultWriter``'s own) defers the whole run rather than fetching some
tails and running out mid-loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.ontology import OntologyEntityNote
from ....models.user import User
from ....tools.base import ProviderReauthRequired, ToolError
from ... import event_bus
from ...obsidian_client import fetch_blob, vault_repo
from ...obsidian_git_data import ObsidianGitDataClient
from ..runner import IngestionError
from . import extract
from .catalogue import navigation_records
from .compose import MOC_ENTITY_TYPE, ComposedNotes, compose
from .config import OntologyConfig
from .diff import DiffPlan, plan_changes
from .render import extract_user_tail, render_entity
from .resolve import ResolveResult, resolve
from .runlog import SyncRunRecorder
from .vault_writer import MIN_API_BUDGET, VaultWriter

logger = logging.getLogger(__name__)

SYNCED_STATE = "synced"
ONTOLOGY_SYNCED_EVENT = "events.obsidian.ontology_synced"
DEFER_RATE_LIMIT = "rate_limit"


def _counts(
    resolved: ResolveResult, composed: ComposedNotes, plan: DiffPlan
) -> dict[str, Any]:
    return {
        # Writes only. Rename-deletes are a separate population (they are
        # not rendered notes), counted under "deleted" — folding them in
        # here would inflate "created_or_updated" past the note count.
        "created_or_updated": plan.written_count,
        "deleted": plan.deleted_count,
        "unchanged": plan.unchanged_count,
        "renamed": len(resolved.rename_ops),
        "unresolved_relationships": composed.unresolved_relationships,
        "dropped_duplicates": resolved.dropped_duplicates,
    }


def _mark_synced(rows: list[OntologyEntityNote], plan: DiffPlan, now: datetime) -> None:
    """Record what actually landed, so the next run's diff can skip it."""
    written = plan.written_paths
    for row in rows:
        if row.vault_path in written:
            row.blob_sha = plan.sha_for(row.vault_path)
            row.last_synced_at = now
            row.sync_state = SYNCED_STATE


async def _announce(
    user: User, run_id: Any, commit_sha: str | None, counts: dict[str, Any]
) -> None:
    try:
        await event_bus.publish(
            ONTOLOGY_SYNCED_EVENT,
            {
                "user_id": str(user.id),
                "run_id": str(run_id),
                "commit_sha": commit_sha,
                "counts": counts,
            },
        )
    except Exception as exc:  # noqa: BLE001 — event delivery is best-effort
        logger.warning("ontology sync: event publish failed — %s", exc)


def _rewrite_targets(
    plan: DiffPlan, rows_by_path: dict[str, OntologyEntityNote]
) -> list[str]:
    """Paths this run is about to overwrite where a live user tail could
    exist: the note is an entity note (MOCs/index are fully managed, no
    tail support), and it has been synced before (``blob_sha`` non-empty
    means "this path already exists in the vault because we put it
    there" — brand-new notes have nothing to preserve)."""
    return [
        path
        for path in plan.written_paths
        if (row := rows_by_path.get(path)) is not None
        and row.entity_type != MOC_ENTITY_TYPE
        and row.blob_sha
    ]


async def _preserve_user_tails(
    *,
    db: AsyncSession,
    user: User,
    repo: str,
    composed: ComposedNotes,
    resolved: ResolveResult,
    plan: DiffPlan,
) -> DiffPlan:
    """Re-renders every about-to-be-overwritten entity note with its live
    tail reattached, then recomputes the plan against the merged content.
    Returns the (possibly unchanged) plan for the caller to act on."""
    rows_by_path = {row.vault_path: row for row in resolved.db_rows}
    targets = _rewrite_targets(plan, rows_by_path)
    if not targets:
        return plan

    merged_any = False
    for path in targets:
        try:
            existing_content, _ = await fetch_blob(db, user, repo, path)
        except ToolError as exc:
            if exc.code == "obsidian_not_found":
                continue  # nothing on the vault side to preserve
            raise
        tail = extract_user_tail(existing_content)
        if not tail:
            continue
        row = rows_by_path[path]
        composed.by_path[path] = render_entity(row, resolved.link_map, user_tail=tail)
        merged_any = True

    if not merged_any:
        return plan

    return plan_changes(
        composed.by_path,
        {row.vault_path: row.blob_sha for row in resolved.db_rows},
        resolved.rename_ops,
    )


async def sync(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    cfg = OntologyConfig.from_payload(payload)
    # Deliberately before the run row exists: a misconfigured vault is a
    # setup error, not a sync attempt worth recording in the audit trail.
    repo = vault_repo()

    recorder = SyncRunRecorder(db=db, user_id=user.id, dry_run=cfg.dry_run)
    await recorder.begin()

    try:
        candidates = await extract.collect(user, db, cfg)
        candidates.extend(navigation_records(cfg.domains))

        resolved = await resolve(candidates, db, user, domains=cfg.domains)
        composed = compose(
            resolved.db_rows,
            resolved.link_map,
            cfg.domains,
            unresolved_relationships=resolved.dropped_relationships,
        )
        plan = plan_changes(
            composed.by_path,
            {row.vault_path: row.blob_sha for row in resolved.db_rows},
            resolved.rename_ops,
        )

        if cfg.dry_run:
            counts = {
                "candidates": len(candidates),
                **_counts(resolved, composed, plan),
            }
            await recorder.abandon("dry_run", counts=counts, dry_run=True)
            return {"dry_run": True, **counts}

        if not plan:
            counts = {"created_or_updated": 0, "unchanged": composed.note_count}
            await recorder.complete(counts)
            return {"status": "succeeded", **counts}

        rows_by_path = {row.vault_path: row for row in resolved.db_rows}
        tail_targets = _rewrite_targets(plan, rows_by_path)
        if tail_targets:
            # Pre-flight budget check mirrors VaultWriter's own: one
            # Contents API call per candidate tail-fetch, plus the
            # commit's own MIN_API_BUDGET headroom, checked up front so a
            # deferred run never leaves some tails fetched and others not.
            rate_client = ObsidianGitDataClient(db=db, user=user, repo=repo)
            try:
                rate = await rate_client.get_rate_limit()
            finally:
                await rate_client.aclose()
            if rate["remaining"] < len(tail_targets) + MIN_API_BUDGET:
                await recorder.defer(DEFER_RATE_LIMIT, resolved.db_rows)
                return {
                    "status": "deferred",
                    "reason": DEFER_RATE_LIMIT,
                    "remaining": rate["remaining"],
                }

        plan = await _preserve_user_tails(
            db=db,
            user=user,
            repo=repo,
            composed=composed,
            resolved=resolved,
            plan=plan,
        )

        if not plan:
            counts = {"created_or_updated": 0, "unchanged": composed.note_count}
            await recorder.complete(counts)
            return {"status": "succeeded", **counts}

        writer = VaultWriter(db=db, user=user, repo=repo)
        outcome = await writer.publish(
            plan.changes,
            message=f"ontology sync: {plan.changed_count} note(s) [{recorder.run_id}]",
        )
        reason = outcome.defer_reason
        if reason is not None:
            await recorder.defer(reason, resolved.db_rows)
            deferred: dict[str, Any] = {"status": "deferred", "reason": reason}
            if outcome.rate_remaining is not None:
                deferred["remaining"] = outcome.rate_remaining
            return deferred

        commit_sha = outcome.commit_sha
        _mark_synced(resolved.db_rows, plan, datetime.now(timezone.utc))
        counts = _counts(resolved, composed, plan)
        await recorder.complete(counts, commit_sha=commit_sha, branch=outcome.branch)
        await _announce(user, recorder.run_id, commit_sha, counts)
        return {"status": "succeeded", "commit_sha": commit_sha, **counts}

    except ProviderReauthRequired:
        await recorder.abandon("failed", error_code="provider_reauth_required")
        raise
    except ToolError as exc:
        await recorder.abandon("failed", error_code=exc.code)
        raise IngestionError(
            f"ontology_sync_failed: {exc.code}: {exc.message}"
        ) from exc
