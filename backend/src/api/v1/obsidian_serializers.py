"""Wire shapes for the Obsidian endpoints.

Separated from the router so the response contract the frontend depends
on can be read — and tested — without going through FastAPI. The shapes
are pinned by tests/test_obsidian_api.py.
"""

from __future__ import annotations

from typing import Any

from ...models.obsidian import IngestedObsidianNote
from ...models.obsidian_export import ObsidianExportState


def note_summary(note: IngestedObsidianNote) -> dict[str, Any]:
    return {
        "id": str(note.id),
        "title": note.title,
        "path": note.github_path,
        "excerpt": note.content[:200].strip(),
        "tags": note.tags if isinstance(note.tags, list) else [],
        "word_count": note.word_count,
        "last_modified_at": note.last_modified_at.isoformat(),
    }


def note_full(note: IngestedObsidianNote) -> dict[str, Any]:
    return {
        **note_summary(note),
        "content": note.content,
        "frontmatter": note.frontmatter,
        "blob_sha": note.blob_sha,
        "ingested_at": note.ingested_at.isoformat(),
    }


def domain_export_status(state: ObsidianExportState | None) -> dict[str, Any]:
    """A domain that has never been exported has no state row yet, and
    reports as an untouched domain rather than as an absence."""
    if state is None:
        return {"last_exported_at": None, "notes_written": 0, "last_error": None}
    return {
        "last_exported_at": (
            state.last_exported_at.isoformat() if state.last_exported_at else None
        ),
        "notes_written": state.notes_written,
        "last_error": state.last_error,
    }


__all__ = ["domain_export_status", "note_full", "note_summary"]
