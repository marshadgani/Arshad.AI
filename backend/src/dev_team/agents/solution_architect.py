"""Solution Architect agent."""

from __future__ import annotations

from pydantic import BaseModel

from ..artifacts import BPDD, SDD
from .base import DevAgent


class SARequest(BaseModel):
    bpdd: BPDD


class SolutionArchitect(DevAgent):
    name = "sa"
    output_dir = "sa"
    input_schema = SARequest
    output_schema = SDD
    prompt_file = "solution_architect.md"
