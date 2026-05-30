"""github/issue_manager — verb-routed issue CRUD.

Single endpoint that dispatches to list_issues / create_issue / update_issue
based on the ``action`` field. Lets the caller (Phase B chat) bind one tool
and get all three behaviours.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ...tools.github.create_issue import (
    CreateIssueInput,
    GitHubCreateIssue,
)
from ...tools.github.list_issues import (
    GitHubListIssues,
    ListIssuesInput,
)
from ...tools.github.update_issue import (
    GitHubUpdateIssue,
    UpdateIssueInput,
)
from ..base import Agent, AgentError
from ..registry import register


class IssueManagerInput(BaseModel):
    action: Literal["list", "create", "update"]
    list_args: ListIssuesInput | None = None
    create_args: CreateIssueInput | None = None
    update_args: UpdateIssueInput | None = None

    @model_validator(mode="after")
    def _action_args_match(self) -> "IssueManagerInput":
        required = {
            "list": "list_args",
            "create": "create_args",
            "update": "update_args",
        }[self.action]
        if getattr(self, required) is None:
            raise ValueError(f"action='{self.action}' requires {required}")
        return self


class IssueManagerOutput(BaseModel):
    action: str
    data: Any  # dict for create/update, list[dict] for list
    summary: Any = Field(description="Tool-specific summary; shape depends on action")


@register
class IssueManagerAgent(Agent):
    domain = "github"
    name = "issue_manager"
    description = (
        "Verb-routed GitHub issue CRUD. action='list' lists issues; "
        "'create' opens a new issue; 'update' patches an existing issue. "
        "Phase B may split this into separate intents."
    )
    input_schema = IssueManagerInput
    output_schema = IssueManagerOutput
    tool_dependencies = [
        "github_list_issues",
        "github_create_issue",
        "github_update_issue",
    ]

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> IssueManagerOutput:
        assert isinstance(payload, IssueManagerInput)
        if payload.action == "list":
            assert payload.list_args is not None
            r = await GitHubListIssues()(user=user, db=db, payload=payload.list_args)
        elif payload.action == "create":
            assert payload.create_args is not None
            r = await GitHubCreateIssue()(user=user, db=db, payload=payload.create_args)
        elif payload.action == "update":
            assert payload.update_args is not None
            r = await GitHubUpdateIssue()(user=user, db=db, payload=payload.update_args)
        else:  # pragma: no cover — Pydantic Literal blocks this
            raise AgentError("invalid_action", f"Unknown action: {payload.action}")
        return IssueManagerOutput(
            action=payload.action,
            data=r.data,
            summary=r.summary,
        )
