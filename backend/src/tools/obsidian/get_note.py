"""obsidian_get_note — fetch full content of a single vault note."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian import IngestedObsidianNote
from ...models.user import User
from ..base import Tool, ToolError
from ..registry import register


class GetNoteInput(BaseModel):
    note_id: str = Field(description="UUID of the note from obsidian_search_notes")


class GetNoteOutput(BaseModel):
    id: str
    title: str
    path: str
    content: str
    tags: list[str]
    word_count: int
    last_modified_at: str
    summary: str


@register
class ObsidianGetNote(Tool):
    name = "obsidian_get_note"
    description = (
        "Fetch the full markdown content of a specific Obsidian vault note by its ID. "
        "Use after obsidian_search_notes to read the complete text of a note."
    )
    input_schema = GetNoteInput
    output_schema = GetNoteOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> GetNoteOutput:
        assert isinstance(payload, GetNoteInput)

        try:
            note_uuid = uuid.UUID(payload.note_id)
        except ValueError:
            raise ToolError(
                "invalid_note_id", f"'{payload.note_id}' is not a valid UUID."
            )

        note = await db.scalar(
            select(IngestedObsidianNote).where(
                IngestedObsidianNote.id == note_uuid,
                IngestedObsidianNote.user_id == user.id,
            )
        )
        if note is None:
            raise ToolError("note_not_found", f"No note with id '{payload.note_id}'.")

        return GetNoteOutput(
            id=str(note.id),
            title=note.title,
            path=note.github_path,
            content=note.content,
            tags=note.tags if isinstance(note.tags, list) else [],
            word_count=note.word_count,
            last_modified_at=note.last_modified_at.isoformat(),
            summary=f"Note '{note.title}' ({note.word_count} words).",
        )
