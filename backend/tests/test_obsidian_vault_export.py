"""Orchestration tests for obsidian_vault_export.export (DB + git mocked)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.services.ingestion import obsidian_vault_export as ex
from src.services.ingestion.errors import IngestionError
from src.services.ingestion.obsidian_vault_git import PushResult

PERSON = {
    "id": uuid.uuid4(),
    "entity_type": "person",
    "external_key": "alice",
    "visibility": "public",
}
PROJECT = {
    "id": uuid.uuid4(),
    "entity_type": "project",
    "external_key": "o/r",
    "visibility": "public",
}
REL = {
    "source_key": "alice",
    "source_type": "person",
    "target_key": "o/r",
    "target_type": "project",
    "relationship_type": "contributed_to",
    "visibility": "public",
}


async def _run(ents, rels, push=None, db=None, payload=None):
    user = MagicMock(id=uuid.uuid4())
    db = db or AsyncMock()
    push = push or AsyncMock(return_value=PushResult("ok", 2, "sha1", "m"))
    with (
        patch.object(ex.repo, "fetch_public_entities", AsyncMock(return_value=ents)),
        patch.object(
            ex.repo, "fetch_public_relationships", AsyncMock(return_value=rels)
        ),
        patch.object(ex, "push_vault", push),
    ):
        result = await ex.export(user=user, db=db, payload=payload or {})
    return db, push, result


@pytest.mark.asyncio
async def test_happy_path_pushes_rendered_files_and_reports_summary():
    db, push, result = await _run([PERSON, PROJECT], [REL])
    files, msg = push.await_args.args
    assert set(files) == {"People/alice.md", "Projects/o-r.md"}
    assert "[[Projects/o-r]]" in files["People/alice.md"]
    assert result == {
        "status": "ok",
        "entities_exported": 2,
        "relationships_exported": 1,
        "files_written": 2,
        "commit_sha": "sha1",
    }
    assert msg.startswith("vault export: 2 notes, 1 relationships")


@pytest.mark.asyncio
async def test_db_transaction_closed_before_git_push():
    order = []
    db = AsyncMock()
    db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
    push = AsyncMock(
        side_effect=lambda *a: order.append("push") or PushResult("ok", 1, "s", "m")
    )
    await _run([PERSON], [], push=push, db=db)
    assert order == ["commit", "push"]


@pytest.mark.asyncio
async def test_no_public_entities_refuses_to_prune_by_default():
    push = AsyncMock(return_value=PushResult("no_changes", 0, None, "m"))
    with pytest.raises(IngestionError, match="vault_export_refused"):
        await _run([], [], push=push)
    push.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_public_entities_prunes_when_explicitly_allowed():
    push = AsyncMock(return_value=PushResult("no_changes", 0, None, "m"))
    _, _, result = await _run([], [], push=push, payload={"allow_empty_prune": True})
    push.assert_awaited_once()
    files_arg, _ = push.await_args.args
    assert files_arg == {}
    assert result["entities_exported"] == 0


@pytest.mark.asyncio
async def test_no_changes_passthrough():
    push = AsyncMock(return_value=PushResult("no_changes", 0, None, "m"))
    _, _, result = await _run([PERSON], [], push=push)
    assert (
        result["status"] == "no_changes"
        and result["commit_sha"] is None
        and result["files_written"] == 0
    )


@pytest.mark.asyncio
async def test_push_failure_propagates():
    push = AsyncMock(side_effect=IngestionError("vault_git_push_failed"))
    with pytest.raises(IngestionError, match="push_failed"):
        await _run([PERSON], [], push=push)


@pytest.mark.asyncio
async def test_private_row_from_query_layer_blocks_push_and_wraps_error():
    bad = {**PERSON, "external_key": "TOPSECRET", "visibility": "private"}
    push = AsyncMock(return_value=PushResult("ok", 1, "s", "m"))
    with pytest.raises(IngestionError, match="vault_render_failed") as exc:
        await _run([PERSON, bad], [], push=push)
    assert "TOPSECRET" not in str(exc.value)
    push.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_collision_is_disambiguated_and_export_proceeds():
    a = {**PROJECT, "external_key": "o/r"}
    b = {**PROJECT, "id": uuid.uuid4(), "external_key": "o-r"}
    push = AsyncMock(return_value=PushResult("ok", 2, "s", "m"))
    await _run([a, b], [], push=push)
    push.assert_awaited_once()


@pytest.mark.asyncio
async def test_relationship_missing_column_is_not_silently_ignored():
    push = AsyncMock(return_value=PushResult("ok", 1, "s", "m"))
    with pytest.raises(KeyError):
        await _run([PERSON], [{"source_key": "alice"}], push=push)
    push.assert_not_awaited()


@pytest.mark.asyncio
async def test_payload_cannot_redirect_target_or_visibility():
    push = AsyncMock(return_value=PushResult("ok", 1, "s", "m"))
    user = MagicMock(id=uuid.uuid4())
    with (
        patch.object(
            ex.repo, "fetch_public_entities", AsyncMock(return_value=[PERSON])
        ) as fe,
        patch.object(ex.repo, "fetch_public_relationships", AsyncMock(return_value=[])),
        patch.object(ex, "push_vault", push),
    ):
        await ex.export(
            user=user,
            db=AsyncMock(),
            payload={"repo": "attacker/x", "visibility": "private", "token": "t"},
        )
    assert len(push.await_args.args) == 2 and not push.await_args.kwargs
    assert fe.await_args.args[1] == user.id


@pytest.mark.asyncio
async def test_rendered_files_deterministic_across_runs():
    seen = []
    for _ in range(2):
        push = AsyncMock(return_value=PushResult("ok", 2, "s", "m"))
        await _run([PERSON, PROJECT], [REL], push=push)
        seen.append(push.await_args.args[0])
    assert seen[0] == seen[1]
