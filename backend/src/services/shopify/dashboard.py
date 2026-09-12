"""Assembly of the ShopifyDashboard read model.

The one place that decides what a /api/v1/shopify/dashboard payload looks
like, in either of its two shapes:

  shell_dashboard  — degraded: connected but with no live figures, used for
                     the needs-reauth and upstream-failure paths.
  build_dashboard  — live: parsed metrics plus the shop presentation
                     fields.

Split out of the router so that the router is left with HTTP concerns only
(auth, rate limit, cache, error policy, status code) and so the response is
constructed exactly once, rather than constructed by the parser and then
mutated field-by-field by the caller.

No I/O: both functions are pure given an Integration/ShopContext.
"""

from __future__ import annotations

from typing import Any

from ...models.integration import Integration
from ...schemas.shopify import ShopifyDashboard
from . import parsers, state


def shell_dashboard(
    integration: Integration, *, needs_reauth: bool
) -> ShopifyDashboard:
    """The connected-but-no-live-data response.

    Uses state.shop_presentation() rather than state.shop_context(): this
    shape is the fallback for an incomplete or unreachable record, so it
    must neither raise nor invent defaults for metadata we never obtained.
    """
    presentation = state.shop_presentation(integration)
    return ShopifyDashboard(
        connected=True,
        needs_reauth=needs_reauth,
        shop_name=presentation.shop_name,
        currency_code=presentation.currency_code,
        timezone=presentation.timezone,
    )


def build_dashboard(
    raw: dict[str, Any], ctx: state.ShopContext, *, as_of: str
) -> ShopifyDashboard:
    """Parsed metrics + shop presentation fields.

    model_copy rather than attribute assignment: the response is immutable
    once assembled, so there is no window in which a half-populated
    dashboard can escape to a caller.
    """
    return parsers.parse_dashboard(raw, ctx.currency_code).model_copy(
        update={
            "shop_name": ctx.shop_name,
            "timezone": ctx.timezone,
            "as_of": as_of,
        }
    )
