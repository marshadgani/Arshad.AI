"""Process Organiser agent.

Receives feature_id + feature_name + domain + sub_section + timestamp.
Emits a POOutput; the pipeline then calls process_hierarchy.update_phd()
to atomically append the entry to tasks/process-hierarchy.md.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..artifacts import POOutput
from .base import DevAgent


class PORequest(BaseModel):
    feature_id: str
    feature_name: str
    domain: str
    sub_section: str
    added_at: str


class ProcessOrganiser(DevAgent):
    name = "po"
    output_dir = "po"
    input_schema = PORequest
    output_schema = POOutput
    prompt_file = "process_organiser.md"

    def build_user_message(
        self, *, feature_id: str, payload: BaseModel, **extra: Any
    ) -> str:
        assert isinstance(payload, PORequest)
        return (
            f"Feature ID: {feature_id}\n"
            f"Feature name: {payload.feature_name}\n"
            f"Domain: {payload.domain}\n"
            f"Sub-section: {payload.sub_section}\n"
            f"Timestamp (use this exact value for added_at): {payload.added_at}\n"
        )
