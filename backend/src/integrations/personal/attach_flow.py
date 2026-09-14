"""Starting half of the "attach a provider to the current user" OAuth flow.

The attach flow has two halves that run in different processes-of-thought
and were previously written in two different modules' private helpers:

  * START (this module) — inside the authenticated
    ``POST /api/v1/integrations/{slug}/connect``. Mints a single-use,
    user-bound attach-state token and hands the browser the provider's own
    consent URL.
  * FINISH (`attach_callback.py`) — anonymous top-level redirect back from
    the provider.

Keeping the start half here means `_shared.py` no longer has to know about
OAuth providers, Redis state, or env-var failure modes at all; it only
decides *whether* an attach is needed and delegates.
"""

from __future__ import annotations

from ...auth.attach_state import store_attach_state
from ...auth.providers import get_login_provider
from ...models.user import User
from ..base import ConnectResult, IntegrationError


def _missing_credential_code(exc: RuntimeError) -> str:
    """`required_env` raises a bare RuntimeError naming the offending var."""
    return "missing_client_secret" if "SECRET" in str(exc) else "missing_client_id"


async def start_attach_flow(
    *,
    user: User,
    slug: str,
    oauth_provider: str,
) -> ConnectResult:
    """Return a ConnectResult whose redirect_url is the provider's consent page.

    Every failure is raised as an IntegrationError so the caller's
    ``POST /connect`` responds with a real error envelope — a bare
    RuntimeError here would surface as an unhandled 500, and a silent
    fallback would reproduce the original bounce-to-/login bug.
    """
    try:
        provider = get_login_provider(oauth_provider)
    except RuntimeError as exc:
        # Provider exists but its client id/secret is unset — surface a real
        # error envelope on the POST /connect response rather than a 500.
        raise IntegrationError(_missing_credential_code(exc), str(exc)) from exc

    if provider is None:
        raise IntegrationError(
            "unknown_oauth_provider", f"No OAuth provider '{oauth_provider}'."
        )

    try:
        attach_state = await store_attach_state(
            user_id=str(user.id), provider=oauth_provider, return_slug=slug
        )
    except Exception as exc:  # noqa: BLE001 — Redis unavailability, etc.
        raise IntegrationError(
            "state_unavailable",
            "Could not start the connect flow; try again.",
        ) from exc

    return ConnectResult(
        integration_id=None,
        redirect_url=provider.authorization_url(attach_state),
    )
