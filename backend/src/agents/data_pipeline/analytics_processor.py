"""data_pipeline/analytics_processor — placeholder; needs ingested data first."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.user import User
from ..base import Agent, AgentNotImplemented
from ..registry import register


class AnalyticsProcessorInput(BaseModel):
    window_days: int = 7


class AnalyticsProcessorOutput(BaseModel):
    data: dict[str, Any]
    summary: dict[str, Any]


@register
class AnalyticsProcessorAgent(Agent):
    domain = "data_pipeline"
    name = "analytics_processor"
    description = (
        "Aggregates ingested Calendar/Gmail/GitHub data into summary tables. "
        "Phase E: not implemented — needs data ingested first (Phase F)."
    )
    input_schema = AnalyticsProcessorInput
    output_schema = AnalyticsProcessorOutput
    tool_dependencies: list[str] = []

    async def run(
        self, *, user: User, db: AsyncSession, payload: BaseModel
    ) -> AnalyticsProcessorOutput:
        raise AgentNotImplemented(slug=self.slug, owning_phase="Phase F")
