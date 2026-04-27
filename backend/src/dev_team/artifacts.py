"""Pydantic models for every artifact passed between agents.

Every cross-agent boundary uses these — never raw strings. Adding a field
here forces every consumer to handle it (the type checker tells us where).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── Requirements Traceability Matrix (BA output) ────────────────────────


class RTMRow(BaseModel):
    requirement_id: str = Field(description="REQ-NNN within this feature")
    description: str
    priority: Literal["must", "should", "could"]
    acceptance_criteria: list[str] = Field(default_factory=list)


class RTM(BaseModel):
    feature_id: str
    rows: list[RTMRow]


# ── Business Process Design Document (BA output) ────────────────────────


class ProcessStep(BaseModel):
    step_id: str
    actor: str
    action: str
    pre_conditions: list[str] = Field(default_factory=list)
    post_conditions: list[str] = Field(default_factory=list)


class BPDD(BaseModel):
    feature_id: str
    feature_name: str
    domain: str
    sub_section: str
    business_objective: str
    actors: list[str]
    process_steps: list[ProcessStep]
    business_rules: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class BAOutput(BaseModel):
    rtm: RTM
    bpdd: BPDD


# ── Enterprise Architect output ─────────────────────────────────────────


class ArchReviewSignoff(BaseModel):
    feature_id: str
    stage: Literal["pre_build", "post_build"]
    decision: Literal["approved", "approved_with_notes", "rejected"]
    misalignments: list[str] = Field(default_factory=list)
    refinement_notes: list[str] = Field(default_factory=list)


# ── Solution Design Document (SA output) ────────────────────────────────


class Component(BaseModel):
    name: str
    responsibility: str
    interfaces: list[str] = Field(default_factory=list)


class DataModel(BaseModel):
    name: str
    fields: list[dict[str, str]]
    notes: str = ""


class ApiSpec(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    summary: str
    request_schema: dict | None = None
    response_schema: dict | None = None


class SDD(BaseModel):
    feature_id: str
    components: list[Component]
    data_models: list[DataModel] = Field(default_factory=list)
    apis: list[ApiSpec] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    technical_approach: str


# ── Developer output ────────────────────────────────────────────────────


class GeneratedFile(BaseModel):
    path: str
    content: str
    language: str = "python"


class FeatureCode(BaseModel):
    feature_id: str
    files: list[GeneratedFile]
    summary: str


# ── Process Organiser output ────────────────────────────────────────────


class PHEntry(BaseModel):
    feature_id: str
    feature_name: str
    domain: str
    sub_section: str
    added_at: str


class POOutput(BaseModel):
    entry: PHEntry
    file_path: str = "tasks/process-hierarchy.md"


# ── Test Script Writer output ───────────────────────────────────────────


class TestScript(BaseModel):
    test_id: str
    scenario: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str]
    expected: str
    linked_requirements: list[str] = Field(default_factory=list)


class TestScripts(BaseModel):
    feature_id: str
    scripts: list[TestScript]


# ── Tester output ───────────────────────────────────────────────────────


class Defect(BaseModel):
    defect_id: str
    test_id: str
    severity: Literal["critical", "high", "medium", "low"]
    description: str
    expected: str
    actual: str
    file_hint: str | None = None


class DefectCatalogue(BaseModel):
    feature_id: str
    iteration: int
    defects: list[Defect] = Field(default_factory=list)
    summary: str = ""


# ── Bug Fixer output ────────────────────────────────────────────────────


class BugFixOutput(BaseModel):
    feature_id: str
    iteration: int
    fixed_code: FeatureCode
    fixes_applied: list[str]


# ── Pipeline result (Orchestrator output) ───────────────────────────────


class PipelineResult(BaseModel):
    feature_id: str
    requirement: str
    status: Literal["completed", "halted", "cancelled"]
    halt_reason: str | None = None
    bug_fix_iterations: int = 0
    final_defect_count: int = 0
    duration_seconds: float = 0.0
    artifact_paths: dict[str, str] = Field(default_factory=dict)
