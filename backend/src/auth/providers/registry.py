"""The set of OAuth providers that can authenticate an Arshad.AI user.

Three call sites need to turn the string "google"/"github" into a live
`OAuthProvider`, and each previously carried its own hand-written
if/elif ladder:

  * `auth/routers.py._provider`             -> raised HTTPException(404)
  * `integrations/personal/_shared.py._make_provider`  -> raised IntegrationError
  * `integrations/personal/attach_callback.py._provider_for` -> raised AttachError

Adding a fourth login provider meant remembering all three. The *set* of
providers is a single fact and now lives here once; the *error* raised for
an unknown name stays with each caller, because a 404 envelope, a
`ConnectResult` error code, and a redirect query param are genuinely
different contracts. `get_login_provider` therefore returns ``None``
rather than raising — the caller supplies the policy.

Instantiation is deliberately lazy (factories, not singletons): each
provider's ``__init__`` calls ``required_env`` and raises RuntimeError when
its client id/secret is unset. Constructing them at import time would turn
a missing GitHub secret into a boot failure for the whole app, including
the Google half of the flow.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from .base import OAuthProvider
from .github import GitHubOAuthProvider
from .google import GoogleOAuthProvider

_FACTORIES: Final[Mapping[str, Callable[[], OAuthProvider]]] = {
    GoogleOAuthProvider.name: GoogleOAuthProvider,
    GitHubOAuthProvider.name: GitHubOAuthProvider,
}


def get_login_provider(name: str) -> OAuthProvider | None:
    """Build the provider for `name`, or return None if there is no such provider.

    Propagates RuntimeError from the provider's own ``required_env`` checks
    when the provider exists but is not configured — callers distinguish
    "unknown provider" (None) from "known but misconfigured" (RuntimeError).
    """
    factory = _FACTORIES.get(name)
    return factory() if factory is not None else None
