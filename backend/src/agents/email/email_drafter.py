"""email/email_drafter — pass-through to gmail_create_draft."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.gmail.create_draft import (
    CreateDraftInput,
    CreateDraftSummary,
    GmailCreateDraft,
)
from ..base import Agent
from ..registry import register


class EmailDrafterOutput(BaseModel):
    data: dict[str, Any]
    summary: CreateDraftSummary


@register
class EmailDrafterAgent(Agent):
    domain = "email"
    name = "email_drafter"
    description = (
        "Creates a Gmail draft (NOT send). Phase E: pass-through to "
        "gmail_create_draft. Phase B will compose the body from a brief "
        "instead of accepting body_plain verbatim."
    )
    input_schema = CreateDraftInput
    output_schema = EmailDrafterOutput
    tool_dependencies = ["gmail_create_draft"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailDrafterOutput:
        result = await GmailCreateDraft()(user=user, db=db, payload=payload)
        return EmailDrafterOutput(data=result.data, summary=result.summary)
