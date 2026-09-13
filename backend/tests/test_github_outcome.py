"""Unit tests for ``src/services/ingestion/github_outcome.py``.

FEAT-139 gap: ``IngestOutcome`` is the single source of truth for both the
event-bus payload and ``ingest()``'s return value (``as_payload()``), and
the escalation decision (``every_repo_failed``) that turns a bad run into
a retried ``IngestionError`` — none of it had a direct unit test; the
existing ingestion tests only observe its effects through ``ingest()``.
Pure dataclass logic, no I/O.
"""

from __future__ import annotations

from src.services.ingestion.github_outcome import IngestOutcome


def test_status_ok_when_no_failures():
    outcome = IngestOutcome()
    outcome.record_repo(issue_rows=3, pr_rows=2, skipped=0)

    assert outcome.status == "ok"
    assert outcome.ingested_count == 5
    assert outcome.issue_count == 3
    assert outcome.pr_count == 2


def test_status_partial_when_any_repo_fails():
    outcome = IngestOutcome()
    outcome.record_repo(issue_rows=2, pr_rows=1, skipped=0)
    outcome.record_failure("org/bad", "github_forbidden", "scope denied")

    assert outcome.status == "partial"
    assert len(outcome.failures) == 1
    assert outcome.failures[0].code == "github_forbidden"


def test_every_repo_failed_true_only_when_all_fail():
    outcome = IngestOutcome()
    outcome.record_failure("org/a", "github_forbidden", "denied")
    outcome.record_failure("org/b", "provider_request_failed", "404")

    assert outcome.every_repo_failed(2) is True


def test_every_repo_failed_false_when_some_succeed():
    outcome = IngestOutcome()
    outcome.record_repo(issue_rows=1, pr_rows=0, skipped=0)
    outcome.record_failure("org/b", "github_forbidden", "denied")

    assert outcome.every_repo_failed(2) is False


def test_every_repo_failed_false_when_zero_attempted():
    """Zero repos attempted is not a 'total failure' -- there was nothing
    to fail, so escalating to IngestionError would be wrong."""
    outcome = IngestOutcome()
    assert outcome.every_repo_failed(0) is False


def test_as_payload_shape_matches_api_contract():
    outcome = IngestOutcome()
    outcome.record_repo(issue_rows=5, pr_rows=3, skipped=1)
    outcome.record_failure("org/x", "github_forbidden", "denied")

    payload = outcome.as_payload()

    assert payload == {
        "ingested_count": 8,
        "issue_count": 5,
        "pr_count": 3,
        "skipped_count": 1,
        "failed_repos": [
            {"repo": "org/x", "code": "github_forbidden", "message": "denied"}
        ],
        "status": "partial",
    }


def test_failure_summary_joins_repo_and_code():
    outcome = IngestOutcome()
    outcome.record_failure("org/a", "github_forbidden", "denied")
    outcome.record_failure("org/b", "provider_request_failed", "404")

    assert (
        outcome.failure_summary()
        == "org/a: github_forbidden; org/b: provider_request_failed"
    )
