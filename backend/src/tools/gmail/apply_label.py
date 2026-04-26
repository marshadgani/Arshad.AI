"""gmail_apply_label — add and/or remove label IDs on a thread."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Tool
from ..clients import gmail
from ..registry import register


class ApplyLabelInput(BaseModel):
    thread_id: str = Field(min_length=1)
    add_label_ids: list[str] = Field(default_factory=list)
    remove_label_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _at_least_one(self) -> "ApplyLabelInput":
        if not self.add_label_ids and not self.remove_label_ids:
            raise ValueError("must specify add_label_ids or remove_label_ids")
        return self


class ApplyLabelSummary(BaseModel):
    thread_id: str
    label_ids: list[str]


class ApplyLabelOutput(BaseModel):
    data: dict[str, Any]
    summary: ApplyLabelSummary


@register
class GmailApplyLabel(Tool):
    name = "gmail_apply_label"
    description = (
        "Add and/or remove Gmail label IDs on a thread. Use system labels "
        "(INBOX, STARRED, IMPORTANT, TRASH, SPAM, UNREAD) or custom label IDs "
        "from /users/me/labels. At least one of add_label_ids or remove_label_ids "
        "must be non-empty."
    )
    input_schema = ApplyLabelInput
    output_schema = ApplyLabelOutput

    async def __call__(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> ApplyLabelOutput:
        assert isinstance(payload, ApplyLabelInput)
        body: dict[str, Any] = {}
        if payload.add_label_ids:
            body["addLabelIds"] = payload.add_label_ids
        if payload.remove_label_ids:
            body["removeLabelIds"] = payload.remove_label_ids

        data = await gmail.request(
            db=db,
            user=user,
            method="POST",
            path=f"/users/me/threads/{payload.thread_id}/modify",
            json=body,
        )
        if not isinstance(data, dict):
            data = {}

        # Gmail returns the thread with messages[*].labelIds; union them.
        label_ids: set[str] = set()
        for msg in data.get("messages") or []:
            label_ids.update(msg.get("labelIds") or [])

        return ApplyLabelOutput(
            data=data,
            summary=ApplyLabelSummary(
                thread_id=payload.thread_id, label_ids=sorted(label_ids)
            ),
        )
