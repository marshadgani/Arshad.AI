"""infrastructure/auth_manager — read-only profile + linked-providers view.

Phase C owns OAuth flows and JWT issuance. This agent exposes the
calling user's profile + a list of which providers they've linked, so
the frontend can render 'connected as: ... · Google ✓ · GitHub ✓'
without a separate /auth/me + /auth/providers round-trip.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.oauth_account import OAuthAccount
from ...models.user import User
from ..base import Agent
from ..registry import register


class AuthManagerInput(BaseModel):
    pass


class AuthManagerSummary(BaseModel):
    user_id: str
    email: str
    name: str | None
    avatar_url: str | None
    linked_providers: list[str]


class AuthManagerOutput(BaseModel):
    data: dict[str, Any]
    summary: AuthManagerSummary


@register
class AuthManagerAgent(Agent):
    domain = "infrastructure"
    name = "auth_manager"
    description = (
        "Returns the current user's profile and linked OAuth providers. "
        "Read-only thin wrapper over the Phase C tables — the actual OAuth "
        "flow + JWT issuance are at /api/v1/auth/*."
    )
    input_schema = AuthManagerInput
    output_schema = AuthManagerOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> AuthManagerOutput:
        rows = (
            await db.scalars(
                select(OAuthAccount).where(OAuthAccount.user_id == user.id)
            )
        ).all()
        providers = sorted({row.provider for row in rows})
        return AuthManagerOutput(
            data={"providers": providers, "account_count": len(rows)},
            summary=AuthManagerSummary(
                user_id=str(user.id),
                email=user.email,
                name=user.name,
                avatar_url=user.avatar_url,
                linked_providers=providers,
            ),
        )
