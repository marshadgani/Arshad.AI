"""Pass 4 — the vault write port.

The only module in the ontology package that knows GitHub exists. It
takes transport-agnostic ``NoteChange`` objects, spends the API budget,
and returns a ``PublishOutcome`` describing what happened in the
pipeline's own vocabulary (committed, or deferred with a reason that
matches ``OntologySyncRun.error_code``).

Collapsing the three previously-duplicated "mark everything deferred and
bail" branches into one outcome type is the point: the pipeline now has
a single deferral path, and adding a new deferral cause is a new
``DeferReason`` here, not a fourth copy of the same six lines there.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.user import User
from ...obsidian_git_data import (
    ObsidianGitDataClient,
    OntologyConcurrentWriteError,
    OntologyRateLimitError,
    TreeEntry,
)
from .diff import NoteChange

# Floor on remaining GitHub core quota before a run is even attempted.
# A commit costs ~7 calls (rate_limit, repo, ref, commit lookup, tree,
# commit, ref patch); 8 is a safe round-number margin above that before
# we even look at payload size.
MIN_API_BUDGET = 8

# Values recorded in OntologySyncRun.error_code / entity conflict_reason.
DEFER_RATE_LIMIT = "rate_limit"
DEFER_CONCURRENT_WRITE = "concurrent_write"


@dataclass(frozen=True)
class PublishOutcome:
    commit_sha: str | None = None
    branch: str | None = None
    defer_reason: str | None = None
    # Only populated when the pre-flight budget check is what deferred
    # the run — a mid-flight 403 tells us nothing reliable about quota.
    rate_remaining: int | None = None


def _tree_entries(changes: list[NoteChange]) -> list[TreeEntry]:
    return [
        TreeEntry(path=change.path, delete=True)
        if change.is_delete
        else TreeEntry(path=change.path, content=change.content)
        for change in changes
    ]


class VaultWriter:
    """Publishes a whole run as ONE vault commit, or defers it."""

    def __init__(self, *, db: AsyncSession, user: User, repo: str) -> None:
        self._client = ObsidianGitDataClient(db=db, user=user, repo=repo)

    async def publish(
        self, changes: list[NoteChange], *, message: str
    ) -> PublishOutcome:
        # One GitHub connection (and one auth-header fetch) for the whole
        # run — see ObsidianGitDataClient's docstring. `aclose()` in
        # `finally` guarantees it's released on every exit path,
        # including the two early-return branches below.
        try:
            rate = await self._client.get_rate_limit()
            if rate["remaining"] < MIN_API_BUDGET:
                return PublishOutcome(
                    defer_reason=DEFER_RATE_LIMIT, rate_remaining=rate["remaining"]
                )

            branch = await self._client.resolve_default_branch()
            try:
                commit_sha = await self._client.commit_paths(
                    branch=branch,
                    entries=_tree_entries(changes),
                    message=message,
                )
            except OntologyRateLimitError:
                return PublishOutcome(defer_reason=DEFER_RATE_LIMIT)
            except OntologyConcurrentWriteError:
                return PublishOutcome(defer_reason=DEFER_CONCURRENT_WRITE)
            return PublishOutcome(commit_sha=commit_sha, branch=branch)
        finally:
            await self._client.aclose()
