"""Bug Fixer agent — produces a new FeatureCode revision that closes every
defect in the input DefectCatalogue.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..artifacts import BugFixOutput, DefectCatalogue, FeatureCode
from .base import DevAgent


class BugFixRequest(BaseModel):
    catalogue: DefectCatalogue
    code: FeatureCode
    iteration: int


class BugFixer(DevAgent):
    name = "bugfixer"
    output_dir = "bugfixer"
    input_schema = BugFixRequest
    output_schema = BugFixOutput
    prompt_file = "bug_fixer.md"

    def build_user_message(
        self, *, feature_id: str, payload: BaseModel, **extra: Any
    ) -> str:
        assert isinstance(payload, BugFixRequest)
        files_block = "\n\n".join(
            f"--- {f.path} ({f.language}) ---\n{f.content}" for f in payload.code.files
        )
        return (
            f"Feature ID: {feature_id}\n"
            f"Iteration: {payload.iteration}\n\n"
            f"Defect catalogue:\n{payload.catalogue.model_dump_json(indent=2)}\n\n"
            f"Current code:\n{files_block}"
        )
