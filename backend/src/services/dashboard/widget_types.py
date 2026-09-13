"""The typed contract between derivation and ``schemas/dashboard.py``.

Field names and Literal values match the Pydantic response models exactly,
so ``projections`` can hand these dicts straight to
``TaskResponse.model_validate`` and friends. Making that promise a
TypedDict rather than a docstring means a field renamed or dropped on
either side is a type-checker error at the call site, not a Pydantic
``ValidationError`` discovered by a test.

Declarations only — no behaviour, no imports from the rest of the package.
This is what lets ``heuristics`` and ``projections`` share the narrowed
Literal aliases without either importing the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from src.models.ingested import GitHubActivityKind

# Narrower than TaskResponse.priority's Literal["p0","p1","p2","p3"] — this
# alias states, in the type itself, exactly which subset
# apply_priority_heuristic can produce (it is a total function over all
# four). Kept distinct from the schema's Literal so widening the schema in
# the future can't silently imply this heuristic grew new outputs.
GmailPriority = Literal["p0", "p1", "p2", "p3"]

# Mirrors NotificationResponse.severity's Literal minus the values this
# package never emits ("info", "ok") — apply_severity_heuristic's signature
# states its own range instead of callers having to trust the docstring.
GitHubIssueSeverity = Literal["critical", "warn"]

# Mirrors GitHubActivityResponse.state. "merged" is derived (from
# raw.merged_at), not a value GitHub reports in raw.state.
GitHubActivityState = Literal["open", "closed", "merged"]


class TaskDict(TypedDict):
    """Exact field set TaskResponse.model_validate() requires for a
    Gmail-derived task. Keep in lock-step with schemas.dashboard.TaskResponse
    by hand — nothing else enforces the two staying aligned."""

    id: str
    title: str
    source: Literal["gmail"]
    due: str
    priority: GmailPriority


class AgentTickDict(TypedDict):
    """Exact field set AgentTickResponse.model_validate() requires."""

    id: str
    agent: str
    message: str
    time: str


class NotificationDict(TypedDict):
    """Exact field set NotificationResponse.model_validate() requires for a
    GitHub-derived notification."""

    id: str
    severity: GitHubIssueSeverity
    title: str
    detail: str
    time: str


class GitHubActivityDict(TypedDict):
    """Exact field set GitHubActivityResponse.model_validate() requires."""

    id: str
    title: str
    url: str | None
    number: int | None
    repository: str
    kind: GitHubActivityKind
    state: GitHubActivityState
    is_draft: bool
    author: str | None
    updated_at: str


class DecisionDict(TypedDict):
    """Exact field set DecisionResponse.model_validate() requires for a
    GitHub-derived decision. Keep in lock-step with
    schemas.dashboard.DecisionResponse by hand — nothing else enforces the
    two staying aligned."""

    id: str
    title: str
    context: str
    source: Literal["github"]
    waiting_since: str
