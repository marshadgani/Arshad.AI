"""Agent ABC + shared exception types.

Each agent subclasses ``Agent`` and registers via ``registry.register``.
The gateway and REST router both consume ``AGENT_REGISTRY``, keyed by
``slug = f"{domain}_{name}"``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User


class AgentError(Exception):
    """Generic agent execution error mapped by the router to 400/501."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgentNotImplemented(AgentError):
    """Raised by placeholder agents that Phase B/F will replace.

    Mapped to 501 by the router so the frontend can distinguish "this
    agent isn't ready yet" from "your input was bad".
    """

    def __init__(self, slug: str, owning_phase: str) -> None:
        super().__init__(
            code="not_yet_implemented",
            message=f"Agent '{slug}' is a Phase E placeholder; real logic ships in {owning_phase}.",
        )
        self.slug = slug


class Agent(ABC):
    """Each concrete agent defines:

    - ``domain`` — one of: calendar, email, github, ai_core, data_pipeline, infrastructure
    - ``name`` — snake_case slug, unique within a domain
    - ``description`` — for Phase B's Claude tool-use binding
    - ``input_schema`` / ``output_schema`` — Pydantic models. Output MUST
      contain ``data`` (raw response) and ``summary`` (normalized fields).
    - ``tool_dependencies`` — list of Phase D tool names this agent invokes
      (used for static analysis + Phase B's tool-use schema generation).
    - ``run`` — async, runs the agent. May raise ``AgentError`` subclasses
      or any ``ToolError`` from Phase D — the router maps both to envelopes.
    """

    domain: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    tool_dependencies: ClassVar[list[str]] = []

    @property
    def slug(self) -> str:
        return f"{self.domain}_{self.name}"

    @abstractmethod
    async def run(
        self,
        *,
        user: User,
        db: AsyncSession,
        payload: BaseModel,
    ) -> BaseModel: ...
