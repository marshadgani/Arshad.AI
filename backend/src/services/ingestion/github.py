"""GitHub activity ingestion runner — orchestration.

Pulls issues + PRs for each repo in ``payload.repos`` (caller must supply
at least one). Both go into ingested_github_activity keyed by
(user_id, kind, provider_id) so issue#3 and pr#3 don't collide.

This module owns the *flow* only. The three concerns it used to inline
now live beside it, each with a single reason to change:

* ``github_mapping`` — GitHub's payload shape → our row shape (pure).
* ``github_store``   — rows → Postgres (the only SQLAlchemy in the path).
* ``github_outcome`` — run bookkeeping and the published result shape.

Freshness contract: a terminal-state transition (merged, closed) is
reconciled into ``raw`` within one ingestion cycle, for any item still
within the most recently-updated ``MAX_INGEST_BATCH_SIZE`` items of its
repo. This is guaranteed by always requesting ``state=all`` — the
``open``-only filter this module used to apply on incremental runs meant
a PR that got merged (or an issue that got closed) between runs was never
re-fetched, so the dashboard projections' merged/closed logic was dead
code in production. ``payload.full_refresh`` is accepted for backward
compatibility but no longer changes the state filter.

Each repo is fetched and written independently: complete both HTTP calls
for a repo, then open a short write transaction and commit, before moving
to the next repo. This keeps no transaction open across a network call
(per database.md) and means one bad repo (revoked scope, 404, rate
limit) doesn't take down the rest of the feed — its failure is recorded
in ``failed_repos`` and the run is reported as ``partial`` rather than a
silent clean success.

Three failure layers are isolated per-repo so a single bad repo, however
it fails, can never abort the whole run: the provider-tool layer
(``ToolError`` — auth, rate limit, 404), the transport layer
(``httpx.HTTPError`` — connect/read timeout, DNS failure, malformed
response body, none of which ``tools/clients/github.py`` converts to a
``ToolError``) and the write layer (``SQLAlchemyError`` — constraint
violation, connection drop during commit). A timeout is the single most
likely per-repo failure in production, so leaving it uncaught would make
the isolation contract above false exactly when it matters most. Any
*other* exception is a real defect rather than a per-repo fault: it rolls
back and propagates, because swallowing it into a "partial" success would
hide the defect behind a green run.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.base import ToolError
from ...tools.github.list_issues import GitHubListIssues, ListIssuesInput
from ...tools.github.list_prs import GitHubListPrs, ListPrsInput
from .. import event_bus
from . import github_mapping as mapping
from . import github_store as store
from .config import field_upper_bound, max_batch_size
from .github_outcome import IngestOutcome
from .runner import IngestionError

logger = logging.getLogger(__name__)

INGESTED_EVENT = "events.github.ingested"

# Always request every state, on every run. See the freshness contract in
# the module docstring — narrowing this to "open" is what previously made
# merged/closed reconciliation impossible.
_STATE_FILTER = "all"

# The largest ``max_results`` both list tools will accept, read off their
# own schemas. MAX_INGEST_BATCH_SIZE is one env var shared with the
# calendar and email runners, whose tools allow different maxima, so the
# operator-supplied value is not inherently valid here: anything above
# this raises a Pydantic ValidationError from _fetch_repo_items, and
# ValidationError is deliberately not in _REPO_FAILURE_POLICIES, so it
# escapes ingest() uncaught and fails every repo at once instead of
# degrading per-repo. Clamping to the schemas' own bound keeps the
# isolation contract in the module docstring true for any env value.
_MAX_RESULTS_BOUNDS = [
    bound
    for bound in (
        field_upper_bound(ListIssuesInput, "max_results"),
        field_upper_bound(ListPrsInput, "max_results"),
    )
    if bound is not None
]
_MAX_RESULTS_CEILING = min(_MAX_RESULTS_BOUNDS) if _MAX_RESULTS_BOUNDS else None


async def _ingest_repo(
    *, user: User, db: AsyncSession, repo: str, batch_size: int
) -> tuple[int, int, int]:
    """Fetch, map and write a single repo. Returns (issues, prs, skipped).

    Both provider calls complete before the write begins, so the write
    transaction never spans a network call. The tool classes are resolved
    from module scope on every call rather than bound at import time —
    that is what lets tests substitute the provider boundary here.

    Raises on any failure; isolating that failure to this repo is the
    caller's job.
    """
    issues_result = await GitHubListIssues()(
        user=user,
        db=db,
        payload=ListIssuesInput(repo=repo, state=_STATE_FILTER, max_results=batch_size),
    )
    prs_result = await GitHubListPrs()(
        user=user,
        db=db,
        payload=ListPrsInput(repo=repo, state=_STATE_FILTER, max_results=batch_size),
    )

    issues = mapping.build_activity_rows(
        user_id=user.id, repo=repo, kind="issue", items=issues_result.data
    )
    prs = mapping.build_activity_rows(
        user_id=user.id, repo=repo, kind="pr", items=prs_result.data
    )

    await store.upsert_activity_rows(db, issues.rows + prs.rows)

    return len(issues.rows), len(prs.rows), issues.skipped_count + prs.skipped_count


async def _record_repo_failure(
    *,
    db: AsyncSession,
    outcome: IngestOutcome,
    repo: str,
    code: str,
    message: str,
    log_event: str,
    log_extra: dict[str, Any],
    with_traceback: bool = False,
) -> None:
    """Roll back this repo's aborted transaction and register the failure.

    Every per-repo failure path goes through here so the rollback that
    must precede recording one is written once.
    """
    await db.rollback()
    outcome.record_failure(repo, code, message)

    emit = logger.exception if with_traceback else logger.warning
    emit(log_event, extra={"repo": repo, **log_extra})


async def _ingest_repo_isolated(
    *, user: User, db: AsyncSession, repo: str, batch_size: int, outcome: IngestOutcome
) -> None:
    """Ingest one repo, folding success or a known failure into ``outcome``."""
    try:
        issue_rows, pr_rows, skipped = await _ingest_repo(
            user=user, db=db, repo=repo, batch_size=batch_size
        )
    except ToolError as exc:
        await _record_repo_failure(
            db=db,
            outcome=outcome,
            repo=repo,
            code=exc.code,
            message=exc.message,
            log_event="github_ingest_repo_failed",
            log_extra={"code": exc.code, "error_message": exc.message},
        )
    except httpx.HTTPError as exc:
        # tools/clients/github.py only converts HTTP *status* codes into
        # ToolError; a transport-level failure (connect/read timeout, DNS,
        # connection reset, unparseable body) escapes as a raw httpx error,
        # so it gets its own code rather than being reported as a provider
        # rejection the user could act on.
        await _record_repo_failure(
            db=db,
            outcome=outcome,
            repo=repo,
            code="github_ingest_provider_unreachable",
            message=f"{type(exc).__name__}: {exc}",
            log_event="github_ingest_repo_transport_failed",
            log_extra={"error_message": str(exc)},
        )
    except SQLAlchemyError as exc:
        # Reached from either the tools' own DB reads (token lookup) or the
        # upsert. It is the one case with no provider-supplied explanation,
        # so the traceback is the only diagnostic available.
        await _record_repo_failure(
            db=db,
            outcome=outcome,
            repo=repo,
            code="github_ingest_write_failed",
            message=str(exc),
            log_event="github_ingest_repo_write_failed",
            log_extra={},
            with_traceback=True,
        )
    except Exception:
        # Not a per-repo fault — propagate. This repo's transaction is
        # still open on `db`, and letting it dangle would leave the session
        # unusable for whatever the caller does next, so roll back first.
        await db.rollback()
        raise
    else:
        outcome.record_repo(issue_rows=issue_rows, pr_rows=pr_rows, skipped=skipped)


def _parse_repos(payload: dict[str, Any]) -> list[str]:
    repos: list[str] = payload.get("repos") or []
    if not repos:
        raise IngestionError(
            "github_repos_required: payload.repos must list at least one owner/name"
        )
    return repos


async def ingest(
    *, user: User, db: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    repos = _parse_repos(payload)
    batch_size = max_batch_size(ceiling=_MAX_RESULTS_CEILING)
    outcome = IngestOutcome()

    for repo in repos:
        await _ingest_repo_isolated(
            user=user, db=db, repo=repo, batch_size=batch_size, outcome=outcome
        )

    if outcome.every_repo_failed(len(repos)):
        raise IngestionError(f"github_all_repos_failed: {outcome.failure_summary()}")

    result = outcome.as_payload()

    # event_bus.publish is Redis pub/sub — fire-and-forget by its own
    # contract (see services/event_bus.py) and best-effort here too: the
    # writes above are already committed, so a broker hiccup (Redis down,
    # no subscribers, connection reset) must not turn an already-correct
    # ``ok``/``partial`` result into a raised exception the queue worker
    # would treat as a failed run. Matches the same guard already used in
    # obsidian.py / ontology/pipeline.py for this exact call.
    try:
        await event_bus.publish(
            INGESTED_EVENT,
            {"user_id": str(user.id), "repos": repos, **result},
        )
    except Exception as exc:
        logger.warning(
            "github_ingest_event_publish_failed",
            extra={"user_id": str(user.id), "repos": repos, "error_message": str(exc)},
        )

    return result
