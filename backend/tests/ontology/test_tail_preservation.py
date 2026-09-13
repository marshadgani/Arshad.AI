"""Unit tests — SEC-002 fix: user-authored tail preservation on rewrite.

Covers:
- render.extract_user_tail() round-trips exactly what render_entity wrote
- pipeline._rewrite_targets() only flags pre-existing, non-MOC notes
- pipeline._preserve_user_tails() merges a fetched tail back into the
  rendered note and recomputes the plan against the merged content

All tests are pure / mocked — zero real network or DB I/O.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from src.models.ontology import OntologyEntityNote
from src.services.ingestion.ontology import pipeline as pipeline_mod
from src.services.ingestion.ontology.compose import ComposedNotes
from src.services.ingestion.ontology.diff import plan_changes
from src.services.ingestion.ontology.render import (
    MANAGED_END,
    extract_user_tail,
    render_entity,
)
from src.services.ingestion.ontology.resolve import ResolveResult


def _row(
    stable_entity_id: str = "event:tail1",
    entity_type: str = "Event",
    domain: str = "calendar",
    blob_sha: str = "",
) -> OntologyEntityNote:
    row = OntologyEntityNote()
    row.id = uuid.uuid4()
    row.user_id = uuid.uuid4()
    row.stable_entity_id = stable_entity_id
    row.entity_type = entity_type
    row.domain = domain
    row.display_name = "Team Standup"
    row.source_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row.tags = []
    row.relationships = []
    row.sync_state = "pending"
    row.blob_sha = blob_sha
    row.vault_path = f"entities/{domain}/{entity_type}/{stable_entity_id}.md"
    return row


# ── extract_user_tail round-trip ────────────────────────────────────
def test_extract_user_tail_round_trips_render_entity_tail():
    row = _row()
    tail = "\n## My Notes\nSome personal insight."
    rendered = render_entity(row, {}, user_tail=tail)
    assert extract_user_tail(rendered) == tail


def test_extract_user_tail_empty_when_no_tail():
    row = _row()
    rendered = render_entity(row, {}, user_tail=None)
    assert extract_user_tail(rendered) == ""


def test_extract_user_tail_empty_when_no_managed_markers():
    assert extract_user_tail("just a random note with no markers") == ""


def test_extract_user_tail_empty_for_none_input():
    assert extract_user_tail(None) == ""


def test_extract_user_tail_contains_marker_string_itself_still_splits_correctly():
    # Sanity: MANAGED_END appearing exactly once is the only supported shape.
    text = f"---\nfoo: bar\n---\n\n<!-- x -->\nbody{MANAGED_END}\ntail content"
    assert extract_user_tail(text) == "tail content"


# ── _rewrite_targets ─────────────────────────────────────────────────
def test_rewrite_targets_excludes_moc_entities():
    moc_row = _row(stable_entity_id="moc:calendar", entity_type="MOC", blob_sha="abc")
    event_row = _row(stable_entity_id="event:e1", entity_type="Event", blob_sha="abc")
    rows_by_path = {moc_row.vault_path: moc_row, event_row.vault_path: event_row}
    plan = plan_changes(
        {moc_row.vault_path: "new moc text", event_row.vault_path: "new event text"},
        {moc_row.vault_path: "old", event_row.vault_path: "old"},
        [],
    )
    targets = pipeline_mod._rewrite_targets(plan, rows_by_path)
    assert targets == [event_row.vault_path]


def test_rewrite_targets_excludes_brand_new_notes():
    """A note never synced before (blob_sha == '') has nothing to preserve."""
    new_row = _row(stable_entity_id="event:new1", blob_sha="")
    rows_by_path = {new_row.vault_path: new_row}
    plan = plan_changes({new_row.vault_path: "text"}, {}, [])
    targets = pipeline_mod._rewrite_targets(plan, rows_by_path)
    assert targets == []


def test_rewrite_targets_includes_previously_synced_rewritten_note():
    row = _row(stable_entity_id="event:existing1", blob_sha="deadbeef")
    rows_by_path = {row.vault_path: row}
    plan = plan_changes({row.vault_path: "new text"}, {row.vault_path: "old_sha"}, [])
    targets = pipeline_mod._rewrite_targets(plan, rows_by_path)
    assert targets == [row.vault_path]


# ── _preserve_user_tails ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_preserve_user_tails_merges_fetched_tail_and_recomputes_plan():
    row = _row(stable_entity_id="event:merge1", blob_sha="deadbeef")
    resolved = ResolveResult(
        db_rows=[row],
        link_map={},
        rename_ops=[],
        dropped_duplicates=0,
        dropped_relationships=0,
    )
    no_tail_text = render_entity(row, {}, user_tail=None)
    composed = ComposedNotes(
        by_path={row.vault_path: no_tail_text}, unresolved_relationships=0
    )
    plan = plan_changes({row.vault_path: no_tail_text}, {row.vault_path: "old_sha"}, [])

    existing_live_content = render_entity(
        row, {}, user_tail="\n## Kept\nDo not delete me."
    )

    with patch.object(
        pipeline_mod,
        "fetch_blob",
        new=AsyncMock(return_value=(existing_live_content, "sha123")),
    ):
        new_plan = await pipeline_mod._preserve_user_tails(
            db=AsyncMock(),
            user=AsyncMock(),
            repo="owner/vault",
            composed=composed,
            resolved=resolved,
            plan=plan,
        )

    merged_text = composed.by_path[row.vault_path]
    assert "Do not delete me." in merged_text
    assert new_plan.written_count == 1


@pytest.mark.asyncio
async def test_preserve_user_tails_no_targets_returns_same_plan_without_fetching():
    row = _row(
        stable_entity_id="event:notouch1", blob_sha=""
    )  # never synced -> not a target
    resolved = ResolveResult(
        db_rows=[row],
        link_map={},
        rename_ops=[],
        dropped_duplicates=0,
        dropped_relationships=0,
    )
    text = render_entity(row, {}, user_tail=None)
    composed = ComposedNotes(by_path={row.vault_path: text}, unresolved_relationships=0)
    plan = plan_changes({row.vault_path: text}, {}, [])

    fetch_mock = AsyncMock()
    with patch.object(pipeline_mod, "fetch_blob", new=fetch_mock):
        result_plan = await pipeline_mod._preserve_user_tails(
            db=AsyncMock(),
            user=AsyncMock(),
            repo="owner/vault",
            composed=composed,
            resolved=resolved,
            plan=plan,
        )
    fetch_mock.assert_not_called()
    assert result_plan is plan


@pytest.mark.asyncio
async def test_preserve_user_tails_skips_404_without_raising():
    """If the note was deleted from the vault out-of-band, there's nothing
    to preserve — must not raise, must not block the rewrite."""
    from src.tools.base import ToolError

    row = _row(stable_entity_id="event:gone1", blob_sha="deadbeef")
    resolved = ResolveResult(
        db_rows=[row],
        link_map={},
        rename_ops=[],
        dropped_duplicates=0,
        dropped_relationships=0,
    )
    text = render_entity(row, {}, user_tail=None)
    composed = ComposedNotes(by_path={row.vault_path: text}, unresolved_relationships=0)
    plan = plan_changes({row.vault_path: text}, {row.vault_path: "old_sha"}, [])

    async def _raise_not_found(*args, **kwargs):
        raise ToolError("obsidian_not_found", "gone")

    with patch.object(pipeline_mod, "fetch_blob", new=_raise_not_found):
        result_plan = await pipeline_mod._preserve_user_tails(
            db=AsyncMock(),
            user=AsyncMock(),
            repo="owner/vault",
            composed=composed,
            resolved=resolved,
            plan=plan,
        )
    # Content stays the tail=None render — nothing was merged.
    assert composed.by_path[row.vault_path] == text
    assert result_plan is plan
