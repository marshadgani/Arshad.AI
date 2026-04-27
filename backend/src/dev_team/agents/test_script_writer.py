"""Test Script Writer agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..artifacts import BPDD, SDD, TestScripts
from .base import DevAgent


class TSWRequest(BaseModel):
    bpdd: BPDD
    sdd: SDD


class TestScriptWriter(DevAgent):
    name = "tsw"
    output_dir = "tsw"
    input_schema = TSWRequest
    output_schema = TestScripts
    prompt_file = "test_script_writer.md"

    def build_user_message(
        self, *, feature_id: str, payload: BaseModel, **extra: Any
    ) -> str:
        assert isinstance(payload, TSWRequest)
        return (
            f"Feature ID: {feature_id}\n\n"
            f"BPDD:\n{payload.bpdd.model_dump_json(indent=2)}\n\n"
            f"SDD:\n{payload.sdd.model_dump_json(indent=2)}"
        )
