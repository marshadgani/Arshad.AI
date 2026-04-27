"""Enterprise Architect agent — invoked twice (pre_build + post_build)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from ..artifacts import BPDD, SDD, ArchReviewSignoff, FeatureCode
from .base import DevAgent


class EARequest(BaseModel):
    stage: Literal["pre_build", "post_build"]
    bpdd: BPDD
    sdd: SDD | None = None
    code: FeatureCode | None = None
    arch_context: str = ""


class EnterpriseArchitect(DevAgent):
    name = "ea"
    output_dir = "ea"
    input_schema = EARequest
    output_schema = ArchReviewSignoff
    prompt_file = "enterprise_architect.md"

    def build_user_message(
        self, *, feature_id: str, payload: BaseModel, **extra: Any
    ) -> str:
        assert isinstance(payload, EARequest)
        parts = [
            f"Feature ID: {feature_id}",
            f"Stage: {payload.stage}",
            "",
            "BPDD:",
            payload.bpdd.model_dump_json(indent=2),
        ]
        if payload.sdd is not None:
            parts += ["", "SDD:", payload.sdd.model_dump_json(indent=2)]
        if payload.code is not None:
            parts += [
                "",
                "Generated code summary:",
                payload.code.summary,
                "Files: " + ", ".join(f.path for f in payload.code.files),
            ]
        if payload.arch_context:
            parts += ["", "Architecture context:", payload.arch_context]
        return "\n".join(parts)
