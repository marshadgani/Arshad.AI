"""Concrete OAuth providers built on _oauth_base.OAuthIntegrationProvider.

Each provider declares minimal config (auth_url, token_url, scopes,
client_id_env / client_secret_env) and implements fetch_profile() + sync().

Setup per provider (one-time):
  1. Register an OAuth app at the provider's developer console
  2. Set the redirect URI to:
     https://arshad-ai.onrender.com/api/v1/integrations/oauth/<slug>/callback
  3. Add <SLUG_UPPER>_CLIENT_ID and <SLUG_UPPER>_CLIENT_SECRET to Render env vars
  4. Click "Connect" in the Arshad.AI Integrations tab
"""

from __future__ import annotations

from typing import Any

import httpx

from ..registry import register
from ._oauth_base import OAuthIntegrationProvider, make_oauth_sync_via_api

# ── Spotify ──────────────────────────────────────────────────────────────


@register
class SpotifyIntegration(OAuthIntegrationProvider):
    slug = "spotify"
    display_name = "Spotify"
    category = "Lifestyle"
    description = "Recently played, top artists, saved tracks."
    docs_url = "https://developer.spotify.com/documentation/web-api"
    icon = "spotify"
    auth_url = "https://accounts.spotify.com/authorize"
    token_url = "https://accounts.spotify.com/api/token"
    scopes = [
        "user-read-recently-played",
        "user-top-read",
        "user-library-read",
        "user-read-private",
        "user-read-email",
    ]
    client_id_env = "SPOTIFY_CLIENT_ID"
    client_secret_env = "SPOTIFY_CLIENT_SECRET"
    use_basic_auth_for_token = True

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return {
            "spotify_id": body.get("id"),
            "display_name": body.get("display_name"),
            "email": body.get("email"),
        }

    sync = make_oauth_sync_via_api(
        sync_url="https://api.spotify.com/v1/me/top/artists?limit=10",
        parse_sync=lambda body: {
            "top_artists": [a.get("name") for a in (body or {}).get("items", [])]
        },
        summary_fmt="Spotify: top artists refreshed",
    )


# ── Strava ───────────────────────────────────────────────────────────────


@register
class StravaIntegration(OAuthIntegrationProvider):
    slug = "strava"
    display_name = "Strava"
    category = "Health"
    description = "Activities, segments, gear, athlete stats."
    docs_url = "https://developers.strava.com/docs/getting-started"
    icon = "strava"
    auth_url = "https://www.strava.com/oauth/authorize"
    token_url = "https://www.strava.com/oauth/token"
    scopes = ["read", "activity:read_all", "profile:read_all"]
    scope_separator = ","
    client_id_env = "STRAVA_CLIENT_ID"
    client_secret_env = "STRAVA_CLIENT_SECRET"
    additional_auth_params = {"approval_prompt": "auto"}

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.strava.com/api/v3/athlete",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return {
            "strava_id": body.get("id"),
            "username": body.get("username"),
            "firstname": body.get("firstname"),
        }

    sync = make_oauth_sync_via_api(
        sync_url="https://www.strava.com/api/v3/athlete/activities?per_page=10",
        parse_sync=lambda body: {
            "recent_activity_count": len(body or []),
            "recent_activities": [
                {
                    "name": a.get("name"),
                    "type": a.get("type"),
                    "distance_m": a.get("distance"),
                }
                for a in (body or [])[:5]
            ],
        },
        summary_fmt="Strava: recent activities refreshed",
    )


# ── Oura ─────────────────────────────────────────────────────────────────


@register
class OuraIntegration(OAuthIntegrationProvider):
    slug = "oura"
    display_name = "Oura Ring"
    category = "Health"
    description = "Sleep, readiness, activity scores."
    docs_url = "https://cloud.ouraring.com/v2/docs"
    icon = "oura"
    auth_url = "https://cloud.ouraring.com/oauth/authorize"
    token_url = "https://api.ouraring.com/oauth/token"
    scopes = ["personal", "daily", "heartrate", "session"]
    client_id_env = "OURA_CLIENT_ID"
    client_secret_env = "OURA_CLIENT_SECRET"

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.ouraring.com/v2/usercollection/personal_info",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return {
            "oura_id": body.get("id"),
            "email": body.get("email"),
            "age": body.get("age"),
        }

    async def sync(self, *, integration, db):  # type: ignore[override]
        # Rolling 7-day window — was hardcoded start_date='2026-04-20' which would
        # grow unboundedly over time and eventually return months of data per sync.
        from datetime import date, timedelta

        start_date = (date.today() - timedelta(days=7)).isoformat()
        # Build a temporary factory call with the dynamic URL.
        runner = make_oauth_sync_via_api(
            sync_url=f"https://api.ouraring.com/v2/usercollection/daily_readiness?start_date={start_date}",
            parse_sync=lambda body: {
                "readiness_count": len((body or {}).get("data", [])),
                "latest_readiness_score": (
                    ((body or {}).get("data", []) or [{}])[-1].get("score")
                ),
                "window_start": start_date,
            },
            summary_fmt="Oura: readiness refreshed",
        )
        return await runner(self, integration=integration, db=db)


