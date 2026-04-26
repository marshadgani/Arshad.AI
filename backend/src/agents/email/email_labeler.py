"""email/email_labeler — pass-through to gmail_apply_label."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.gmail.apply_label import (
    ApplyLabelInput,
    ApplyLabelSummary,
    GmailApplyLabel,
)
from ..base import Agent
from ..registry import register


class EmailLabelerOutput(BaseModel):
    data: dict[str, Any]
    summary: ApplyLabelSummary


@register
class EmailLabelerAgent(Agent):
    domain = "email"
    name = "email_labeler"
    description = (
        "Adds and/or removes Gmail label IDs on a thread. Phase E: "
        "pass-through. Phase B will accept label NAMES (resolving to IDs) "
        "and decide labels from thread content."
    )
    input_schema = ApplyLabelInput
    output_schema = EmailLabelerOutput
    tool_dependencies = ["gmail_apply_label"]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> EmailLabelerOutput:
        result = await GmailApplyLabel()(user=user, db=db, payload=payload)
        return EmailLabelerOutput(data=result.data, summary=result.summary)
