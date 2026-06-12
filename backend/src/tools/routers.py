"""POST /api/v1/tools/{tool-name} — generic dispatcher.

The router is auth-gated at the router level via Depends(get_current_user).
It looks up the tool in TOOL_REGISTRY, validates the JSON body against
the tool's input_schema, executes, and returns the output_schema model.

Importing the calendar / gmail / github sub-packages registers all 12
tools at import time (each module ends in ``@register class ...(Tool)``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User

# Import sub-packages so their @register decorators run at module load time.
from . import calendar, github, gmail, obsidian  # noqa: F401,E402
from .base import ProviderNotLinked, ProviderReauthRequired, ToolError
from .registry import TOOL_REGISTRY, get_tool

router = APIRouter(
    prefix="/api/v1/tools",
    tags=["tools"],
    dependencies=[Depends(get_current_user)],
)


def _envelope(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )


@router.get("", summary="List registered tools")
async def list_tools() -> dict:
    return {
        "data": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema.model_json_schema(),
            }
            for tool in TOOL_REGISTRY.values()
        ],
        "total": len(TOOL_REGISTRY),
    }


@router.post("/{tool_name}", summary="Execute a tool")
async def execute_tool(
    tool_name: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tool = get_tool(tool_name)
    if tool is None:
        raise _envelope(
            status.HTTP_404_NOT_FOUND,
            "unknown_tool",
            f"No tool registered as '{tool_name}'.",
        )
    try:
        validated = tool.input_schema.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "invalid_input",
                    "message": f"Input failed validation for {tool_name}.",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    try:
        result = await tool(user=user, db=db, payload=validated)
    except ProviderReauthRequired as exc:
        raise _envelope(status.HTTP_401_UNAUTHORIZED, exc.code, exc.message)
    except ProviderNotLinked as exc:
        raise _envelope(status.HTTP_400_BAD_REQUEST, exc.code, exc.message)
    except ToolError as exc:
        # Provider 4xx/5xx that the client wrapper turned into ToolError. Map
        # provider_http_error -> 502, anything else -> 400.
        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if exc.code == "provider_http_error"
            else status.HTTP_400_BAD_REQUEST
        )
        raise _envelope(status_code, exc.code, exc.message)

    return result.model_dump(mode="json")
