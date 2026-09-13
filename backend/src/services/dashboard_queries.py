"""Import-path facade — re-exports from src.services.dashboard.queries.

Kept for backwards compatibility with any code that imported from
``src.services.dashboard_queries`` before the module was moved into the
``dashboard/`` sub-package.
"""

from __future__ import annotations

from src.services.dashboard.queries import (
    GITHUB_ACTIVITY_LIMIT,
    LIVE_ROW_LIMIT,
    fetch_flagged_gmail_threads,
    fetch_github_activity_by_kind,
    fetch_github_provider_user_id,
    fetch_recent_github_activity,
)

__all__ = [
    "LIVE_ROW_LIMIT",
    "GITHUB_ACTIVITY_LIMIT",
    "fetch_flagged_gmail_threads",
    "fetch_github_activity_by_kind",
    "fetch_github_provider_user_id",
    "fetch_recent_github_activity",
]
