"""gmail_create_draft — compose and save a draft (does NOT send)."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import gmail
from ..registry import register


class CreateDraftInput(BaseModel):
    to: list[EmailStr] = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=998)  # RFC 5322 line-length cap
    body_plain: str = Field(min_length=1)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    in_reply_to_thread_id: str | None = Field(
        default=None, description="If set, the draft is attached to this thread"
    )


class CreateDraftSummary(BaseModel):
    draft_id: str
    message_id: str
    thread_id: str | None


class CreateDraftOutput(BaseModel):
    data: dict[str, Any]
    summary: CreateDraftSummary


def _build_mime(payload: CreateDraftInput) -> str:
    msg = EmailMessage()
    msg["To"] = ", ".join(payload.to)
    if payload.cc:
        msg["Cc"] = ", ".join(payload.cc)
    if payload.bcc:
        msg["Bcc"] = ", ".join(payload.bcc)
    msg["Subject"] = payload.subject
    msg.set_content(payload.body_plain)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


@register
class GmailCreateDraft(Tool):
    name = "gmail_create_draft"
    description = (
        "Create a Gmail draft (NOT send). Returns the draft ID. The user must "
        "send manually from Gmail. Use in_reply_to_thread_id to attach the draft "
        "to an existing thread (the From header is filled by Gmail at send time)."
    )
    input_schema = CreateDraftInput
    output_schema = CreateDraftOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> CreateDraftOutput:
        assert isinstance(payload, CreateDraftInput)
        body: dict[str, Any] = {"message": {"raw": _build_mime(payload)}}
        if payload.in_reply_to_thread_id:
            body["message"]["threadId"] = payload.in_reply_to_thread_id

        data = await gmail.request(
            db=db,
            user=user,
            method="POST",
            path="/users/me/drafts",
            json=body,
        )
        if not isinstance(data, dict):
            data = {}
        msg = data.get("message") or {}
        return CreateDraftOutput(
            data=data,
            summary=CreateDraftSummary(
                draft_id=data.get("id", ""),
                message_id=msg.get("id", ""),
                thread_id=msg.get("threadId"),
            ),
        )
