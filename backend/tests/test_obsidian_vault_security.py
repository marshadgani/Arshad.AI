"""Security tests for FEAT-166: public-only enforcement at every layer."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from src.services.ingestion.obsidian_vault_render import Entity, render_vault

_REPO_SRC = (
    Path(__file__).parent.parent
    / "src"
    / "services"
    / "ingestion"
    / "obsidian_vault_repository.py"
)


def test_repository_uses_bound_public_predicate_and_no_raw_sql():
    src = _REPO_SRC.read_text()
    assert "PUBLIC" in src and "text(" not in src
    assert not re.search(r'execute\(\s*f["\']', src)
    assert src.count("visibility == PUBLIC") >= 4  # entities + rel + both endpoints


@pytest.mark.asyncio
@pytest.mark.pg
async def test_query_layer_returns_only_public_rows_and_edges(
    pg_session, committed_user
):
    from sqlalchemy import text
    from src.models.ontology import OntologyEntity, OntologyRelationship
    from src.services.ingestion import obsidian_vault_repository as repo

    uid = committed_user.id
    ents = {
        k: OntologyEntity(id=uuid.uuid4(), user_id=uid, entity_type=t, external_key=k)
        for k, t in [("pub_p", "person"), ("pub_r", "project"), ("priv_r", "project")]
    }
    pg_session.add_all(ents.values())
    await pg_session.flush()
    await pg_session.execute(
        text("UPDATE ontology_entities SET visibility='private' WHERE id=:i"),
        {"i": ents["priv_r"].id},
    )
    for tgt in ("pub_r", "priv_r"):
        pg_session.add(
            OntologyRelationship(
                id=uuid.uuid4(),
                user_id=uid,
                source_entity_id=ents["pub_p"].id,
                relationship_type="contributed_to",
                target_entity_id=ents[tgt].id,
            )
        )
    await pg_session.flush()
    await pg_session.execute(
        text("UPDATE ontology_relationships SET visibility='public' WHERE user_id=:u"),
        {"u": uid},
    )
    keys = {
        e["external_key"] for e in await repo.fetch_public_entities(pg_session, uid)
    }
    assert keys == {"pub_p", "pub_r"}
    rels = await repo.fetch_public_relationships(pg_session, uid)
    assert [r["target_key"] for r in rels] == [
        "pub_r"
    ]  # public edge to private endpoint dropped


@pytest.mark.asyncio
@pytest.mark.pg
async def test_tenant_isolation(pg_session, committed_user):
    from src.models.ontology import OntologyEntity
    from src.models.user import User
    from src.services.ingestion import obsidian_vault_repository as repo

    other = User(
        id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:8]}@example.com", name="Other"
    )
    pg_session.add(other)
    await pg_session.flush()
    for u, k in ((committed_user, "u1"), (other, "u2")):
        pg_session.add(
            OntologyEntity(
                id=uuid.uuid4(), user_id=u.id, entity_type="person", external_key=k
            )
        )
    await pg_session.flush()
    got = {
        e["external_key"]
        for e in await repo.fetch_public_entities(pg_session, committed_user.id)
    }
    assert got == {"u1"}


def test_private_key_never_in_render_output_or_error():
    with pytest.raises(ValueError) as exc:
        render_vault([Entity("1", "person", "SENTINEL_PRIVATE", "private")], [])
    assert "SENTINEL_PRIVATE" not in str(exc.value)


# ---------------------------------------------------------------------------
# Stale-file pruning tests (DEF-001)
# Entities demoted to private or deleted must have their vault notes removed
# via git rm --cached in the same commit as new/changed files.
# ---------------------------------------------------------------------------


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


def _make_fake_git(active_sha, stale_path, diff_output):
    """Return a fake _run_git that simulates HEAD containing active + stale files."""
    calls = []

    def fake(args, cwd=None, env=None, timeout=0):
        sub = next(
            (
                a
                for a in args
                if a
                in {
                    "clone",
                    "rev-parse",
                    "ls-tree",
                    "add",
                    "rm",
                    "diff",
                    "commit",
                    "push",
                }
            ),
            "other",
        )
        calls.append((sub, list(args)))
        if sub == "rev-parse" and "--verify" in args:
            return _cp(0, "", "")
        if sub == "rev-parse":
            return _cp(0, "sha_test\n", "")
        if sub == "ls-tree":
            return _cp(
                0,
                f"100644 blob {active_sha}\tPeople/active.md\n"
                f"100644 blob old123\t{stale_path}\n",
                "",
            )
        if sub == "diff":
            return _cp(0, diff_output, "")
        return _cp()

    return fake, calls


@pytest.mark.asyncio
async def test_stale_people_file_triggers_git_rm_cached():
    """A People/ file in HEAD but absent from the render set gets git rm --cached."""
    from src.services.ingestion import obsidian_vault_git as g

    active_sha = g.blob_sha("active\n".encode())
    fake, calls = _make_fake_git(active_sha, "People/demoted.md", "People/demoted.md\n")

    with patch.dict(
        os.environ,
        {
            "OBSIDIAN_VAULT_REPO_TOKEN": "tok_stale_test",
            "OBSIDIAN_VAULT_REPO_URL": "owner/repo",
        },
    ):
        with patch.object(g, "_run_git", fake):
            res = await g.push_vault({"People/active.md": "active\n"}, "prune")

    rm_calls = [a for s, a in calls if s == "rm"]
    assert rm_calls, "git rm --cached was never called for the stale People/ file"
    assert "People/demoted.md" in rm_calls[0], "stale file not passed to git rm"
    assert "People/active.md" not in rm_calls[0], (
        "active file wrongly staged for removal"
    )
    assert res.status == "ok"


@pytest.mark.asyncio
async def test_prune_only_run_still_commits_and_pushes():
    """A prune-only run (no changed files, only stale) still commits and pushes."""
    from src.services.ingestion import obsidian_vault_git as g

    active_sha = g.blob_sha("active\n".encode())
    fake, calls = _make_fake_git(active_sha, "People/stale.md", "People/stale.md\n")

    with patch.dict(
        os.environ,
        {
            "OBSIDIAN_VAULT_REPO_TOKEN": "tok_prune_only",
            "OBSIDIAN_VAULT_REPO_URL": "owner/repo",
        },
    ):
        with patch.object(g, "_run_git", fake):
            res = await g.push_vault({"People/active.md": "active\n"}, "prune-only")

    subs = [s for s, _ in calls]
    assert "rm" in subs, "git rm --cached not called in prune-only run"
    assert "commit" in subs, "commit not called in prune-only run"
    assert "push" in subs, "push not called in prune-only run"
    assert res.status == "ok"


@pytest.mark.asyncio
async def test_files_outside_managed_prefixes_not_pruned():
    """Files outside People/ and Projects/ in HEAD are never touched by pruning."""
    from src.services.ingestion import obsidian_vault_git as g

    current_sha = g.blob_sha("current\n".encode())
    calls = []

    def fake(args, cwd=None, env=None, timeout=0):
        sub = next(
            (
                a
                for a in args
                if a
                in {
                    "clone",
                    "rev-parse",
                    "ls-tree",
                    "add",
                    "rm",
                    "diff",
                    "commit",
                    "push",
                }
            ),
            "other",
        )
        calls.append((sub, list(args)))
        if sub == "rev-parse" and "--verify" in args:
            return _cp(0, "", "")
        if sub == "rev-parse":
            return _cp(0, "sha_ext\n", "")
        if sub == "ls-tree":
            return _cp(
                0,
                f"100644 blob abc\tREADME.md\n"
                f"100644 blob xyz\tNotes/custom.md\n"
                f"100644 blob {current_sha}\tPeople/current.md\n",
                "",
            )
        if sub == "diff":
            return _cp(0, "", "")  # nothing staged — all content already matches
        return _cp()

    with patch.dict(
        os.environ,
        {
            "OBSIDIAN_VAULT_REPO_TOKEN": "tok_ext_test",
            "OBSIDIAN_VAULT_REPO_URL": "owner/repo",
        },
    ):
        with patch.object(g, "_run_git", fake):
            res = await g.push_vault({"People/current.md": "current\n"}, "noop")

    rm_calls = [a for s, a in calls if s == "rm"]
    assert not rm_calls, (
        f"Files outside managed prefixes were wrongly staged for removal: {rm_calls}"
    )
    assert res.status == "no_changes"
