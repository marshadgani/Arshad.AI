"""Tool ABC + shared exception types.

Every tool subclasses ``Tool`` and is registered in ``registry.TOOL_REGISTRY``.
The REST router (``routers.py``) and Phase B chat both consume this map.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User


class ToolError(Exception):
    """Generic tool execution error mapped to 400 by the router."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderNotLinked(ToolError):
    """User hasn't completed OAuth for this provider yet.

    Maps to 400 ``oauth_account_not_linked`` so the frontend can prompt
    the user to sign in with the missing provider.
    """

    def __init__(self, provider: str) -> None:
        super().__init__(
            code="oauth_account_not_linked",
            message=f"User has not linked {provider}. Sign in with {provider} first.",
        )
        self.provider = provider


class ProviderReauthRequired(ToolError):
    """OAuth token revoked / refresh denied / scopes removed.

    Maps to 401 ``<provider>_reauth_required`` so the frontend can show
    a "click to reconnect" CTA. For Google this is raised after a refresh
    attempt fails. For GitHub, raised on the FIRST 401 since GitHub OAuth
    Apps don't issue refresh tokens (locked Phase C decision).
    """

    def __init__(self, provider: str) -> None:
        super().__init__(
            code=f"{provider}_reauth_required",
            message=f"{provider} access has been revoked. Reconnect to continue.",
        )
        self.provider = provider


class Tool(ABC):
    """Each concrete tool defines:

    - ``name`` — slug used as URL path AND registry key (snake_case, prefixed
      by provider, e.g. ``calendar_list_events``)
    - ``description`` — for Claude's tool-use schema (Phase B)
    - ``input_schema`` / ``output_schema`` — Pydantic models. The output
      schema MUST contain at least ``data`` (raw provider JSON) and
      ``summary`` (normalized fields for chat surfacing) per Phase D §2.5.
    - ``__call__`` — async, runs the tool. Raises ToolError subclasses on
      provider failures; raises Pydantic ``ValidationError`` if the input
      payload is malformed (the router maps that to 400 invalid_input).
    """

    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    async def __call__(
        self,
        *,
        user: User,
        db: AsyncSession,
        payload: BaseModel,
    ) -> BaseModel: ...
