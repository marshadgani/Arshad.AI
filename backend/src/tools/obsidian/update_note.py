"""obsidian_update_note — overwrite an existing vault note via GitHub."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian import IngestedObsidianNote
from ...models.user import User
from ...services import obsidian_client as gh
from ..base import Tool, ToolError
from ..registry import register


class UpdateNoteInput(BaseModel):
    note_id: str = Field(description="UUID of the note to update")
    content: str = Field(
        description="New full markdown content — replaces existing content"
    )


class UpdateNoteOutput(BaseModel):
    id: str
    title: str
    path: str
    blob_sha: str
    summary: str


@register
class ObsidianUpdateNote(Tool):
    name = "obsidian_update_note"
    description = (
        "Update the content of an existing Obsidian vault note. "
        "The change is committed to GitHub and synced back to Obsidian. "
        "Always fetch the note first with obsidian_get_note to build on the current content."
    )
    input_schema = UpdateNoteInput
    output_schema = UpdateNoteOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> UpdateNoteOutput:
        assert isinstance(payload, UpdateNoteInput)

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

        repo = gh.vault_repo()
        result = await gh.write_file(
            db=db,
            user=user,
            repo=repo,
            path=note.github_path,
            content=payload.content,
            commit_message=f"arshad.ai: update {note.github_path}",
            existing_sha=note.blob_sha or None,
        )

        from ...services.ingestion.obsidian import (
            _extract_tags,
            _extract_title,
            _parse_frontmatter,
            _word_count,
        )

        fm, body = _parse_frontmatter(payload.content)
        now = datetime.now(timezone.utc)
        note.title = _extract_title(fm, body, note.github_path)
        note.content = payload.content
        note.frontmatter = fm
        note.tags = _extract_tags(fm, body)
        note.word_count = _word_count(body)
        note.blob_sha = result["sha"]
        note.last_modified_at = now
        note.ingested_at = now
        await db.commit()

        return UpdateNoteOutput(
            id=str(note.id),
            title=note.title,
            path=note.github_path,
            blob_sha=result["sha"],
            summary=f"Updated note '{note.title}' at {note.github_path}.",
        )
