"""Pure planning for an export run: render rows, diff against the ledger.

Nothing here touches the session or the network. That is the point: the
decision of *what* to write, and how far the watermark may advance, is
worked out completely before the first byte goes to GitHub, so a failed
vault write cannot leave the ledger claiming notes were exported.

Two rules live here and are testable without a session or a network: the
watermark freezes at the last row before the first render failure, and an
unchanged note still advances the watermark but is not counted as written.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, NamedTuple

from ...models.obsidian_export import ObsidianExportedNote
from .client import VaultFile
from .config import ExportConfig
from .domains import ExportDomain
from .renderers import RenderedNote

logger = logging.getLogger(__name__)


class RenderFailure(NamedTuple):
    row_id: str
    error: str


class RenderResult(NamedTuple):
    """Outcome of rendering one domain's page of rows."""

    rendered: list[tuple[Any, RenderedNote]]
    failures: list[RenderFailure]
    # Rows safe to count towards the watermark: everything before the
    # first failure, so a failed record is retried on the next run
    # instead of being silently skipped.
    frozen_rows: list[Any]

    def as_dicts(self) -> list[dict[str, str]]:
        return [{"row_id": f.row_id, "error": f.error} for f in self.failures]


def render_rows(
    domain: ExportDomain, rows: list[Any], cfg: ExportConfig
) -> RenderResult:
    """Render every row, isolating per-record failures."""
    rendered: list[tuple[Any, RenderedNote]] = []
    failures: list[RenderFailure] = []
    first_failure_index: int | None = None

    for idx, row in enumerate(rows):
        try:
            rendered.append((row, domain.renderer(row, cfg)))
        except Exception as exc:  # noqa: BLE001 — isolate per-record failures
            logger.warning(
                "obsidian_export: render failed for %s row %s — %s",
                domain.name,
                getattr(row, "id", "?"),
                exc,
            )
            failures.append(RenderFailure(str(getattr(row, "id", "")), str(exc)))
            if first_failure_index is None:
                first_failure_index = idx

    frozen_upto = first_failure_index if first_failure_index is not None else len(rows)
    return RenderResult(rendered, failures, rows[:frozen_upto])


class NotePlan(NamedTuple):
    """Pure diff result for one rendered note — no session access.

    ``existing`` is the already-tracked ORM row to update in place, or
    None to insert a new one; either way, mutation is deferred to
    export_repository.stage_ledger, which only runs once the vault write
    has actually succeeded.
    """

    path: str
    content_hash: str
    row_id: uuid.UUID
    existing: ObsidianExportedNote | None
    # False when the ledger already holds this exact content_hash, i.e. the
    # note was NOT part of this run's commit. Such a plan still advances the
    # watermark, but must not be counted as written or stamped with this
    # run's commit_sha.
    changed: bool


def build_export_plan(
    rendered: list[tuple[Any, RenderedNote]],
    existing_by_path: dict[str, ObsidianExportedNote],
) -> tuple[list[VaultFile], list[NotePlan]]:
    """Diff rendered notes against the pre-fetched ledger in memory only.

    Returns (files_to_commit, plans) — plans covers every rendered note
    (changed or not) so the watermark/ledger still advances for unchanged
    ones, while files_to_commit only includes notes whose content
    actually changed against what's already recorded in the ledger.
    """
    files: list[VaultFile] = []
    plans: list[NotePlan] = []
    for row, note in rendered:
        content_hash = hashlib.sha256(note.content.encode("utf-8")).hexdigest()
        existing = existing_by_path.get(note.path)
        changed = existing is None or existing.content_hash != content_hash
        if changed:
            files.append(VaultFile(note.path, note.content))
        plans.append(NotePlan(note.path, content_hash, row.id, existing, changed))
    return files, plans


__all__ = [
    "NotePlan",
    "RenderFailure",
    "RenderResult",
    "build_export_plan",
    "render_rows",
]
