"""Single source of truth for dag_id <-> integration slug.

Every queue-backed provider declares its dag_id exactly once, on
IntegrationProvider.sync_dag_id (see integrations/base.py). This module
derives the reverse mapping from the live registry instead of duplicating
the pairing anywhere else, so runner.py and routers.py can never drift
from what a provider actually declares.

obsidian_ingestor has no registered IntegrationProvider (Obsidian sync is
driven directly by api/v1/obsidian.py, not the integrations registry) —
it is the one explicit exception, called out below rather than silently
falling through.
"""

from __future__ import annotations

_EXPLICIT_FALLBACKS: dict[str, str] = {
    "obsidian_ingestor": "obsidian",
}


def dag_to_slug(dag_id: str) -> str | None:
    """Resolve a dag_id to the integration slug whose last_synced_at /
    last_error should be updated after that dag runs. Returns None for a
    dag_id with no matching slug (e.g. analytics_processor) — callers
    treat that as a silent no-op, not an error."""
    from ...integrations.registry import all_providers  # avoid import cycle

    for provider in all_providers():
        if provider.sync_dag_id == dag_id:
            return provider.slug
    return _EXPLICIT_FALLBACKS.get(dag_id)