# ── Fitbit ───────────────────────────────────────────────────────────────


@register
class FitbitIntegration(OAuthIntegrationProvider):
    slug = "fitbit"
    display_name = "Fitbit"
    category = "Health"
    description = "Daily activity, heart rate, sleep stages."
    docs_url = "https://dev.fitbit.com/build/reference/web-api/"
    icon = "fitbit"
    auth_url = "https://www.fitbit.com/oauth2/authorize"
    token_url = "https://api.fitbit.com/oauth2/token"
    scopes = ["activity", "heartrate", "sleep", "profile"]
    client_id_env = "FITBIT_CLIENT_ID"
    client_secret_env = "FITBIT_CLIENT_SECRET"
    use_basic_auth_for_token = True

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.fitbit.com/1/user/-/profile.json",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        user = body.get("user") or {}
        return {
            "fitbit_id": user.get("encodedId"),
            "display_name": user.get("displayName"),
        }

    sync = make_oauth_sync_via_api(
        sync_url="https://api.fitbit.com/1/user/-/profile.json",
        parse_sync=lambda body: {
            "display_name": (body.get("user") or {}).get("displayName"),
            "average_daily_steps": (body.get("user") or {}).get("averageDailySteps"),
        },
        summary_fmt="Fitbit: profile refreshed",
    )


# ── Coinbase ─────────────────────────────────────────────────────────────


@register
class CoinbaseIntegration(OAuthIntegrationProvider):
    slug = "coinbase"
    display_name = "Coinbase"
    category = "Finance"
    description = "Crypto holdings, transactions, prices."
    docs_url = "https://docs.cdp.coinbase.com/sign-in-with-coinbase/docs/welcome"
    icon = "coinbase"
    auth_url = "https://login.coinbase.com/oauth2/auth"
    token_url = "https://login.coinbase.com/oauth2/token"
    scopes = ["wallet:user:read", "wallet:accounts:read"]
    client_id_env = "COINBASE_CLIENT_ID"
    client_secret_env = "COINBASE_CLIENT_SECRET"

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.coinbase.com/v2/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        data = body.get("data") or {}
        return {
            "coinbase_id": data.get("id"),
            "name": data.get("name"),
            "email": data.get("email"),
        }

    sync = make_oauth_sync_via_api(
        sync_url="https://api.coinbase.com/v2/accounts",
        parse_sync=lambda body: {
            "account_count": len((body or {}).get("data", [])),
            "accounts": [
                {
                    "currency": (a.get("currency") or {}).get("code"),
                    "balance": (a.get("balance") or {}).get("amount"),
                }
                for a in (body or {}).get("data", [])[:10]
            ],
        },
        summary_fmt="Coinbase: account list refreshed",
    )


# ── Discord ──────────────────────────────────────────────────────────────


@register
class DiscordIntegration(OAuthIntegrationProvider):
    slug = "discord"
    display_name = "Discord"
    category = "Communication"
    description = "User profile, guilds, connections."
    docs_url = "https://discord.com/developers/docs/topics/oauth2"
    icon = "discord"
    auth_url = "https://discord.com/api/oauth2/authorize"
    token_url = "https://discord.com/api/oauth2/token"
    scopes = ["identify", "email", "guilds"]
    client_id_env = "DISCORD_CLIENT_ID"
    client_secret_env = "DISCORD_CLIENT_SECRET"

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return {
            "discord_id": body.get("id"),
            "username": body.get("username"),
            "email": body.get("email"),
        }

    sync = make_oauth_sync_via_api(
        sync_url="https://discord.com/api/users/@me/guilds",
        parse_sync=lambda body: {
            "guild_count": len(body or []),
            "guilds": [
                {"id": g.get("id"), "name": g.get("name")} for g in (body or [])[:5]
            ],
        },
        summary_fmt="Discord: guilds refreshed",
    )


# ── Reddit ───────────────────────────────────────────────────────────────


@register
class RedditIntegration(OAuthIntegrationProvider):
    slug = "reddit"
    display_name = "Reddit"
    category = "Lifestyle"
    description = "Saved posts, subscribed subreddits, profile."
    docs_url = "https://www.reddit.com/dev/api/oauth"
    icon = "reddit"
    auth_url = "https://www.reddit.com/api/v1/authorize"
    token_url = "https://www.reddit.com/api/v1/access_token"
    scopes = ["identity", "history", "mysubreddits", "save"]
    client_id_env = "REDDIT_CLIENT_ID"
    client_secret_env = "REDDIT_CLIENT_SECRET"
    use_basic_auth_for_token = True
    additional_auth_params = {"duration": "permanent"}

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://oauth.reddit.com/api/v1/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": "Arshad.AI/1.0",
                },
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return {
            "reddit_name": body.get("name"),
            "karma": body.get("total_karma"),
        }

    sync = make_oauth_sync_via_api(
        sync_url="https://oauth.reddit.com/subreddits/mine/subscriber?limit=20",
        parse_sync=lambda body: {
            "subreddit_count": len(
                ((body or {}).get("data") or {}).get("children") or []
            ),
        },
        summary_fmt="Reddit: subscriptions refreshed",
    )


