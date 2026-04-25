"""Abstract OAuth2 provider contract.

Each concrete provider implements:
  - authorization_url(state) -> str            (302 target for /login)
  - exchange_code(code) -> OAuthTokenBundle    (callback exchange)
  - fetch_user_info(access_token) -> OAuthUserInfo

The router orchestrates state -> redirect -> exchange -> user-info -> upsert.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


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
