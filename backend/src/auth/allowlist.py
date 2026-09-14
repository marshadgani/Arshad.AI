"""Login allowlist — restricts who may create/use an account via OAuth.

Arshad.AI is a single-user personal assistant (CLAUDE.md §1), but without
this gate `upsert_user_from_oauth` (auth/service.py) creates a full User
row for ANY Google or GitHub account that completes OAuth consent, and
`_find_user_integration` (integrations/routers.py) lets any authenticated
user read/sync/disconnect the deployment's shared, project-scoped
credentials (Stripe, Cloudflare, Render, Vercel, Supabase, the Anthropic
admin key, ...) because those rows have `user_id IS NULL` by design.
AUTH_ALLOWED_EMAILS closes both: only listed emails may log in, and only
listed emails may mutate a shared integration.
"""

from __future__ import annotations

import os


def allowed_emails() -> set[str]:
    raw = os.getenv("AUTH_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_email_allowed(email: str) -> bool:
    """True if login/ownership should be permitted for this email.

    An empty AUTH_ALLOWED_EMAILS means "allow everyone" — local dev only.
    main.py fails startup if this is unset in production, so an empty
    allowlist should never actually occur there.
    """
    allowed = allowed_emails()
    if not allowed:
        return True
    return email.strip().lower() in allowed
