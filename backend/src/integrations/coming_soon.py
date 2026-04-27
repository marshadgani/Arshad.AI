"""Coming-soon provider stubs.

These show up in the Integrations UI so you can see Arshad.AI's full roadmap,
but connecting raises a not_yet_implemented error. Each one declares why it's
not shipped yet (usually: requires a generic OAuth callback endpoint that
needs Phase H work, or has restricted API access).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration import Integration
from ..models.user import User
from .base import (
    ConnectResult,
    IntegrationError,
    IntegrationProvider,
    StatusReport,
    SyncResult,
)
from .registry import register


def _make_coming_soon(
    *,
    slug: str,
    display_name: str,
    category: str,
    description: str,
    docs_url: str | None,
    icon: str,
    reason: str,
) -> type[IntegrationProvider]:
    class _Stub(IntegrationProvider):
        async def connect(
            self, *, user: User | None, db: AsyncSession, payload: dict[str, Any]
        ) -> ConnectResult:
            raise IntegrationError(
                "not_yet_implemented",
                f"{display_name} connector is on the roadmap. {reason}",
            )

        async def sync(
            self, *, integration: Integration, db: AsyncSession
        ) -> SyncResult:
            raise IntegrationError(
                "not_yet_implemented", f"{display_name} sync not yet built."
            )

        async def status(
            self, *, integration: Integration, db: AsyncSession
        ) -> StatusReport:
            return StatusReport(
                status="coming_soon",  # type: ignore[arg-type]
                last_synced_at=None,
                last_error=None,
                extra={"reason": reason},
            )

    _Stub.slug = slug
    _Stub.kind = "personal_oauth"  # cosmetic — never actually used since coming_soon
    _Stub.display_name = display_name
    _Stub.category = category
    _Stub.description = description
    _Stub.docs_url = docs_url
    _Stub.icon = icon
    _Stub.coming_soon = True
    _Stub.coming_soon_reason = reason
    _Stub.__name__ = f"{slug.replace('_', '').title()}Stub"
    return _Stub


_OAUTH_REASON = (
    "Requires the generic OAuth callback endpoint shipping in Phase H. "
    "Backend connector code is ready; awaiting auth flow infrastructure."
)


# ── OAuth-only providers (need /integrations/oauth/{provider}/callback) ──
# Spotify, Fitbit, Oura, Strava, Coinbase, Discord, Reddit, Linear are now
# REAL providers in personal/oauth_providers.py — Phase H promoted them.


# ── Explicit "not available — no public API" cards ──────────────────────

_NO_API = "No public consumer API exists for this service. Cannot be integrated."


@register
class _WhatsAppStub(
    _make_coming_soon(
        slug="whatsapp",
        display_name="WhatsApp (personal)",
        category="Communication",
        description="WhatsApp Business API exists, but personal chats are not accessible to apps.",
        docs_url=None,
        icon="whatsapp",
        reason=_NO_API
        + " WhatsApp Business API is for businesses messaging customers.",
    )
):
    pass


@register
class _InstagramStub(
    _make_coming_soon(
        slug="instagram",
        display_name="Instagram (personal)",
        category="Lifestyle",
        description="Personal feed access deprecated. Only Business/Creator account data available.",
        docs_url=None,
        icon="instagram",
        reason=_NO_API
        + " Meta deprecated the Basic Display API in 2024. Only Business accounts via Graph API.",
    )
):
    pass


@register
class _FacebookStub(
    _make_coming_soon(
        slug="facebook",
        display_name="Facebook (personal)",
        category="Lifestyle",
        description="Graph API requires Business app verification. Personal feed scraping is forbidden.",
        docs_url=None,
        icon="facebook",
        reason=_NO_API + " Personal feed access is not granted to third-party apps.",
    )
):
    pass


@register
class _CredStub(
    _make_coming_soon(
        slug="cred",
        display_name="CRED (India)",
        category="Finance",
        description="Indian credit-card management — app-only.",
        docs_url=None,
        icon="cred",
        reason=_NO_API,
    )
):
    pass


@register
class _IndMoneyStub(
    _make_coming_soon(
        slug="indmoney",
        display_name="IndMoney (India)",
        category="Finance",
        description="Indian investment platform — app-only.",
        docs_url=None,
        icon="indmoney",
        reason=_NO_API,
    )
):
    pass


@register
class _AppleHealthStub(
    _make_coming_soon(
        slug="apple_health",
        display_name="Apple Health",
        category="Health",
        description="HealthKit is iOS-only. Web integration requires a native iOS companion app.",
        docs_url="https://developer.apple.com/documentation/healthkit",
        icon="apple-health",
        reason="No web API. Workaround: iOS Shortcuts → POST to Arshad.AI webhook (Phase J+).",
    )
):
    pass


@register
class _IMessageStub(
    _make_coming_soon(
        slug="imessage",
        display_name="iMessage",
        category="Communication",
        description="Apple-only. No public API.",
        docs_url=None,
        icon="imessage",
        reason=_NO_API,
    )
):
    pass
