"""TC-001 through TC-004 — SyncResult dataclass: mode and job_id fields.

REQUIREMENTS COVERED:
  REQ-T01  SyncResult defaults mode='completed', job_id=None (backward compat)
  REQ-T02  SyncResult accepts mode='enqueued' + explicit job_id
  REQ-T03  DAG-backed providers expose sync_dag_id class var matching the expected DAG
  REQ-T04  Synchronous providers have sync_dag_id = None
"""

from __future__ import annotations

import pytest
from src.integrations.base import SyncResult


class TestSyncResultDefaults:
    """TC-001 — SyncResult must be backward-compatible for the ~24 synchronous providers."""

    def test_mode_defaults_to_completed(self):
        r = SyncResult(rows_written=5, summary="ok", duration_ms=100)
        assert r.mode == "completed"

    def test_job_id_defaults_to_none(self):
        r = SyncResult(rows_written=5, summary="ok", duration_ms=100)
        assert r.job_id is None

    def test_all_required_fields_present(self):
        r = SyncResult(rows_written=0, summary="done", duration_ms=1)
        assert hasattr(r, "rows_written")
        assert hasattr(r, "summary")
        assert hasattr(r, "duration_ms")
        assert hasattr(r, "mode")
        assert hasattr(r, "job_id")


class TestSyncResultEnqueuedMode:
    """TC-002 — SyncResult with mode='enqueued' + job_id used by DAG-backed providers."""

    def test_accepts_enqueued_mode_with_job_id(self):
        r = SyncResult(
            rows_written=0,
            summary="Sync enqueued.",
            duration_ms=5,
            mode="enqueued",
            job_id="abc-123",
        )
        assert r.mode == "enqueued"
        assert r.job_id == "abc-123"

    def test_rows_written_zero_for_enqueued(self):
        r = SyncResult(
            rows_written=0,
            summary="Sync enqueued.",
            duration_ms=5,
            mode="enqueued",
            job_id="abc-123",
        )
        assert r.rows_written == 0


class TestSyncDagIdDeclarations:
    """TC-003 — Each DAG-backed provider declares the correct sync_dag_id."""

    def test_google_calendar_sync_dag_id(self):
        from src.integrations.personal.google_calendar import GoogleCalendarIntegration

        assert GoogleCalendarIntegration.sync_dag_id == "calendar_ingestor"

    def test_gmail_sync_dag_id(self):
        from src.integrations.personal.gmail import GmailIntegration

        assert GmailIntegration.sync_dag_id == "email_ingestor"

    def test_github_sync_dag_id(self):
        from src.integrations.personal.github import GitHubIntegration

        assert GitHubIntegration.sync_dag_id == "github_ingestor"


class TestSynchronousProviderNoDagId:
    """TC-004 — A non-DAG-backed provider must not set sync_dag_id."""

    def test_base_provider_sync_dag_id_default_is_none(self):
        from src.integrations.base import IntegrationProvider

        assert IntegrationProvider.sync_dag_id is None

    def test_shopify_has_no_sync_dag_id(self):
        try:
            from src.integrations.personal.shopify import ShopifyIntegration

            assert ShopifyIntegration.sync_dag_id is None
        except ImportError:
            pytest.skip("Shopify provider not present in this build")
