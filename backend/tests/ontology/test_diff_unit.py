"""Unit tests — diff.py (blob_sha + plan_changes).

Covers TC-028 through TC-036. Zero I/O.
"""

from __future__ import annotations

import hashlib

from src.services.ingestion.ontology.diff import (
    blob_sha,
    plan_changes,
)


# ── TC-028 ─────────────────────────────────────────────────────────
def test_blob_sha_matches_git_algorithm():
    """Known fixture: git hash-object of the string 'hello\n' is 8ab686...
    Verify our computation matches git's algorithm byte-for-byte.
    """
    content = b"hello\n"
    header = f"blob {len(content)}\0".encode()
    expected = hashlib.sha1(header + content).hexdigest()
    assert blob_sha(content) == expected


# ── TC-029 ─────────────────────────────────────────────────────────
def test_blob_sha_identical_content_identical_sha():
    content = b"The quick brown fox"
    assert blob_sha(content) == blob_sha(content)


# ── TC-030 ─────────────────────────────────────────────────────────
def test_blob_sha_single_byte_change():
    content_a = b"hello world"
    content_b = b"hello worLd"
    assert blob_sha(content_a) != blob_sha(content_b)


# ── TC-031 ─────────────────────────────────────────────────────────
def test_plan_changes_includes_changed_path():
    rendered = {"path/a.md": "new content"}
    stored = {"path/a.md": "old_sha_value"}  # different → change
    plan = plan_changes(rendered, stored, [])
    assert any(c.path == "path/a.md" for c in plan.changes)


# ── TC-032 ─────────────────────────────────────────────────────────
def test_plan_changes_skips_unchanged_path():
    text = "same content"
    sha = blob_sha(text.encode("utf-8"))
    rendered = {"path/b.md": text}
    stored = {"path/b.md": sha}  # identical
    plan = plan_changes(rendered, stored, [])
    # No change for this path
    assert not any(c.path == "path/b.md" for c in plan.changes)


# ── TC-033 ─────────────────────────────────────────────────────────
def test_plan_changes_new_path_never_synced():
    """blob_sha stored as empty string (default) means never synced → always commit."""
    text = "brand new note"
    rendered = {"path/new.md": text}
    stored = {"path/new.md": ""}  # default empty = never synced
    plan = plan_changes(rendered, stored, [])
    assert any(c.path == "path/new.md" for c in plan.changes)


# ── TC-034 ─────────────────────────────────────────────────────────
def test_plan_changes_rename_emits_delete_of_old_path():
    text = "content"
    sha = blob_sha(text.encode())
    rendered = {"new_path.md": text}
    stored = {"new_path.md": sha}  # new path up-to-date
    rename_ops = [("old_path.md", "new_path.md")]
    plan = plan_changes(rendered, stored, rename_ops)
    delete_changes = [c for c in plan.changes if c.is_delete]
    assert any(c.path == "old_path.md" for c in delete_changes)


# ── TC-035 ─────────────────────────────────────────────────────────
def test_plan_changes_bool_false_when_nothing_changed():
    text = "unchanged"
    sha = blob_sha(text.encode())
    rendered = {"note.md": text}
    stored = {"note.md": sha}
    plan = plan_changes(rendered, stored, [])
    assert not plan  # DiffPlan.__bool__ is False


# ── TC-036 ─────────────────────────────────────────────────────────
def test_plan_changes_sha_by_path_populated():
    text = "some text"
    sha = blob_sha(text.encode())
    plan = plan_changes({"x.md": text}, {}, [])
    assert plan.sha_by_path["x.md"] == sha


# ── TC-036b ────────────────────────────────────────────────────────
def test_plan_changes_rename_to_same_path_no_delete():
    """A rename op whose old and new path are identical must not emit a
    spurious self-delete (real-world no-op rename, e.g. display_name
    round-tripped to the same slug)."""
    text = "content"
    sha = blob_sha(text.encode())
    rendered = {"same.md": text}
    stored = {"same.md": sha}
    rename_ops = [("same.md", "same.md")]
    plan = plan_changes(rendered, stored, rename_ops)
    assert not any(c.path == "same.md" and c.is_delete for c in plan.changes)


# ── TC-036c ────────────────────────────────────────────────────────
def test_unchanged_count_not_double_charged_by_rename_delete():
    """Regression: a rename-delete must not be subtracted from the
    unchanged tally.

    ``sha_by_path`` only ever holds RENDERED (new) paths, so the old path
    of a rename has no entry there. Deriving unchanged as
    ``len(sha_by_path) - len(changes)`` therefore double-charged every
    rename-delete against an unrelated unchanged note, reporting a
    rename-only sync as having zero unchanged notes on
    /ontology/status.
    """
    text = "byte-identical body"
    sha = blob_sha(text.encode())
    plan = plan_changes(
        {"new_path.md": text},
        {"new_path.md": sha},  # content genuinely unchanged
        [("old_path.md", "new_path.md")],
    )
    assert plan.written_count == 0
    assert plan.deleted_count == 1
    assert plan.changed_count == 1  # the delete is still a vault operation
    assert plan.unchanged_count == 1


# ── TC-036d ────────────────────────────────────────────────────────
def test_vacated_path_reclaimed_by_another_entity_is_not_deleted():
    """Regression (data loss): when A renames off path P and B claims P
    in the same run, P must be written and NOT also deleted.

    ``resolve._claimed_paths`` frees a renaming entity's old path
    precisely so a sibling can take it, so this is a designed-for case.
    Emitting both a write and a ``sha: null`` delete for P in one git
    tree is ambiguous — the trailing delete wins and B's note vanishes
    from the vault, while _mark_synced still records B's blob_sha, so
    every later run diffs clean and never restores it.
    """
    rendered = {"Retro.md": "A body", "Standup.md": "B body"}
    plan = plan_changes(rendered, {}, [("Standup.md", "Retro.md")])

    deleted = {c.path for c in plan.changes if c.is_delete}
    assert deleted == set()
    assert plan.written_paths == {"Retro.md", "Standup.md"}
    # No path may carry two contradictory operations in one tree.
    assert len(plan.changes) == len({c.path for c in plan.changes})


# ── TC-036e ────────────────────────────────────────────────────────
def test_rename_swap_cycle_emits_no_deletes():
    """A full A<->B path swap renders both paths; neither may be deleted."""
    rendered = {"Retro.md": "A body", "Standup.md": "B body"}
    rename_ops = [("Standup.md", "Retro.md"), ("Retro.md", "Standup.md")]
    plan = plan_changes(rendered, {}, rename_ops)

    assert not any(c.is_delete for c in plan.changes)
    assert plan.written_paths == {"Retro.md", "Standup.md"}


# ── TC-036f ────────────────────────────────────────────────────────
def test_vacated_path_still_deleted_when_nobody_reclaims_it():
    """The guard must not suppress genuine rename-deletes — an old path
    that nothing renders to is still removed from the vault."""
    plan = plan_changes({"new.md": "body"}, {}, [("old.md", "new.md")])
    assert {c.path for c in plan.changes if c.is_delete} == {"old.md"}
    assert plan.deleted_count == 1


# ── TC-036g ────────────────────────────────────────────────────────
def test_duplicate_rename_ops_emit_one_delete():
    """Two rename ops vacating the same old path yield a single delete
    entry — a git tree with the same path twice is ill-formed."""
    plan = plan_changes(
        {"a.md": "A", "b.md": "B"},
        {},
        [("old.md", "a.md"), ("old.md", "b.md")],
    )
    deletes = [c for c in plan.changes if c.is_delete and c.path == "old.md"]
    assert len(deletes) == 1
