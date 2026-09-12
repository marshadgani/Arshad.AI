"""Whoop integration-record lifecycle: lookup, error classification, and
the status transitions that follow a fetch attempt.

Thin binding over src/services/integrations/state.py — the shared,
slug-parameterised implementation. This module supplies WHOOP_SLUG and
REAUTH_CODES and re-exports the four functions bound to them, so every
existing call site (src/api/v1/whoop.py) keeps working unmodified and with
identical behaviour. See services/integrations/state.py for the rules
themselves; this file is deliberately thin.
"""

from __future__ import annotations

from ...models.integration import Integration
from ..integrations import state as _shared

WHOOP_SLUG = "whoop"

# IntegrationError codes raised by the OAuth token layer that mean the user
# must re-approve access — no amount of retrying will fix them.
REAUTH_CODES = frozenset(
    {
        "refresh_failed",
        "no_refresh_token",
        "not_connected",
        "token_decryption_failed",
    }
)

ACTIVE_STATUSES = _shared.ACTIVE_STATUSES
UPSTREAM_FALLBACK_STATUS = _shared.UPSTREAM_FALLBACK_STATUS


async def find_integration(user_id: str, db) -> Integration | None:  # type: ignore[no-untyped-def]
    """The user's Whoop integration, if it is in any active status."""
    return await _shared.find_integration(user_id, WHOOP_SLUG, db)


def classify_error(exc: Exception) -> tuple[bool, int]:
    return _shared.classify_error(exc, REAUTH_CODES)


apply_error_status = _shared.apply_error_status
mark_healthy = _shared.mark_healthy


def profile_first_name(integration: Integration) -> str | None:
    """Whoop first name from the integration config.

    Profile metadata is nested under config['profile'] — written there by
    upsert_oauth_integration in integrations/_oauth_base.py — not a flat
    config key. Read in one place so that stays true at one call site.
    """
    config = integration.config or {}
    return (config.get("profile") or {}).get("first_name")
