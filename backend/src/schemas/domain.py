"""Pydantic v2 response schemas for domain catalogue + sidebar nav."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DomainKPIResponse(_ORM):
    label: str
    value: str
    delta: str | None = None


class DomainApplicationResponse(_ORM):
    id: str
    name: str
    description: str
    status: Literal["live", "beta", "planned"]


class DomainAgentResponse(_ORM):
    name: str
    description: str
    health: Literal["healthy", "training", "degraded", "offline"]
    uptime: str
    accuracy: int
    last_action: str = Field(serialization_alias="lastAction")
    last_run: str = Field(serialization_alias="lastRun")


class DomainFeedRowResponse(_ORM):
    id: str
    message: str
    time: str


class DomainSummary(_ORM):
    """Lightweight summary used by ``GET /api/v1/domains`` (list)."""

    slug: str
    title: str
    emoji: str
    tagline: str


class DomainConfigResponse(_ORM):
    """Full domain config returned by ``GET /api/v1/domains/{slug}``.

    Matches the frontend's ``DomainConfig`` interface 1:1 so
    ``DomainPage.tsx`` consumes it without a transformer.
    """

    slug: str
    title: str
    emoji: str
    tagline: str
    kpis: list[DomainKPIResponse]
    applications: list[DomainApplicationResponse]
    agents: list[DomainAgentResponse]
    feed: list[DomainFeedRowResponse]


class NavItemResponse(_ORM):
    path: str = Field(serialization_alias="to")
    label: str
    icon: str
    domain: str | None = None
