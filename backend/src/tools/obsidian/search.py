"""obsidian_search_notes — full-text search over the Obsidian vault."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.obsidian import IngestedObsidianNote
from ...models.user import User
from ..base import Tool
from ..registry import register


class SearchNotesInput(BaseModel):
    query: str = Field(description="Full-text search query")
    tags: list[str] | None = Field(
        default=None, description="Filter by tags (all must match)"
    )
    limit: int = Field(default=10, ge=1, le=50)


class NoteExcerpt(BaseModel):
    id: str
    title: str
    path: str
    excerpt: str
    tags: list[str]
    last_modified_at: str


class SearchNotesOutput(BaseModel):
    data: list[NoteExcerpt]
    total: int
    summary: str


@register
class ObsidianSearchNotes(Tool):
    name = "obsidian_search_notes"
    description = (
        "Search the user's Obsidian vault notes by keywords. "
        "Use this when the user asks about their notes, memories, writing, or knowledge base. "
        "Returns note titles, paths, and excerpts ranked by relevance."
    )
    input_schema = SearchNotesInput
    output_schema = SearchNotesOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> SearchNotesOutput:
        assert isinstance(payload, SearchNotesInput)

        stmt = select(IngestedObsidianNote).where(
            IngestedObsidianNote.user_id == user.id
        )

        if payload.query.strip():
            stmt = stmt.where(
                text(
                    "to_tsvector('english', "
                    "coalesce(title, '') || ' ' || coalesce(content, '')) "
                    "@@ plainto_tsquery('english', :q)"
                ).bindparams(q=payload.query)
            )

        if payload.tags:
            for tag in payload.tags:
                stmt = stmt.where(
                    IngestedObsidianNote.tags.op("@>")(
                        func.cast(f'["{tag}"]', type_=None)
                    )
                )

        stmt = stmt.order_by(IngestedObsidianNote.last_modified_at.desc()).limit(
            payload.limit
        )

        rows = (await db.execute(stmt)).scalars().all()

        excerpts: list[NoteExcerpt] = []
        for note in rows:
            excerpts.append(
                NoteExcerpt(
                    id=str(note.id),
                    title=note.title,
                    path=note.github_path,
                    excerpt=note.content[:300].strip(),
                    tags=note.tags if isinstance(note.tags, list) else [],
                    last_modified_at=note.last_modified_at.isoformat(),
                )
            )

        summary = (
            f"Found {len(excerpts)} note(s) matching '{payload.query}'."
            if payload.query.strip()
            else f"Retrieved {len(excerpts)} most-recent note(s)."
        )
        return SearchNotesOutput(data=excerpts, total=len(excerpts), summary=summary)
