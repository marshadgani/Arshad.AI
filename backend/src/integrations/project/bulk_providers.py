"""Declarative API-key providers built via the spec factory.

Each block instantiates a provider class and registers it. Adding a new
provider = adding a ProviderSpec block.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from ..base import (
    IntegrationError,
    UpstreamRevocation,
    cannot_revoke,
    revokes_via,
)
from ..registry import register
from ._factory import ProviderSpec, make_provider

_REVOKE_TIMEOUT_S = 10.0


# Every provider in this module authenticates with a key the user pasted
# in, minted by hand in a dashboard. Almost none of them let that key
# delete itself over the API — key lifecycle is a dashboard-only
# operation — so disconnect() can destroy our encrypted copy but cannot
# make the key stop working. Saying so per provider, in the user's own
# terms, is the whole point: a blanket "credentials revoked" claim in the
# disconnect dialog was true for none of them.
def _dashboard_only(provider: str, where: str) -> UpstreamRevocation:
    return cannot_revoke(
        f"{provider} has no API for deleting an API key, so the key itself is "
        f"not revoked — only Arshad.AI's encrypted copy is deleted. Delete the "
        f"key at {where} to revoke it fully."
    )


async def _slack_auth_revoke(api_key: str) -> None:
    """Revoke a Slack token via auth.revoke.

    Unusual among the providers here in that the token can revoke itself,
    with no separate admin credential — so Slack is the one API-key
    integration whose disconnect genuinely ends access at the provider.

    Slack reports failure as HTTP 200 with `ok: false`, so the status code
    alone proves nothing; `revoked: true` is the only evidence the call
    did anything, and anything else raises for disconnect() to log.
    """
    async with httpx.AsyncClient(timeout=_REVOKE_TIMEOUT_S) as client:
        resp = await client.post(
            "https://slack.com/api/auth.revoke",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    resp.raise_for_status()
    body = resp.json() or {}
    if not body.get("revoked"):
        reason = str(body.get("error", "unknown"))[:64]
        raise IntegrationError(
            "revoke_failed", f"Slack did not revoke the token ({reason})."
        )


def _bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _bearer_v2022(api_key: str) -> dict[str, str]:
    """Notion requires a Notion-Version header in addition to bearer."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
    }


def _slack_identity(body: dict[str, Any] | None) -> dict[str, Any]:
    """Parse Slack's auth.test response — serves as both parse_probe and
    parse_sync, since Slack returns the same shape at both call sites.

    Slack signals auth failure with HTTP 200 + ok=false, so this raises
    IntegrationError rather than returning: a bare Exception would escape
    the factory's connect()/sync() handlers as a 500. Slack's own error
    string goes in the human-readable message only — the machine-readable
    code stays in our closed vocabulary (invalid_key/probe_failed/...)
    rather than handing Slack ownership of our public API contract.
    """
    if not isinstance(body, dict) or not body.get("ok"):
        reason = (
            str(body.get("error", "unknown"))[:64]
            if isinstance(body, dict)
            else "unknown"
        )
        raise IntegrationError("invalid_key", f"Slack rejected the token ({reason}).")
    return {"team": body.get("team"), "user": body.get("user")}


def _api_key_header(name: str) -> Callable[[str], dict[str, str]]:
    def _h(api_key: str) -> dict[str, str]:
        return {name: api_key}

    return _h


# ── Project-class (deployment-wide) ──────────────────────────────────────


@register
class _UpstashProvider(
    make_provider(
        ProviderSpec(
            slug="upstash",
            upstream_revocation=_dashboard_only(
                "Upstash", "console.upstash.com → Account → API Keys"
            ),
            display_name="Upstash",
            category="Infrastructure",
            description="Redis & Vector databases — request count, memory usage.",
            docs_url="https://upstash.com/docs/devops/developer-api/intro",
            icon="upstash",
            probe_url="https://api.upstash.com/v2/redis/databases",
            auth_header=_bearer,
            parse_probe=lambda body: {"db_count": len(body or [])},
            parse_sync=lambda body: {
                "db_count": len(body or []),
                "databases": [
                    {"id": d.get("database_id"), "name": d.get("database_name")}
                    for d in (body or [])[:10]
                ],
            },
            scopes=["redis:read"],
        )
    )
): ...


