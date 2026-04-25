"""GitHub OAuth provider.

Scope: read:user user:email repo (full repo, includes private).

GitHub OAuth Apps (NOT GitHub Apps) don't issue refresh tokens — access
tokens are long-lived. token_expires_at is always None for GitHub rows.

The /user endpoint may return a null email when the user has hidden their
primary email. Falling back to /user/emails picks the verified primary.
"""

from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx

from .base import OAuthProvider, OAuthTokenBundle, OAuthUserInfo

_AUTH_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"

_SCOPES = ["read:user", "user:email", "repo"]


class GitHubOAuthProvider(OAuthProvider):
    name = "github"
    scopes = _SCOPES

    def __init__(self) -> None:
        self.client_id = _required("GITHUB_OAUTH_CLIENT_ID")
        self.client_secret = _required("GITHUB_OAUTH_CLIENT_SECRET")
        backend_url = _required("BACKEND_URL").rstrip("/")
        self.redirect_uri = f"{backend_url}/api/v1/auth/github/callback"

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(_SCOPES),
            "state": state,
            "allow_signup": "false",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokenBundle:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"GitHub token exchange failed: {data}")
        return OAuthTokenBundle(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=None,
            scopes=(data.get("scope") or "").split(",")
            if data.get("scope")
            else list(_SCOPES),
        )

    async def fetch_user_info(self, access_token: str) -> OAuthUserInfo:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            user_resp = await client.get(_USER_URL)
            user_resp.raise_for_status()
            user = user_resp.json()
            email = user.get("email")
            if not email:
                emails_resp = await client.get(_EMAILS_URL)
                emails_resp.raise_for_status()
                primary = next(
                    (
                        e
                        for e in emails_resp.json()
                        if e.get("primary") and e.get("verified")
                    ),
                    None,
                )
                if not primary:
                    raise RuntimeError("GitHub returned no primary verified email")
                email = primary["email"]
        return OAuthUserInfo(
            provider_user_id=str(user["id"]),
            email=email.lower(),
            name=user.get("name") or user.get("login"),
            avatar_url=user.get("avatar_url"),
        )


def _required(var: str) -> str:
    val = os.getenv(var)
    if not val or val.startswith("your-"):
        raise RuntimeError(f"{var} is unset or still a placeholder")
    return val
