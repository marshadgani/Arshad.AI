"""POST /api/v1/agents/{domain}/{agent}/run + GET /api/v1/agents.

Auth-gated at the router level via Depends(get_current_user). The body
is a free-form dict that the gateway validates against the agent's
input_schema. Errors map to:

  - 404 unknown_agent              (agent slug not in registry)
  - 400 invalid_input              (Pydantic ValidationError)
  - 501 not_yet_implemented        (placeholder agent for Phase B/F)
  - 400 oauth_account_not_linked   (Phase D ProviderNotLinked)
  - 401 google_reauth_required / github_reauth_required
  - 502 provider_http_error / provider_unreachable
  - 400 anything else from AgentError / ToolError

Importing the per-domain sub-packages triggers the @register decorators
so AGENT_REGISTRY is populated before the first request arrives.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User
from ..services.gateway import GatewayError, dispatch, list_agents
from ..tools.base import ProviderNotLinked, ProviderReauthRequired, ToolError

# Import sub-packages so @register runs at module load.
from . import (  # noqa: F401,E402
    ai_core,
    calendar,
    data_pipeline,
    email,
    github,
    infrastructure,
)
from .base import AgentError, AgentNotImplemented

router = APIRouter(
    prefix="/api/v1/agents",
    tags=["agents"],
    dependencies=[Depends(get_current_user)],
)


def _envelope(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )


@router.get("", summary="List registered agents")
async def list_endpoint() -> dict:
    agents = list_agents()
    return {"data": agents, "total": len(agents)}


@router.post("/{domain}/{agent}/run", summary="Execute an agent")
async def run_endpoint(
    domain: str,
    agent: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await dispatch(domain, agent, user=user, db=db, payload=payload)
    except GatewayError as exc:
        raise _envelope(exc.status, exc.code, exc.message)
    except AgentNotImplemented as exc:
        raise _envelope(status.HTTP_501_NOT_IMPLEMENTED, exc.code, exc.message)
    except ProviderReauthRequired as exc:
        raise _envelope(status.HTTP_401_UNAUTHORIZED, exc.code, exc.message)
    except ProviderNotLinked as exc:
        raise _envelope(status.HTTP_400_BAD_REQUEST, exc.code, exc.message)
    except (AgentError, ToolError) as exc:
        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if exc.code == "provider_http_error"
            else status.HTTP_400_BAD_REQUEST
        )
        raise _envelope(status_code, exc.code, exc.message)

    return result.model_dump(mode="json")
