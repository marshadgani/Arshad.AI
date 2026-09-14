"""Who may disconnect a *project-scoped* integration (FEAT-145).

Project integrations (`user_id IS NULL`) are shared deployment
infrastructure rather than one person's credential, so once disconnect()
started genuinely deleting credential rows, "any authenticated user" was
no longer an acceptable audience for that button.

This module holds the decision only — no FastAPI, no HTTPException, no DB
session. The router maps a Denied decision onto its 403 contract; the
policy itself stays independently readable and testable, and a future
caller (a CLI, an admin task) can reuse it without dragging in the HTTP
layer. See integrations/DECISION.md §2 for why the no-config default is
fail-open-with-WARNING rather than fail-closed.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Literal

_log = logging.getLogger(__name__)

ADMIN_USER_IDS_ENV = "INTEGRATION_ADMIN_USER_IDS"
ADMIN_EMAILS_ENV = "INTEGRATION_ADMIN_EMAILS"

# 'allowed'    — caller is a configured admin.
# 'unguarded'  — neither env var is configured; allowed, but logged at
#                WARNING so the fail-open default is never silent.
# 'denied'     — admins are configured and the caller is not one.
ProjectDisconnectDecision = Literal["allowed", "unguarded", "denied"]


def _csv_env(name: str, *, lower: bool = False) -> set[str]:
    """Read once per call (never cached) so a Render env-var edit takes
    effect without a redeploy. Empty set when unset or blank."""
    raw = os.getenv(name, "")
    values = (v.strip() for v in raw.split(","))
    return {v.lower() if lower else v for v in values if v}


def project_disconnect_decision(
    *, slug: str, user_id: uuid.UUID | str, email: str | None
) -> ProjectDisconnectDecision:
    """Decide whether this user may disconnect the shared integration `slug`."""
    admin_user_ids = _csv_env(ADMIN_USER_IDS_ENV)
    admin_emails = _csv_env(ADMIN_EMAILS_ENV, lower=True)

    if not admin_user_ids and not admin_emails:
        _log.warning(
            "integration.disconnect.unguarded_project_access slug=%s user_id=%s "
            "— %s/%s both unset",
            slug,
            user_id,
            ADMIN_USER_IDS_ENV,
            ADMIN_EMAILS_ENV,
        )
        return "unguarded"

    if str(user_id) in admin_user_ids or (email or "").lower() in admin_emails:
        return "allowed"
    return "denied"
