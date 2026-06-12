"""obsidian_create_note — write a new note to the vault via GitHub."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian import IngestedObsidianNote
from ...models.user import User
from ...services import obsidian_client as gh
from ..base import Tool, ToolError
from ..registry import register


class CreateNoteInput(BaseModel):
    path: str = Field(
        description="Vault-relative path, e.g. 'Daily Notes/2026-06-12.md'. "
        "Must end in .md.",
        min_length=1,
        max_length=500,
    )
    content: str = Field(description="Full markdown content of the note.")


class CreateNoteOutput(BaseModel):
    id: str
    title: str
    path: str
    blob_sha: str
    summary: str


@register
class ObsidianCreateNote(Tool):
    name = "obsidian_create_note"
    description = (
        "Create a new note in the user's Obsidian vault. "
        "The note is committed to GitHub and synced back to Obsidian automatically. "
        "path should end in .md and use the user's existing folder structure."
    )
    input_schema = CreateNoteInput
    output_schema = CreateNoteOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CreateNoteOutput:
        assert isinstance(payload, CreateNoteInput)

        repo = gh.vault_repo()
        path = payload.path if payload.path.endswith(".md") else payload.path + ".md"

        # Reject path traversal attempts.
        norm = PurePosixPath(path)
        if ".." in norm.parts or norm.is_absolute():
            raise ToolError(
                "invalid_path",
                "Note path must not contain '..' components or be absolute.",
            )

        result = await gh.write_file(
            db=db,
            user=user,
            repo=repo,
            path=path,
            content=payload.content,
            commit_message=f"arshad.ai: add {path}",
        )

        from ...services.ingestion.obsidian import (
            _extract_tags,
            _extract_title,
            _parse_frontmatter,
            _word_count,
        )

        fm, body = _parse_frontmatter(payload.content)
        title = _extract_title(fm, body, path)
        tags = _extract_tags(fm, body)
        now = datetime.now(timezone.utc)

        row: dict[str, Any] = {
            "user_id": user.id,
            "github_path": path,
            "title": title,
            "content": payload.content,
            "frontmatter": fm,
            "tags": tags,
            "word_count": _word_count(body),
            "blob_sha": result["sha"],
            "last_modified_at": now,
            "ingested_at": now,
        }
        stmt = pg_insert(IngestedObsidianNote).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "github_path"],
            set_={
                k: stmt.excluded[k] for k in row if k not in ("user_id", "github_path")
            },
        )
        await db.execute(stmt)
        await db.commit()

        from sqlalchemy import select

        note = await db.scalar(
            select(IngestedObsidianNote).where(
                IngestedObsidianNote.user_id == user.id,
                IngestedObsidianNote.github_path == path,
            )
        )
        if note is None:
            raise ToolError(
                "create_note_db_error",
                "Note was written to GitHub but could not be confirmed in the database.",
            )

        return CreateNoteOutput(
            id=str(note.id),
            title=title,
            path=path,
            blob_sha=result["sha"],
            summary=f"Created note '{title}' at {path}.",
        )