@register
class _CloudflareProvider(
    make_provider(
        ProviderSpec(
            slug="cloudflare",
            upstream_revocation=_dashboard_only(
                "Cloudflare", "dash.cloudflare.com → My Profile → API Tokens"
            ),
            display_name="Cloudflare",
            category="Infrastructure",
            description="DNS, Workers, analytics.",
            docs_url="https://developers.cloudflare.com/api/",
            icon="cloudflare",
            probe_url="https://api.cloudflare.com/client/v4/user/tokens/verify",
            auth_header=_bearer,
            parse_probe=lambda body: {
                "token_status": (body or {}).get("result", {}).get("status"),
            },
            parse_sync=lambda body: {
                "token_status": (body or {}).get("result", {}).get("status"),
            },
            scopes=["account:read"],
        )
    )
): ...


@register
class _StripeProvider(
    make_provider(
        ProviderSpec(
            slug="stripe",
            upstream_revocation=_dashboard_only(
                "Stripe", "dashboard.stripe.com → Developers → API keys"
            ),
            display_name="Stripe",
            category="Infrastructure",
            description="Payments, customers, balance — restricted key recommended.",
            docs_url="https://docs.stripe.com/api",
            icon="stripe",
            probe_url="https://api.stripe.com/v1/balance",
            auth_header=_bearer,
            parse_probe=lambda body: {
                "available_count": len((body or {}).get("available", []))
            },
            parse_sync=lambda body: {
                "available_amounts": [
                    {"currency": a.get("currency"), "amount": a.get("amount")}
                    for a in (body or {}).get("available", [])
                ]
            },
            scopes=["balance:read"],
        )
    )
): ...


@register
class _SentryProvider(
    make_provider(
        ProviderSpec(
            slug="sentry",
            upstream_revocation=_dashboard_only(
                "Sentry", "sentry.io → Settings → Auth Tokens"
            ),
            display_name="Sentry",
            category="Infrastructure",
            description="Errors, releases, performance.",
            docs_url="https://docs.sentry.io/api/",
            icon="sentry",
            probe_url="https://sentry.io/api/0/organizations/",
            auth_header=_bearer,
            parse_probe=lambda body: {"org_count": len(body or [])},
            parse_sync=lambda body: {
                "orgs": [
                    {"slug": o.get("slug"), "name": o.get("name")}
                    for o in (body or [])[:5]
                ]
            },
            scopes=["org:read"],
        )
    )
): ...


