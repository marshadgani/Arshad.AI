"""gmail_search_threads — Gmail search-syntax query, returns thread snippets."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import gmail
from ..registry import register


class SearchThreadsInput(BaseModel):
    query: str = Field(
        description="Gmail search syntax, e.g. 'in:inbox newer_than:7d from:boss@example.com'"
    )
    max_results: int = Field(default=20, ge=1, le=100)
    label_ids: list[str] | None = Field(
        default=None, description="Restrict to threads bearing all of these label IDs"
    )


class ThreadSummary(BaseModel):
    thread_id: str
    snippet: str
    history_id: str | None = None


class SearchThreadsOutput(BaseModel):
    data: dict[str, Any]
    summary: list[ThreadSummary]


@register
class GmailSearchThreads(Tool):
    name = "gmail_search_threads"
    description = (
        "Search Gmail threads using Gmail's search syntax. Returns up to "
        "max_results matching threads with snippets. Does NOT fetch full message "
        "bodies — call gmail_get_thread for that."
    )
    input_schema = SearchThreadsInput
    output_schema = SearchThreadsOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> SearchThreadsOutput:
        assert isinstance(payload, SearchThreadsInput)
        params: dict[str, Any] = {"q": payload.query, "maxResults": payload.max_results}
        if payload.label_ids:
            params["labelIds"] = payload.label_ids

        data = await gmail.request(
            db=db,
            user=user,
            method="GET",
            path="/users/me/threads",
            params=params,
        )
        threads = data.get("threads", []) if isinstance(data, dict) else []
        return SearchThreadsOutput(
            data=data or {},
            summary=[
                ThreadSummary(
                    thread_id=t["id"],
                    snippet=t.get("snippet", ""),
                    history_id=t.get("historyId"),
                )
                for t in threads
            ],
        )
