"""Abstract OAuth2 provider contract.

Each concrete provider implements:
  - authorization_url(state) -> str            (302 target for /login)
  - exchange_code(code) -> OAuthTokenBundle    (callback exchange)
  - fetch_user_info(access_token) -> OAuthUserInfo

The router orchestrates state -> redirect -> exchange -> user-info -> upsert.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class OAuthError(Exception):
    """Raised when a provider rejects the auth flow for a non-network reason
    (e.g. GitHub returns no verified primary email, Google omits a refresh
    token on a re-consent). Routers map this to a 400/502 envelope.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def required_env(var: str) -> str:
    """Read an env var, refusing placeholders.

    Lifted out of google.py / github.py — both providers had character-
    identical copies that silently drift when the placeholder pattern changes.
    """
    val = os.getenv(var)
    if not val or val.startswith("your-"):
        raise RuntimeError(f"{var} is unset or still a placeholder")
    return val


@dataclass(frozen=True)
class OAuthUserInfo:
    provider_user_id: str
    email: str
    name: str | None
    avatar_url: str | None


@dataclass(frozen=True)
class OAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: list[str]


class OAuthProvider(ABC):
    name: str
    scopes: list[str]

    @abstractmethod
    def authorization_url(self, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str) -> OAuthTokenBundle: ...

    @abstractmethod
    async def fetch_user_info(self, access_token: str) -> OAuthUserInfo: ...
