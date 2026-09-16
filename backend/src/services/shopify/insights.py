"""Assembly of the ShopifyInsights read model.

Mirrors dashboard.py's role: the one place that decides what a
/api/v1/shopify/insights payload looks like, keeping the router to HTTP
concerns only. Kept as its own module — not folded into dashboard.py — for
symmetry with the dashboard/insights split everywhere else in this feature,
and because it is the seam a future anomaly-detection pass (see
tasks/backlog.md) attaches to without touching the router or client.

No I/O: pure given a parsed ShopifyInsightsCore and a ShopContext.
"""

from __future__ import annotations

from typing import Any

from ...schemas.shopify import ShopifyInsights
from . import parsers, state


def build_insights(
    raw: dict[str, Any],
    ctx: state.ShopContext,
    bounds: parsers.WindowBounds,
    days: int,
) -> ShopifyInsights:
    core = parsers.parse_insights(raw, bounds, ctx.currency_code)
    return ShopifyInsights(
        days=days,
        currency_code=ctx.currency_code,
        timezone=ctx.timezone,
        start_date=bounds.local_dates[0],
        end_date=bounds.local_dates[-1],
        points=core.points,
        summary=core.summary,
        truncated=core.truncated,
        covered_through=core.covered_through,
        partial_failures=core.partial_failures,
    )
