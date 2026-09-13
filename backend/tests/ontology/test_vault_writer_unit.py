"""Unit tests — vault_writer.py (BPDD point 6: GitHub Contents/Git-Data
API rate-limit awareness).

This is the ONLY module that knows GitHub exists, and the pre-flight
rate-limit budget check here (``MIN_API_BUDGET``) is the concrete
implementation of the requirement's rate-limit-awareness clause. It had
zero test coverage before this file. Every test mocks
``ObsidianGitDataClient`` so nothing here makes a network call.

Covers TC-100 through TC-108.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from src.models.user import User
from src.services.ingestion.ontology.diff import NoteChange
from src.services.ingestion.ontology.vault_writer import (
    DEFER_CONCURRENT_WRITE,
    DEFER_RATE_LIMIT,
    MIN_API_BUDGET,
    VaultWriter,
    _tree_entries,
)
from src.services.obsidian_git_data import (
    OntologyConcurrentWriteError,
    OntologyRateLimitError,
    TreeEntry,
)


def _user() -> User:
    u = User()
    u.id = uuid.uuid4()
    u.email = "vault_writer_test@example.com"
    return u


def _writer_with_fake_client(fake_client) -> VaultWriter:
    with patch(
        "src.services.ingestion.ontology.vault_writer.ObsidianGitDataClient",
        return_value=fake_client,
    ):
        return VaultWriter(
            db=AsyncMock(), user=_user(), repo="marshadgani/Obsidian-Vault"
        )


# ── TC-100 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_defers_preflight_when_budget_too_low():
    """remaining below MIN_API_BUDGET must defer BEFORE any branch/commit
    call is made — the whole point of a pre-flight check is spending
    zero further quota on a run that can't finish."""
    fake_client = AsyncMock()
    fake_client.get_rate_limit = AsyncMock(
        return_value={"remaining": MIN_API_BUDGET - 1}
    )
    writer = _writer_with_fake_client(fake_client)

    outcome = await writer.publish(
        [NoteChange(path="a.md", content="x")], message="msg"
    )

    assert outcome.defer_reason == DEFER_RATE_LIMIT
    assert outcome.rate_remaining == MIN_API_BUDGET - 1
    assert outcome.commit_sha is None
    fake_client.resolve_default_branch.assert_not_called()
    fake_client.commit_paths.assert_not_called()


# ── TC-101 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_proceeds_when_budget_exactly_at_floor():
    """remaining == MIN_API_BUDGET must NOT defer — the check is a strict
    '<', so the documented floor value itself is still spendable."""
    fake_client = AsyncMock()
    fake_client.get_rate_limit = AsyncMock(return_value={"remaining": MIN_API_BUDGET})
    fake_client.resolve_default_branch = AsyncMock(return_value="main")
    fake_client.commit_paths = AsyncMock(return_value="commitsha123")
    writer = _writer_with_fake_client(fake_client)

    outcome = await writer.publish(
        [NoteChange(path="a.md", content="x")], message="msg"
    )

    assert outcome.defer_reason is None
    assert outcome.commit_sha == "commitsha123"
    assert outcome.branch == "main"


# ── TC-102 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_defers_on_midflight_rate_limit_without_remaining_figure():
    """A 403/rate-limit raised DURING commit_paths (after the pre-flight
    check passed) must still defer — but rate_remaining stays None,
    because a mid-flight 403 tells us nothing reliable about quota
    (docstring in PublishOutcome)."""
    fake_client = AsyncMock()
    fake_client.get_rate_limit = AsyncMock(return_value={"remaining": 100})
    fake_client.resolve_default_branch = AsyncMock(return_value="main")
    fake_client.commit_paths = AsyncMock(side_effect=OntologyRateLimitError())
    writer = _writer_with_fake_client(fake_client)

    outcome = await writer.publish(
        [NoteChange(path="a.md", content="x")], message="msg"
    )

    assert outcome.defer_reason == DEFER_RATE_LIMIT
    assert outcome.rate_remaining is None
    assert outcome.commit_sha is None


# ── TC-103 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_defers_on_concurrent_write():
    """A 422 from the ref update (ObsidianGitDataClient already retried
    once internally) must defer with DEFER_CONCURRENT_WRITE, distinct
    from a rate-limit defer, so the audit trail records the real cause."""
    fake_client = AsyncMock()
    fake_client.get_rate_limit = AsyncMock(return_value={"remaining": 100})
    fake_client.resolve_default_branch = AsyncMock(return_value="main")
    fake_client.commit_paths = AsyncMock(side_effect=OntologyConcurrentWriteError())
    writer = _writer_with_fake_client(fake_client)

    outcome = await writer.publish(
        [NoteChange(path="a.md", content="x")], message="msg"
    )

    assert outcome.defer_reason == DEFER_CONCURRENT_WRITE
    assert outcome.commit_sha is None


# ── TC-104 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_success_returns_commit_sha_and_branch():
    fake_client = AsyncMock()
    fake_client.get_rate_limit = AsyncMock(return_value={"remaining": 500})
    fake_client.resolve_default_branch = AsyncMock(return_value="main")
    fake_client.commit_paths = AsyncMock(return_value="abc123def")
    writer = _writer_with_fake_client(fake_client)

    outcome = await writer.publish(
        [NoteChange(path="a.md", content="hello")], message="ontology sync: 1 note(s)"
    )

    assert outcome.commit_sha == "abc123def"
    assert outcome.branch == "main"
    assert outcome.defer_reason is None
    assert outcome.rate_remaining is None


# ── TC-105 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_publish_passes_message_and_branch_through_to_commit_paths():
    fake_client = AsyncMock()
    fake_client.get_rate_limit = AsyncMock(return_value={"remaining": 500})
    fake_client.resolve_default_branch = AsyncMock(return_value="develop")
    fake_client.commit_paths = AsyncMock(return_value="sha1")
    writer = _writer_with_fake_client(fake_client)

    await writer.publish([NoteChange(path="a.md", content="x")], message="the message")

    _, kwargs = fake_client.commit_paths.call_args
    assert kwargs["branch"] == "develop"
    assert kwargs["message"] == "the message"


# ── TC-106 ─────────────────────────────────────────────────────────
def test_tree_entries_delete_change_maps_to_delete_entry():
    changes = [NoteChange(path="gone.md", content=None)]
    entries = _tree_entries(changes)
    assert entries == [TreeEntry(path="gone.md", delete=True)]


# ── TC-107 ─────────────────────────────────────────────────────────
def test_tree_entries_write_change_maps_to_content_entry():
    changes = [NoteChange(path="new.md", content="hello world")]
    entries = _tree_entries(changes)
    assert entries == [TreeEntry(path="new.md", content="hello world")]


# ── TC-108 ─────────────────────────────────────────────────────────
def test_tree_entries_mixed_batch_preserves_order():
    changes = [
        NoteChange(path="a.md", content="A"),
        NoteChange(path="b.md", content=None),
        NoteChange(path="c.md", content="C"),
    ]
    entries = _tree_entries(changes)
    assert [e.path for e in entries] == ["a.md", "b.md", "c.md"]
    assert entries[1].delete is True
    assert entries[0].delete is False and entries[2].delete is False
