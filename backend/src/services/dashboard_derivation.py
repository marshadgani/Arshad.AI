"""Import-path facade — re-exports from src.services.dashboard sub-package.

Kept for backwards compatibility with any code that imported from
``src.services.dashboard_derivation`` before the module was reorganised
into the ``dashboard/`` sub-package.
"""

from __future__ import annotations

from src.services.dashboard.formatting import (
    TITLE_LIMIT,
    clean_title,
    extract_repo_from_provider_id,
    humanize_due,
    humanize_elapsed,
    humanize_time,
)
from src.services.dashboard.heuristics import (
    apply_priority_heuristic,
    apply_severity_heuristic,
    is_actionable_pr,
)
from src.services.dashboard.projections import (
    derive_activities_from_github,
    derive_decisions_from_github,
    derive_notifications_from_github,
    derive_tasks_from_gmail,
    project_github_activity,
)
from src.services.dashboard.projections import (
    project_pr_decision as _project_pr_decision,
)
from src.services.dashboard.rows import (
    derived_of,
    occurred_at_of,
    project_all,
    raw_of,
    repo_or_github,
)
from src.services.dashboard.rows import (
    pr_opened_at as _pr_opened_at,
)
from src.services.dashboard.widget_types import (
    AgentTickDict,
    DecisionDict,
    GitHubActivityDict,
    GitHubActivityState,
    NotificationDict,
    TaskDict,
)

# Aliases used by existing characterisation tests that reference the private
# helpers by their old names.
_pr_opened_at = _pr_opened_at  # noqa: F841  (re-export alias)
_project_pr_decision = _project_pr_decision  # noqa: F841
_is_actionable_pr = is_actionable_pr  # noqa: F841

__all__ = [
    # formatting
    "TITLE_LIMIT",
    "clean_title",
    "extract_repo_from_provider_id",
    "humanize_due",
    "humanize_elapsed",
    "humanize_time",
    # heuristics
    "apply_priority_heuristic",
    "apply_severity_heuristic",
    "is_actionable_pr",
    # projections
    "derive_activities_from_github",
    "derive_decisions_from_github",
    "derive_notifications_from_github",
    "derive_tasks_from_gmail",
    "project_github_activity",
    # rows
    "derived_of",
    "occurred_at_of",
    "project_all",
    "raw_of",
    "repo_or_github",
    # widget_types
    "AgentTickDict",
    "DecisionDict",
    "GitHubActivityDict",
    "GitHubActivityState",
    "NotificationDict",
    "TaskDict",
    # private aliases for characterisation tests
    "_pr_opened_at",
    "_project_pr_decision",
    "_is_actionable_pr",
]