@register
class _AnthropicProvider(
    make_provider(
        ProviderSpec(
            slug="anthropic",
            upstream_revocation=_dashboard_only(
                "Anthropic", "console.anthropic.com → Settings → API keys"
            ),
            display_name="Anthropic",
            category="Infrastructure",
            description="API usage, rate limits, billing.",
            docs_url="https://docs.anthropic.com/en/api/admin-api",
            icon="anthropic",
            # Admin API endpoints require the admin key class.
            probe_url="https://api.anthropic.com/v1/organizations/me",
            auth_header=lambda key: {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            parse_probe=lambda body: {"org_id": (body or {}).get("id")},
            parse_sync=lambda body: {"org_id": (body or {}).get("id")},
            scopes=["org:read"],
        )
    )
): ...


@register
class _OpenAIProvider(
    make_provider(
        ProviderSpec(
            slug="openai",
            upstream_revocation=_dashboard_only(
                "OpenAI", "platform.openai.com → API keys"
            ),
            display_name="OpenAI",
            category="Infrastructure",
            description="Models list, usage, organization info.",
            docs_url="https://platform.openai.com/docs/api-reference",
            icon="openai",
            probe_url="https://api.openai.com/v1/models",
            auth_header=_bearer,
            parse_probe=lambda body: {"model_count": len((body or {}).get("data", []))},
            parse_sync=lambda body: {
                "model_count": len((body or {}).get("data", [])),
                "models": [m.get("id") for m in (body or {}).get("data", [])[:8]],
            },
            scopes=["models:read"],
        )
    )
): ...


# ── Personal-class (per-user) ────────────────────────────────────────────


@register
class _NotionProvider(
    make_provider(
        ProviderSpec(
            slug="notion",
            upstream_revocation=_dashboard_only("Notion", "notion.so/my-integrations"),
            display_name="Notion",
            category="Productivity",
            description="Pages and databases via internal integration token.",
            docs_url="https://developers.notion.com/reference",
            icon="notion",
            probe_url="https://api.notion.com/v1/users/me",
            auth_header=_bearer_v2022,
            parse_probe=lambda body: {
                "name": (body or {}).get("name"),
                "type": (body or {}).get("type"),
            },
            parse_sync=lambda body: {
                "name": (body or {}).get("name"),
                "bot_id": (body or {}).get("bot", {}).get("workspace_name"),
            },
            scopes=["pages:read", "databases:read"],
            per_user=True,
        )
    )
): ...


@register
class _SlackProvider(
    make_provider(
        ProviderSpec(
            slug="slack",
            upstream_revocation=revokes_via(
                "POST https://slack.com/api/auth.revoke — Slack invalidates "
                "the token, ending Arshad.AI's access to your workspace."
            ),
            revoke_key=_slack_auth_revoke,
            display_name="Slack",
            category="Communication",
            description="Channels, messages, DMs (user token from your Slack app).",
            docs_url="https://api.slack.com/web",
            icon="slack",
            probe_url="https://slack.com/api/auth.test",
            auth_header=_bearer,
            parse_probe=_slack_identity,
            parse_sync=_slack_identity,
            scopes=["channels:read"],
            per_user=True,
        )
    )
): ...


@register
class _TodoistProvider(
    make_provider(
        ProviderSpec(
            slug="todoist",
            upstream_revocation=_dashboard_only(
                "Todoist", "Todoist → Settings → Integrations → Developer"
            ),
            display_name="Todoist",
            category="Productivity",
            description="Tasks, projects, comments via REST v2.",
            docs_url="https://developer.todoist.com/rest/v2/",
            icon="todoist",
            probe_url="https://api.todoist.com/rest/v2/projects",
            auth_header=_bearer,
            parse_probe=lambda body: {"project_count": len(body or [])},
            parse_sync=lambda body: {
                "project_count": len(body or []),
                "projects": [
                    {"id": p.get("id"), "name": p.get("name")}
                    for p in (body or [])[:10]
                ],
            },
            scopes=["data:read"],
            per_user=True,
        )
    )
): ...


@register
class _NewsApiProvider(
    make_provider(
        ProviderSpec(
            slug="news_api",
            upstream_revocation=_dashboard_only("News API", "newsapi.org/account"),
            display_name="News API",
            category="Lifestyle",
            description="Headlines and articles by topic.",
            docs_url="https://newsapi.org/docs",
            icon="news",
            probe_url="https://newsapi.org/v2/top-headlines?country=us&pageSize=1",
            auth_header=_api_key_header("X-Api-Key"),
            parse_probe=lambda body: {"status": (body or {}).get("status")},
            parse_sync=lambda body: {"status": (body or {}).get("status")},
            scopes=["headlines:read"],
            per_user=True,
        )
    )
): ...


# OpenWeatherMap and Linear use query-param auth / POST GraphQL respectively;
# they don't fit the simple GET-with-header factory. Add as custom providers
# in personal/openweathermap.py and personal/linear.py in a follow-up commit.
