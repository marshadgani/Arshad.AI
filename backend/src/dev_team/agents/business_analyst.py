"""Business Analyst agent.

In:  raw requirement string
Out: RTM + BPDD (BAOutput)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..artifacts import BAOutput
from .base import DevAgent


class BARequest(BaseModel):
    requirement: str = Field(min_length=1, max_length=10_000)


class BusinessAnalyst(DevAgent):
    name = "ba"
    output_dir = "ba"
    input_schema = BARequest
    output_schema = BAOutput
    prompt_file = "business_analyst.md"
