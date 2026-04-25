"""Google OAuth2 provider.

Scopes (Phase C-locked):
    openid email profile
    https://www.googleapis.com/auth/calendar.events
    https://www.googleapis.com/auth/gmail.modify
    https://www.googleapis.com/auth/gmail.send

Refresh tokens require access_type=offline + prompt=consent on the auth URL.
Without prompt=consent, Google only returns a refresh token on the FIRST
consent ever — re-auths after that omit it, which silently breaks Phase D.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from .base import OAuthProvider, OAuthTokenBundle, OAuthUserInfo

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


class GoogleOAuthProvider(OAuthProvider):
    name = "google"
    scopes = _SCOPES

    def __init__(self) -> None:
        self.client_id = _required("GOOGLE_OAUTH_CLIENT_ID")
        self.client_secret = _required("GOOGLE_OAUTH_CLIENT_SECRET")
        backend_url = _required("BACKEND_URL").rstrip("/")
        self.redirect_uri = f"{backend_url}/api/v1/auth/google/callback"

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokenBundle:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
        resp.raise_for_status()
        data = resp.json()
        expires_in = data.get("expires_in")
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            if expires_in
            else None
        )
        return OAuthTokenBundle(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=(data.get("scope") or "").split() or list(_SCOPES),
        )

    async def fetch_user_info(self, access_token: str) -> OAuthUserInfo:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        resp.raise_for_status()
        data = resp.json()
        return OAuthUserInfo(
            provider_user_id=data["sub"],
            email=data["email"].lower(),
            name=data.get("name"),
            avatar_url=data.get("picture"),
        )


def _required(var: str) -> str:
    val = os.getenv(var)
    if not val or val.startswith("your-"):
        raise RuntimeError(f"{var} is unset or still a placeholder")
    return val
