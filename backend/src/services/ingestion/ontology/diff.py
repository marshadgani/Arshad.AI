"""Pass 3 — Local diff. Zero network calls.

The idempotent-upsert guarantee (FEAT-141 point 5) is implemented here:
a note is only committed when the git blob SHA of its freshly rendered
bytes differs from the SHA we recorded the last time we wrote it. The
SHA is computed locally with git's own ``blob <len>\\0`` framing, so a
run over unchanged data makes no GitHub calls at all rather than
fetching every file to compare.

``NoteChange`` is deliberately transport-agnostic — it knows nothing
about the Git Data API. ``vault_writer.py`` is the only module that
translates these into GitHub tree entries, which is what keeps this pass
testable with plain strings.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


def blob_sha(content: bytes) -> str:
    """git's blob object id for ``content`` — identical to what the
    GitHub API reports for the same bytes."""
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


@dataclass(frozen=True)
class NoteChange:
    """One path the vault must be made to agree with. ``content is None``
    means delete."""

    path: str
    content: str | None = None

    @property
    def is_delete(self) -> bool:
        return self.content is None


@dataclass(frozen=True)
class DiffPlan:
    changes: list[NoteChange]
    sha_by_path: dict[str, str]

    @property
    def changed_count(self) -> int:
        """Total vault operations in this plan — writes AND deletes.
        Used for the commit message, not for the audit counts."""
        return len(self.changes)

    @property
    def written_count(self) -> int:
        return len(self.written_paths)

    @property
    def deleted_count(self) -> int:
        return sum(1 for c in self.changes if c.is_delete)

    @property
    def unchanged_count(self) -> int:
        """Rendered notes whose bytes already match the vault.

        Deliberately subtracts ``written_count`` and NOT ``len(changes)``:
        ``changes`` also carries rename-deletes, whose paths are never
        keys of ``sha_by_path`` (that map is built from ``rendered``,
        i.e. new paths only). Subtracting the whole list double-charges
        each delete against an unrelated unchanged note and under-reports
        the unchanged figure surfaced by /ontology/status.
        """
        return len(self.sha_by_path) - self.written_count

    @property
    def written_paths(self) -> set[str]:
        return {c.path for c in self.changes if not c.is_delete}

    def sha_for(self, path: str) -> str:
        return self.sha_by_path[path]

    def __bool__(self) -> bool:
        return bool(self.changes)


def plan_changes(
    rendered: Mapping[str, str],
    stored_sha_by_path: Mapping[str, str],
    rename_ops: Iterable[tuple[str, str]],
) -> DiffPlan:
    """Compare rendered notes against last-committed SHAs.

    Renames contribute a delete of the OLD path; the new path is already
    in ``rendered`` under its new name and diffs as a normal write.

    A vacated path is only deleted when nothing else in this run renders
    to it. ``resolve._claimed_paths`` deliberately frees the old path of
    a renaming entity so a *different* entity in the same batch can claim
    it, so "A moves off P, B moves onto P" is a designed-for case, not a
    corner case. Emitting the delete unconditionally puts a write and a
    ``sha: null`` delete for P in the SAME git tree — an ambiguous tree
    where the trailing delete wins and B's note silently disappears from
    the vault, while ``_mark_synced`` still records B's blob_sha, so
    every later run diffs clean and never restores it. Filtering against
    ``sha_by_path`` (all rendered paths, not just the written ones — a
    rendered-but-byte-unchanged note must survive too) keeps each path
    under exactly one operation per tree.
    """
    changes: list[NoteChange] = []
    sha_by_path: dict[str, str] = {}

    for path, text in rendered.items():
        sha = blob_sha(text.encode("utf-8"))
        sha_by_path[path] = sha
        if stored_sha_by_path.get(path) != sha:
            changes.append(NoteChange(path=path, content=text))

    deleted: set[str] = set()
    for old_path, new_path in rename_ops:
        if old_path == new_path or not old_path:
            continue
        if old_path in sha_by_path or old_path in deleted:
            continue
        deleted.add(old_path)
        changes.append(NoteChange(path=old_path, content=None))

    return DiffPlan(changes=changes, sha_by_path=sha_by_path)
