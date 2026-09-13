"""Run-level bookkeeping and the published result contract.

``as_payload()`` is the single definition of a run's result shape, used
verbatim for both the event bus payload and ``ingest()``'s return value,
so the queue worker's view of a run can never drift from its
subscribers'. This module imports nothing from the rest of the package:
it is pure accounting, testable without a session, user or provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Every repo wrote something (or had nothing to write) without error.
STATUS_OK = "ok"
# At least one repo failed and at least one succeeded. Deliberately not a
# clean success: a silent "ok" would let a permanently-broken repo rot out
# of the feed unnoticed.
STATUS_PARTIAL = "partial"


@dataclass(frozen=True)
class RepoFailure:
    """One repo's failure, already classified into a stable error code.

    ``code`` is machine-readable and safe to branch on downstream;
    ``message`` is for humans reading logs and the queue's error_text.
    """

    repo: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"repo": self.repo, "code": self.code, "message": self.message}


@dataclass
class IngestOutcome:
    """Mutable accumulator for a single ingestion run."""

    ingested_count: int = 0
    issue_count: int = 0
    pr_count: int = 0
    skipped_count: int = 0
    failures: list[RepoFailure] = field(default_factory=list)

    def record_repo(self, *, issue_rows: int, pr_rows: int, skipped: int) -> None:
        """Fold one successfully-written repo into the totals."""
        self.issue_count += issue_rows
        self.pr_count += pr_rows
        self.ingested_count += issue_rows + pr_rows
        self.skipped_count += skipped

    def record_failure(self, repo: str, code: str, message: str) -> None:
        """Fold one failed repo into the totals."""
        self.failures.append(RepoFailure(repo=repo, code=code, message=message))

    @property
    def status(self) -> str:
        return STATUS_PARTIAL if self.failures else STATUS_OK

    def every_repo_failed(self, attempted: int) -> bool:
        """True when no repo in the run produced a write.

        The caller escalates this to an ``IngestionError`` so the queue
        worker retries and eventually marks the job failed. A run where
        *some* repo succeeded is reported as partial instead, because
        failing the whole job would discard work already committed.
        """
        return attempted > 0 and len(self.failures) == attempted

    def failure_summary(self) -> str:
        """Compact ``repo: code`` list for the all-failed error message."""
        return "; ".join(f"{f.repo}: {f.code}" for f in self.failures)

    def as_payload(self) -> dict[str, object]:
        """The run's result shape. See the module docstring."""
        return {
            "ingested_count": self.ingested_count,
            "issue_count": self.issue_count,
            "pr_count": self.pr_count,
            "skipped_count": self.skipped_count,
            "failed_repos": [f.as_dict() for f in self.failures],
            "status": self.status,
        }