# ── Linear (GraphQL POST — custom, not in factory) ───────────────────────


@register
class LinearIntegration(OAuthIntegrationProvider):
    """Linear supports OAuth2; their token grant is POST + GraphQL queries.
    Treated like a normal OAuth provider here, with a custom sync that POSTs
    a GraphQL viewer query.
    """

    slug = "linear"
    display_name = "Linear"
    category = "Productivity"
    description = "Issues, projects, cycles."
    docs_url = "https://developers.linear.app/docs/oauth/authentication"
    icon = "linear"
    auth_url = "https://linear.app/oauth/authorize"
    token_url = "https://api.linear.app/oauth/token"
    scopes = ["read"]
    scope_separator = ","
    client_id_env = "LINEAR_CLIENT_ID"
    client_secret_env = "LINEAR_CLIENT_SECRET"

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.linear.app/graphql",
                json={"query": "{ viewer { id name email } }"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        viewer = (body.get("data") or {}).get("viewer") or {}
        return {
            "linear_id": viewer.get("id"),
            "name": viewer.get("name"),
            "email": viewer.get("email"),
        }

    async def sync(self, *, integration, db):  # type: ignore[override]
        import time
        from datetime import datetime, timezone

        from ..base import IntegrationError, SyncResult

        started = time.perf_counter()
        access_token = await self.get_access_token(integration=integration, db=db)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.linear.app/graphql",
                    json={
                        "query": "{ issues(first: 10) { nodes { id title state { name } } } }"
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        nodes = ((body.get("data") or {}).get("issues") or {}).get("nodes") or []
        integration.config = {
            **(integration.config or {}),
            "issue_count": len(nodes),
            "issues": [{"id": n.get("id"), "title": n.get("title")} for n in nodes[:5]],
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=0,
            summary=f"Linear: {len(nodes)} recent issues refreshed",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


# ── Whoop ─────────────────────────────────────────────────────────────────


@register
class WhoopIntegration(OAuthIntegrationProvider):
    slug = "whoop"
    display_name = "Whoop"
    category = "Health"
    description = "Recovery scores, sleep analysis, strain, HRV, and workouts."
    docs_url = "https://developer.whoop.com"
    icon = "whoop"
    auth_url = "https://api.prod.whoop.com/oauth/oauth2/auth"
    token_url = "https://api.prod.whoop.com/oauth/oauth2/token"
    scopes = [
        "read:recovery",
        "read:sleep",
        "read:strain",
        "read:workout",
        "read:body_measurement",
        "read:profile",
        "offline",
    ]
    client_id_env = "WHOOP_CLIENT_ID"
    client_secret_env = "WHOOP_CLIENT_SECRET"

    _BASE = "https://api.prod.whoop.com/developer/v1"

    async def fetch_profile(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._BASE}/user/profile/basic",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            body = resp.json() or {}
        return {
            "whoop_user_id": body.get("user_id"),
            "email": body.get("email"),
            "first_name": body.get("first_name"),
        }

    async def sync(self, *, integration, db) -> "SyncResult":
        import time as _time
        from datetime import date, timedelta

        from ..base import IntegrationError, SyncResult

        started = _time.perf_counter()
        access_token = await self.get_access_token(integration=integration, db=db)
        start = (date.today() - timedelta(days=1)).isoformat()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._BASE}/recovery",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"limit": 1, "start": start},
                )
                resp.raise_for_status()
                body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            integration.status = "error"
            integration.last_error = f"{type(exc).__name__}: {exc}"[:500]
            await db.commit()
            raise IntegrationError("sync_failed", f"{type(exc).__name__}: {exc}")
        records = body.get("records") or []
        latest = records[0] if records else {}
        score = latest.get("score") or {}
        integration.config = {
            **(integration.config or {}),
            "latest_recovery_score": score.get("recovery_score"),
            "latest_hrv_rmssd": score.get("hrv_rmssd_milli"),
            "latest_resting_hr": score.get("resting_heart_rate"),
            "window_start": start,
        }
        integration.last_synced_at = datetime.now(timezone.utc)
        integration.last_error = None
        integration.status = "connected"
        await db.commit()
        return SyncResult(
            rows_written=len(records),
            summary="Whoop: recovery score refreshed.",
            duration_ms=int((_time.perf_counter() - started) * 1000),
        )
