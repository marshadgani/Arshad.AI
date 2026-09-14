"""Outbound Obsidian exporter — Arshad.AI ingested_* -> vault markdown notes.

One-way sync only (Arshad.AI -> vault). No bidirectional sync, no
ontology/MOC graph — see renderers.py's module docstring for how the
FEAT-141 non-reintroduction boundary is enforced in code.

Entry point is ``export_notes()``, dispatched from
services/ingestion/runner.py under dag_id='obsidian_exporter'.

This module orchestrates and decides; it does not query, render, or speak
HTTP. Rendering and the ledger diff are in export_planner.py, every
database access is in export_repository.py, the vault write is in
batch_commit.py, and the run lock is in export_lock.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian_export import ObsidianExportState
from ...models.user import User
from ...tools.base import ToolError
from . import batch_commit, client, config, export_planner, export_repository, jobs
from .client import RepoVisibility, VaultFile
from .config import ExportConfig
from .domains import ExportDomain, select_domains
from .export_lock import export_lock
from .export_planner import NotePlan
from .renderers import RenderedNote

MAX_NOTES_PER_RUN = 500
MAX_CHAINED_RUNS = 20


class _DomainWork(NamedTuple):
    """What reading one domain's pending rows decided, before any write.

    Deliberately holds no NotePlans: the ledger diff that produces them
    needs one lookup batched across *all* domains, so it can only happen
    after every domain has been read.
    """

    domain: ExportDomain
    state: ObsidianExportState
    rendered: list[tuple[Any, RenderedNote]]
    failures: list[dict[str, str]]
    new_watermark_ts: datetime | None
    new_watermark_id: Any
    has_more: bool


async def export_notes(
    user: User, db: AsyncSession, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = payload or {}
    domains = select_domains(payload.get("domains"))
    since_override = export_repository.as_utc(_parse_since(payload.get("since")))
    chain = int(payload.get("chain") or 0)

    async with export_lock(user.id) as acquired:
        if not acquired:
            return {"status": "skipped_locked", "domains": {}}
        return await _run_export(user, db, domains, since_override, chain)


def _parse_since(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def _screen_by_visibility(
    db: AsyncSession,
    user: User,
    domains: list[ExportDomain],
    visibility: RepoVisibility,
) -> tuple[list[ExportDomain], dict[str, Any]]:
    """Drop domains that may not be written to a non-private vault.

    RepoVisibility.is_export_safe() is fail-closed: UNKNOWN (never a bare
    False/None) is treated the same as a confirmed public repo.
    """
    allowed: list[ExportDomain] = []
    refused: dict[str, Any] = {}
    for domain in domains:
        if domain.requires_private_vault and not visibility.is_export_safe():
            state = await export_repository.get_or_create_state(db, user, domain.name)
            reason = (
                "vault_repo_visibility_unknown"
                if visibility is RepoVisibility.UNKNOWN
                else "skipped_public_repo"
            )
            state.last_error = reason
            await db.commit()
            refused[domain.name] = {"status": reason, "notes_written": 0}
            continue
        allowed.append(domain)
    return allowed, refused


async def _plan_domain(
    db: AsyncSession,
    user: User,
    domain: ExportDomain,
    cfg: ExportConfig,
    since_override: datetime | None,
) -> _DomainWork:
    """Read this domain's pending rows and render them. No writes yet."""
    state = await export_repository.get_or_create_state(db, user, domain.name)
    watermark_ts = since_override or export_repository.as_utc(state.last_exported_at)
    watermark_id = state.last_exported_id if not since_override else None

    rows = await export_repository.fetch_watermarked_rows(
        db, user, domain, watermark_ts, watermark_id, MAX_NOTES_PER_RUN
    )
    has_more = len(rows) > MAX_NOTES_PER_RUN
    if has_more:
        rows = rows[:MAX_NOTES_PER_RUN]

    result = export_planner.render_rows(domain, rows, cfg)
    frozen = result.frozen_rows
    return _DomainWork(
        domain=domain,
        state=state,
        rendered=result.rendered,
        failures=result.as_dicts(),
        new_watermark_ts=(
            export_repository.as_utc(frozen[-1].ingested_at) if frozen else watermark_ts
        ),
        new_watermark_id=frozen[-1].id if frozen else watermark_id,
        has_more=has_more,
    )


