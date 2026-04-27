"""Tester agent — static review of code against test scripts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..artifacts import DefectCatalogue, FeatureCode, TestScripts
from .base import DevAgent


class TesterRequest(BaseModel):
    scripts: TestScripts
    code: FeatureCode
    iteration: int = 0


class Tester(DevAgent):
    name = "tester"
    output_dir = "tester"
    input_schema = TesterRequest
    output_schema = DefectCatalogue
    prompt_file = "tester.md"

    def build_user_message(
        self, *, feature_id: str, payload: BaseModel, **extra: Any
    ) -> str:
        assert isinstance(payload, TesterRequest)
        files_block = "\n\n".join(
            f"--- {f.path} ({f.language}) ---\n{f.content}" for f in payload.code.files
        )
        return (
            f"Feature ID: {feature_id}\n"
            f"Iteration: {payload.iteration}\n\n"
            f"Test scripts:\n{payload.scripts.model_dump_json(indent=2)}\n\n"
            f"Code under test:\n{files_block}"
        )
