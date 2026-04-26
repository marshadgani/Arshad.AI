"""gmail_get_thread — fetch a thread with decoded plain-text bodies."""

from __future__ import annotations

import base64
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import gmail
from ..registry import register


class GetThreadInput(BaseModel):
    thread_id: str = Field(min_length=1)


class MessageSummary(BaseModel):
    id: str
    from_addr: str | None
    to_addrs: list[str] = Field(default_factory=list)
    subject: str | None
    date: str | None
    body_plain: str | None


class GetThreadSummary(BaseModel):
    thread_id: str
    messages: list[MessageSummary]


class GetThreadOutput(BaseModel):
    data: dict[str, Any]
    summary: GetThreadSummary


def _header(headers: list[dict[str, str]], name: str) -> str | None:
    """Case-insensitive header lookup; returns the FIRST match or None."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _walk_for_plain(part: dict[str, Any]) -> str | None:
    """DFS through MIME parts; return the first text/plain body decoded.

    Gmail base64url-encodes bodies in ``parts[*].body.data``. Multi-part
    messages have nested ``parts``. text/html is preferred only when no
    text/plain exists anywhere in the tree.
    """
    if not part:
        return None
    if part.get("mimeType") == "text/plain":
        data = (part.get("body") or {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
    for sub in part.get("parts") or []:
        found = _walk_for_plain(sub)
        if found is not None:
            return found
    return None


@register
class GmailGetThread(Tool):
    name = "gmail_get_thread"
    description = (
        "Fetch a Gmail thread with decoded text/plain bodies for each message. "
        "Headers are extracted to from/to/subject/date. Use after "
        "gmail_search_threads identifies a thread of interest."
    )
    input_schema = GetThreadInput
    output_schema = GetThreadOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> GetThreadOutput:
        assert isinstance(payload, GetThreadInput)
        data = await gmail.request(
            db=db,
            user=user,
            method="GET",
            path=f"/users/me/threads/{payload.thread_id}",
            params={"format": "full"},
        )
        if not isinstance(data, dict):
            data = {}

        summary_messages: list[MessageSummary] = []
        for msg in data.get("messages") or []:
            payload_part = msg.get("payload") or {}
            headers = payload_part.get("headers") or []
            to_raw = _header(headers, "To") or ""
            summary_messages.append(
                MessageSummary(
                    id=msg.get("id", ""),
                    from_addr=_header(headers, "From"),
                    to_addrs=[a.strip() for a in to_raw.split(",") if a.strip()],
                    subject=_header(headers, "Subject"),
                    date=_header(headers, "Date"),
                    body_plain=_walk_for_plain(payload_part),
                )
            )

        return GetThreadOutput(
            data=data,
            summary=GetThreadSummary(
                thread_id=payload.thread_id, messages=summary_messages
            ),
        )
