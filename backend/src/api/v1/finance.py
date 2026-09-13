"""HTTP surface for brokerage holdings: GET /api/v1/finance/holdings.

This module owns HTTP concerns only -- auth, rate limit, the response
envelope and the status code. The read model itself (broker catalogue,
config parsing, row projection) lives in src/services/finance/; see that
package's __init__ for its layering. Nothing below computes a figure.

Always returns HTTP 200 -- the same documented deviation as
/api/v1/shopify/dashboard and /api/v1/whoop/dashboard (see
.claude/rules/api.md): this endpoint backs an always-visible page tile, and
frontend/src/hooks/useFetch.ts treats ANY 401 response as an Arshad.AI
session expiry and clears the JWT. A brokerage token expiring must never
trigger that app-wide logout.

Why this is not a thin filter over GET /api/v1/integrations: that route's
config/`extra` passthrough (see src/integrations/personal/_oauth_base.py)
is unbounded, shaped per-provider, and carries OAuth scope/expiry metadata
this feature has no business exposing. This route is the narrow, typed,
server-computed projection over exactly the two brokerage slugs.

Scoping: state.find_integration() matches user_id only -- it deliberately
does not also match the NULL-owner, project-scoped rows that
src/integrations/routers.py serves elsewhere. Personal portfolio data must
never be reachable by way of a NULL-owner row. No project-scoped brokerage
integration exists today; if one is ever seeded, /integrations would show
it connected while this endpoint would not -- that divergence is
intentional.

No cache: two indexed reads (uq_integrations_user_slug) against a tiny
result set are cheaper than a Redis round trip, and a cache would risk
serving stale data immediately after the user hits "Sync now" on the
frontend (which calls the existing POST /api/v1/integrations/{slug}/sync).
No pagination either -- both providers' sync() methods already cap
holdings at 10 rows; this route does not add a second, redundant
limit/offset contract on top of an already fixed-size projection.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.auth.dependencies import get_current_user
from src.middleware.rate_limit import enforce_rate_limit
from src.models.database import get_db
from src.models.user import User
from src.services.finance import holdings as holdings_service
from src.services.integrations import state

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])

_RATE_LIMIT = 30
_RATE_WINDOW_SECONDS = 60


async def _check_rate_limit(user_id: str) -> None:
    """Kept as a module-level function so tests can substitute the limiter."""
    await enforce_rate_limit(
        bucket="finance",
        identity=user_id,
        limit=_RATE_LIMIT,
        window_seconds=_RATE_WINDOW_SECONDS,
        message=f"Too many requests. Retry after {_RATE_WINDOW_SECONDS} seconds.",
    )


@router.get("/holdings")
async def get_holdings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Real Upstox / Zerodha Kite holdings for the current user.

    Always HTTP 200 -- see module docstring. `brokers` is empty when
    neither broker is connected; `connected` is a convenience flag derived
    from that.

    `state.find_integration` is read off the module here, at call time,
    rather than from-imported at module scope, so that patching it
    substitutes the DB for the whole request.
    """
    await _check_rate_limit(str(current_user.id))

    payload = await holdings_service.collect_broker_holdings(
        str(current_user.id), db, find_integration=state.find_integration
    )
    return JSONResponse(
        status_code=200, content={"data": payload.model_dump(mode="json")}
    )
