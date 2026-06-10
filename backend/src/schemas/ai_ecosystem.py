"""Pydantic v2 response schemas for the AI Ecosystem endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from . import ORMBase

AgentStatus = Literal["ACTIVE", "IDLE", "UNKNOWN"]
AgentCategory = Literal["development_team", "other"]
Period = Literal["1h", "1d", "1w", "1m", "1y"]


class AgentResponse(ORMBase):
    agent_name: str
    display_name: str
    purpose: str
    model: str
    category: AgentCategory
    pipeline_stage: int | None = None
    is_active: bool
    status: AgentStatus = "UNKNOWN"


class AgentMetricResponse(ORMBase):
    agent_name: str
    usage_count: int
    total_tokens: int
    avg_tokens_per_use: int
    success_rate: float
    efficiency_score: int = Field(ge=0, le=100)


class MetricsResponse(ORMBase):
    period: Period
    agents: list[AgentMetricResponse]


class SummaryResponse(ORMBase):
    period: Period
    total_invocations: int
    total_tokens: int
    most_used_agent: str | None = None
    most_efficient_agent: str | None = None


class LogRequest(ORMBase):
    agent_name: str
    model: str | None = None
    tokens_used: int = Field(default=0, ge=0)
    duration_ms: int | None = None
    success: bool = True
    session_id: uuid.UUID | None = None


class RegisterAgentRequest(ORMBase):
    agent_name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    purpose: str = Field(..., min_length=1)
    model: str = Field(default="claude-sonnet-4-6", max_length=100)
    category: AgentCategory = "other"
    pipeline_stage: int | None = None
    is_active: bool = True
