"""Unit tests — pipeline.sync() orchestration.

pipeline.py had ZERO test coverage before this file even though it owns
every terminal outcome the ontology sync can produce (dry-run, no-op,
success, deferral for each ``DeferReason``, and the two failure paths
that must re-raise rather than swallow). Every dependency (extract,
resolve, compose, plan_changes, VaultWriter, SyncRunRecorder, event_bus)
is faked so this stays a pure orchestration test — no DB, no network.

Covers TC-090 through TC-099.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from src.models.ontology import OntologyEntityNote
from src.models.user import User
from src.services.ingestion.ontology import pipeline
from src.services.ingestion.ontology.compose import ComposedNotes
from src.services.ingestion.ontology.diff import DiffPlan, NoteChange
from src.services.ingestion.ontology.resolve import ResolveResult
from src.services.ingestion.ontology.vault_writer import PublishOutcome
from src.services.ingestion.runner import IngestionError
from src.tools.base import ProviderReauthRequired, ToolError


def _user() -> User:
    u = User()
    u.id = uuid.uuid4()
    u.email = "pipeline_test@example.com"
    return u


def _row(stable_id: str = "event:p1", vault_path: str = "p1.md") -> OntologyEntityNote:
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.stable_entity_id = stable_id
    row.vault_path = vault_path
    row.blob_sha = ""
    row.sync_state = "pending"
    return row


class _FakeRecorder:
    """Records every call made on it so tests can assert the terminal path taken."""

    def __init__(self, *_, **__) -> None:
        self.run_id = uuid.uuid4()
        self.calls: list[tuple[str, tuple, dict]] = []

    async def begin(self) -> None:
        self.calls.append(("begin", (), {}))

    async def complete(self, counts, *, commit_sha=None, branch=None) -> None:
        self.calls.append(
            ("complete", (counts,), {"commit_sha": commit_sha, "branch": branch})
        )

    async def defer(self, reason, rows) -> None:
        self.calls.append(("defer", (reason, list(rows)), {}))

    async def abandon(
        self, status, *, counts=None, error_code=None, dry_run=False
    ) -> None:
        self.calls.append(
            (
                "abandon",
                (status,),
                {"counts": counts, "error_code": error_code, "dry_run": dry_run},
            )
        )


def _patch_common(
    recorder: _FakeRecorder,
    *,
    resolved: ResolveResult,
    composed: ComposedNotes,
    plan: DiffPlan,
):
    return [
        patch.object(pipeline, "vault_repo", return_value="marshadgani/Obsidian-Vault"),
        patch.object(pipeline, "SyncRunRecorder", lambda **kw: recorder),
        patch.object(pipeline.extract, "collect", AsyncMock(return_value=[])),
        patch.object(pipeline, "navigation_records", return_value=[]),
        patch.object(pipeline, "resolve", AsyncMock(return_value=resolved)),
        patch.object(pipeline, "compose", lambda *a, **kw: composed),
        patch.object(pipeline, "plan_changes", lambda *a, **kw: plan),
    ]


def _enter_all(patches):
    started = [p.start() for p in patches]
    return started


def _exit_all(patches):
    for p in patches:
        p.stop()


# ── TC-090 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_dry_run_never_publishes_and_abandons_run():
    """dry_run=True must never touch VaultWriter and must abandon (not
    complete) the run, so a dry run leaves no audit-trail or DB trace."""
    user = _user()
    resolved = ResolveResult(
        link_map={"event:p1": ("p1.md", "P1")},
        rename_ops=[],
        db_rows=[_row()],
        dropped_duplicates=0,
    )
    composed = ComposedNotes(by_path={"p1.md": "content"}, unresolved_relationships=0)
    plan = DiffPlan(
        changes=[NoteChange(path="p1.md", content="content")],
        sha_by_path={"p1.md": "sha1"},
    )
    recorder = _FakeRecorder()
    patches = _patch_common(recorder, resolved=resolved, composed=composed, plan=plan)
    writer_mock = AsyncMock()
    patches.append(patch.object(pipeline, "VaultWriter", writer_mock))
    _enter_all(patches)
    try:
        result = await pipeline.sync(
            user=user, db=AsyncMock(), payload={"dry_run": True}
        )
    finally:
        _exit_all(patches)

    assert result["dry_run"] is True
    writer_mock.assert_not_called()
    assert recorder.calls[-1][0] == "abandon"
    assert recorder.calls[-1][1] == ("dry_run",)


# ── TC-091 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_no_changes_completes_without_publishing():
    """An empty/falsy DiffPlan short-circuits before VaultWriter is even
    constructed — a run with nothing to write must make zero GitHub calls."""
    user = _user()
    resolved = ResolveResult(
        link_map={}, rename_ops=[], db_rows=[], dropped_duplicates=0
    )
    composed = ComposedNotes(by_path={}, unresolved_relationships=0)
    plan = DiffPlan(changes=[], sha_by_path={})  # falsy
    recorder = _FakeRecorder()
    patches = _patch_common(recorder, resolved=resolved, composed=composed, plan=plan)
    writer_mock = AsyncMock()
    patches.append(patch.object(pipeline, "VaultWriter", writer_mock))
    _enter_all(patches)
    try:
        result = await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert result["status"] == "succeeded"
    assert result["created_or_updated"] == 0
    writer_mock.assert_not_called()
    assert recorder.calls[-1][0] == "complete"


# ── TC-092 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_success_publishes_marks_rows_synced_and_announces():
    """The happy path: VaultWriter succeeds, synced rows get blob_sha +
    sync_state='synced', the run completes, and the event fires."""
    user = _user()
    row = _row()
    resolved = ResolveResult(
        link_map={"event:p1": ("p1.md", "P1")},
        rename_ops=[],
        db_rows=[row],
        dropped_duplicates=0,
    )
    composed = ComposedNotes(by_path={"p1.md": "content"}, unresolved_relationships=0)
    plan = DiffPlan(
        changes=[NoteChange(path="p1.md", content="content")],
        sha_by_path={"p1.md": "sha-new"},
    )
    recorder = _FakeRecorder()
    patches = _patch_common(recorder, resolved=resolved, composed=composed, plan=plan)

    publish_mock = AsyncMock(
        return_value=PublishOutcome(commit_sha="deadbeef", branch="main")
    )
    writer_instance = AsyncMock()
    writer_instance.publish = publish_mock
    patches.append(patch.object(pipeline, "VaultWriter", lambda **kw: writer_instance))
    announce_mock = AsyncMock()
    patches.append(patch.object(pipeline, "_announce", announce_mock))
    _enter_all(patches)
    try:
        result = await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert result["status"] == "succeeded"
    assert result["commit_sha"] == "deadbeef"
    assert row.sync_state == "synced"
    assert row.blob_sha == "sha-new"
    announce_mock.assert_awaited_once()
    assert recorder.calls[-1][0] == "complete"
    assert recorder.calls[-1][1][0]["created_or_updated"] == 1


# ── TC-093 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_defers_on_rate_limit_and_reports_remaining():
    """BPDD point 6 — rate-limit awareness: when VaultWriter defers for
    rate_limit, the run is recorded as deferred (never as failed or
    succeeded) and the remaining-quota figure is surfaced to the caller."""
    user = _user()
    row = _row()
    resolved = ResolveResult(
        link_map={"event:p1": ("p1.md", "P1")},
        rename_ops=[],
        db_rows=[row],
        dropped_duplicates=0,
    )
    composed = ComposedNotes(by_path={"p1.md": "content"}, unresolved_relationships=0)
    plan = DiffPlan(
        changes=[NoteChange(path="p1.md", content="content")],
        sha_by_path={"p1.md": "sha-new"},
    )
    recorder = _FakeRecorder()
    patches = _patch_common(recorder, resolved=resolved, composed=composed, plan=plan)

    publish_mock = AsyncMock(
        return_value=PublishOutcome(defer_reason="rate_limit", rate_remaining=2)
    )
    writer_instance = AsyncMock()
    writer_instance.publish = publish_mock
    patches.append(patch.object(pipeline, "VaultWriter", lambda **kw: writer_instance))
    _enter_all(patches)
    try:
        result = await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert result["status"] == "deferred"
    assert result["reason"] == "rate_limit"
    assert result["remaining"] == 2
    # Deferred rows are parked, not marked synced.
    assert row.sync_state != "synced"
    assert recorder.calls[-1][0] == "defer"
    assert recorder.calls[-1][1][0] == "rate_limit"


# ── TC-094 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_defers_on_concurrent_write_without_remaining_key():
    """A concurrent-write defer has no rate_remaining figure — the result
    dict must omit 'remaining' rather than report a stale/undefined value."""
    user = _user()
    row = _row()
    resolved = ResolveResult(
        link_map={"event:p1": ("p1.md", "P1")},
        rename_ops=[],
        db_rows=[row],
        dropped_duplicates=0,
    )
    composed = ComposedNotes(by_path={"p1.md": "content"}, unresolved_relationships=0)
    plan = DiffPlan(
        changes=[NoteChange(path="p1.md", content="content")],
        sha_by_path={"p1.md": "sha-new"},
    )
    recorder = _FakeRecorder()
    patches = _patch_common(recorder, resolved=resolved, composed=composed, plan=plan)

    publish_mock = AsyncMock(
        return_value=PublishOutcome(defer_reason="concurrent_write")
    )
    writer_instance = AsyncMock()
    writer_instance.publish = publish_mock
    patches.append(patch.object(pipeline, "VaultWriter", lambda **kw: writer_instance))
    _enter_all(patches)
    try:
        result = await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert result["status"] == "deferred"
    assert result["reason"] == "concurrent_write"
    assert "remaining" not in result


# ── TC-095 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_reraises_provider_reauth_and_abandons_run():
    """A ProviderReauthRequired from anywhere in the pipeline must
    propagate to the caller (so the API/dag-worker layer can surface a
    re-auth prompt) — never be swallowed into a success/failure dict."""
    user = _user()
    recorder = _FakeRecorder()
    patches = [
        patch.object(pipeline, "vault_repo", return_value="marshadgani/Obsidian-Vault"),
        patch.object(pipeline, "SyncRunRecorder", lambda **kw: recorder),
        patch.object(
            pipeline.extract,
            "collect",
            AsyncMock(side_effect=ProviderReauthRequired("github")),
        ),
    ]
    _enter_all(patches)
    try:
        with pytest.raises(ProviderReauthRequired):
            await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert recorder.calls[-1] == (
        "abandon",
        ("failed",),
        {"counts": None, "error_code": "provider_reauth_required", "dry_run": False},
    )


# ── TC-096 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_wraps_tool_error_as_ingestion_error_and_abandons_run():
    """A ToolError anywhere in the pipeline is recorded as a failed run
    (with its code) and re-raised as IngestionError — never masked as a
    quiet success."""
    user = _user()
    recorder = _FakeRecorder()
    boom = ToolError("obsidian_api_error", "GitHub returned 500.")
    patches = [
        patch.object(pipeline, "vault_repo", return_value="marshadgani/Obsidian-Vault"),
        patch.object(pipeline, "SyncRunRecorder", lambda **kw: recorder),
        patch.object(pipeline.extract, "collect", AsyncMock(side_effect=boom)),
    ]
    _enter_all(patches)
    try:
        with pytest.raises(IngestionError):
            await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert recorder.calls[-1][0] == "abandon"
    assert recorder.calls[-1][2]["error_code"] == "obsidian_api_error"


# ── TC-097 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sync_announce_failure_does_not_fail_the_run():
    """event_bus.publish failing after a successful commit must be
    best-effort — the sync() call itself must still report success since
    the commit already landed."""
    user = _user()
    row = _row()
    resolved = ResolveResult(
        link_map={"event:p1": ("p1.md", "P1")},
        rename_ops=[],
        db_rows=[row],
        dropped_duplicates=0,
    )
    composed = ComposedNotes(by_path={"p1.md": "content"}, unresolved_relationships=0)
    plan = DiffPlan(
        changes=[NoteChange(path="p1.md", content="content")],
        sha_by_path={"p1.md": "sha-new"},
    )
    recorder = _FakeRecorder()
    patches = _patch_common(recorder, resolved=resolved, composed=composed, plan=plan)

    publish_mock = AsyncMock(
        return_value=PublishOutcome(commit_sha="c0ffee", branch="main")
    )
    writer_instance = AsyncMock()
    writer_instance.publish = publish_mock
    patches.append(patch.object(pipeline, "VaultWriter", lambda **kw: writer_instance))
    patches.append(
        patch.object(
            pipeline.event_bus,
            "publish",
            AsyncMock(side_effect=RuntimeError("bus down")),
        )
    )
    _enter_all(patches)
    try:
        result = await pipeline.sync(user=user, db=AsyncMock(), payload={})
    finally:
        _exit_all(patches)

    assert result["status"] == "succeeded"
    assert result["commit_sha"] == "c0ffee"
