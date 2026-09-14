"""Login allowlist — restricts who may create/use an account via OAuth.

Arshad.AI is a single-user personal assistant (CLAUDE.md §1), but without
this gate `upsert_user_from_oauth` (auth/service.py) creates a full User
row for ANY Google or GitHub account that completes OAuth consent, and
`_find_user_integration` (integrations/routers.py) lets any authenticated
user read/sync/disconnect the deployment's shared, project-scoped
credentials (Stripe, Cloudflare, Render, Vercel, Supabase, the Anthropic
admin key, ...) because those rows have `user_id IS NULL` by design.
AUTH_ALLOWED_EMAILS closes both: only listed emails may log in (checked
on every request via auth/dependencies.py, not just at login — a JWT
issued before this gate existed must not keep working), and only listed
emails may mutate a shared integration.

Deny-by-default: an empty AUTH_ALLOWED_EMAILS denies everyone unless
AUTH_ALLOW_ALL_LOGINS is explicitly set (local dev only — see
.env.example). Earlier versions of this gate inferred "am I in
production" from BACKEND_URL's URL scheme and only enforced there; that
heuristic is unreliable (an unset/misconfigured BACKEND_URL silently
disabled the entire gate with no error). Requiring an explicit opt-in
for the permissive case removes that failure mode instead of trying to
detect it.
"""

from __future__ import annotations

import os


def is_production_backend() -> bool:
    """Best-effort "are we a real deployment" signal, used only for the
    early/loud main.py startup check — never as the sole safety mechanism
    (see module docstring: is_email_allowed() denies by default regardless
    of this). RENDER is set unconditionally on every Render service
    (independent of app-level config, so a misconfigured/unset BACKEND_URL
    can't silently defeat it); BACKEND_URL's scheme is kept as a secondary
    signal for non-Render deployments.
    """
    return os.getenv("RENDER", "").strip().lower() == "true" or os.getenv(
        "BACKEND_URL", ""
    ).startswith("https")


def allowed_emails() -> set[str]:
    raw = os.getenv("AUTH_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_local_dev_open_login() -> bool:
    return os.getenv("AUTH_ALLOW_ALL_LOGINS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def is_email_allowed(email: str | None) -> bool:
    """True if login/ownership should be permitted for this email.

    Deny-by-default when AUTH_ALLOWED_EMAILS is empty, unless
    AUTH_ALLOW_ALL_LOGINS is explicitly set (local dev only).
    """
    if not email:
        return False
    allowed = allowed_emails()
    if not allowed:
        return is_local_dev_open_login()
    return email.strip().lower() in allowed
