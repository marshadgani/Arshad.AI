"""Which OAuth providers exist, in one place.

Adding a third login provider is a single entry here plus its
`OAuthProvider` implementation — `auth/routers.py` needs no change,
because the flow it runs is provider-agnostic. The registry returns
None for an unknown name rather than raising an HTTP error: knowing
that "unknown provider" means 404 is the HTTP layer's business, not
this module's.
"""

from __future__ import annotations

from typing import Callable

from .base import OAuthProvider
from .github import GitHubOAuthProvider
from .google import GoogleOAuthProvider

PROVIDER_FACTORIES: dict[str, Callable[[], OAuthProvider]] = {
    "google": GoogleOAuthProvider,
    "github": GitHubOAuthProvider,
}


def build_provider(name: str) -> OAuthProvider | None:
    factory = PROVIDER_FACTORIES.get(name)
    return factory() if factory else None