async def _run_export(
    user: User,
    db: AsyncSession,
    domains: list[ExportDomain],
    since_override: datetime | None,
    chain: int,
) -> dict[str, Any]:
    repo = await config.resolve_vault_repo(db, user)
    visibility = await client.repo_is_private(db, user, repo)
    allowed, domain_results = await _screen_by_visibility(db, user, domains, visibility)

    cfg = ExportConfig.from_env()
    work_by_domain: dict[str, _DomainWork] = {
        domain.name: await _plan_domain(db, user, domain, cfg, since_override)
        for domain in allowed
    }

    existing_by_path = await export_repository.fetch_existing_exported(
        db,
        user,
        [note.path for w in work_by_domain.values() for _, note in w.rendered],
    )

    # Diff against the ledger in memory only — no session mutation yet.
    # Staging inserts/updates must wait until the vault write below has
    # actually succeeded, otherwise a failed GitHub write would still get
    # committed to the ledger as if it had been exported.
    files: list[VaultFile] = []
    plans_by_domain: dict[str, list[NotePlan]] = {}
    for name, work in work_by_domain.items():
        domain_files, plans_by_domain[name] = export_planner.build_export_plan(
            work.rendered, existing_by_path
        )
        files.extend(domain_files)

    # Read phase is done — commit it (this only persists the idempotent
    # ObsidianExportState rows created by get_or_create_state; no ledger
    # rows are pending yet) so the DB connection isn't left idle-in-transaction
    # for the duration of the multi-round-trip GitHub API call below
    # (database.md: never hold a transaction open across a network call).
    await db.commit()

    commit_sha = ""
    if files:
        try:
            commit_sha = await batch_commit.create_commit_batch(
                db,
                user,
                repo,
                files,
                message=(
                    f"Arshad.AI export: {len(files)} note(s) "
                    f"[{datetime.now(timezone.utc).isoformat()}]"
                ),
            )
        except ToolError as exc:
            return await _record_commit_failure(
                db, work_by_domain, domains, domain_results, exc
            )

    now = datetime.now(timezone.utc)
    for name, work in work_by_domain.items():
        domain_results[name] = _commit_domain(
            db, user, work, plans_by_domain[name], commit_sha, now
        )
    await db.commit()

    has_more = any(w.has_more for w in work_by_domain.values())
    if has_more and chain < MAX_CHAINED_RUNS:
        await _queue_chained_run(
            db, user, domains, work_by_domain, since_override, chain, now
        )

    return {"status": "ok", "domains": domain_results, "has_more": has_more}


async def _record_commit_failure(
    db: AsyncSession,
    work_by_domain: dict[str, _DomainWork],
    domains: list[ExportDomain],
    domain_results: dict[str, Any],
    exc: ToolError,
) -> dict[str, Any]:
    for work in work_by_domain.values():
        work.state.last_error = f"{exc.code}: {exc.message}"
    await db.commit()
    for domain in domains:
        if domain.name not in domain_results:
            domain_results[domain.name] = {
                "status": "commit_failed",
                "notes_written": 0,
                "error": exc.code,
            }
    return {"status": "commit_failed", "domains": domain_results}


def _commit_domain(
    db: AsyncSession,
    user: User,
    work: _DomainWork,
    plans: list[NotePlan],
    commit_sha: str,
    now: datetime,
) -> dict[str, Any]:
    """Stage this domain's ledger rows and update its export state.

    Session mutation only — the caller commits once for all domains.
    """
    written = export_repository.stage_ledger(
        db, user, work.domain, plans, commit_sha, now
    )
    export_repository.advance_watermark(
        work.state, work.new_watermark_ts, work.new_watermark_id
    )
    work.state.notes_written += len(written)
    if work.failures:
        work.state.last_error = (
            f"{len(work.failures)} record(s) failed to render; "
            f"first: {work.failures[0]['error']}"
        )
    else:
        work.state.last_error = None

    return {
        "status": "ok",
        "notes_written": len(written),
        "failed": len(work.failures),
        "has_more": work.has_more,
    }


async def _queue_chained_run(
    db: AsyncSession,
    user: User,
    domains: list[ExportDomain],
    work_by_domain: dict[str, _DomainWork],
    since_override: datetime | None,
    chain: int,
    now: datetime,
) -> None:
    chain_payload: dict[str, Any] = {
        "domains": [d.name for d in domains],
        "chain": chain + 1,
    }
    # A `since` backfill doesn't persist its position (advance_watermark
    # refuses to rewind), so the follow-up run has to be told where this one
    # stopped — otherwise it would restart from the same `since` and loop
    # over the same page until MAX_CHAINED_RUNS.
    if since_override is not None:
        cursors = [
            w.new_watermark_ts
            for w in work_by_domain.values()
            if w.has_more and w.new_watermark_ts is not None
        ]
        if cursors:
            chain_payload["since"] = min(cursors).isoformat()
    await jobs.enqueue(db, user, jobs.EXPORT_DAG_ID, chain_payload, requested_at=now)


__all__ = ["MAX_CHAINED_RUNS", "MAX_NOTES_PER_RUN", "export_notes"]
