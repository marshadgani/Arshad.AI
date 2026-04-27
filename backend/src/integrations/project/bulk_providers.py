"""Declarative API-key providers built via the spec factory.

Each block instantiates a provider class and registers it. Adding a new
provider = adding a ProviderSpec block.
"""

from __future__ import annotations

from ..registry import register
from ._factory import ProviderSpec, make_provider


def _bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _bearer_v2022(api_key: str) -> dict[str, str]:
    """Notion requires a Notion-Version header in addition to bearer."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
    }


def _slack_bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _api_key_header(name: str):
    def _h(api_key: str) -> dict[str, str]:
        return {name: api_key}

    return _h


# ── Project-class (deployment-wide) ──────────────────────────────────────


@register
class _UpstashProvider(
    make_provider(
        ProviderSpec(
            slug="upstash",
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
            display_name="Slack",
            category="Communication",
            description="Channels, messages, DMs (user token from your Slack app).",
            docs_url="https://api.slack.com/web",
            icon="slack",
            probe_url="https://slack.com/api/auth.test",
            auth_header=_slack_bearer,
            parse_probe=lambda body: (
                {"team": (body or {}).get("team"), "user": (body or {}).get("user")}
                if (body or {}).get("ok")
                else (_ for _ in ()).throw(
                    Exception((body or {}).get("error", "slack_auth_failed"))
                )
            ),
            parse_sync=lambda body: {
                "team": (body or {}).get("team"),
                "user": (body or {}).get("user"),
            },
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
