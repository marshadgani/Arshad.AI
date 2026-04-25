"""FastAPI auth dependency.

``Depends(get_current_user)`` resolves the JWT bearer header to the User
row. 401 on missing header, malformed header, invalid/expired JWT, or
user no longer exists.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import get_db
from ..models.user import User
from .jwt import ExpiredSignatureError, InvalidTokenError, decode_jwt


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": code, "message": message, "details": {}}},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization:
        raise _unauthorized(
            "missing_authorization", "Authorization header is required."
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise _unauthorized(
            "malformed_authorization", "Authorization must be 'Bearer <token>'."
        )
    token = parts[1].strip()
    try:
        user_id = decode_jwt(token)
    except ExpiredSignatureError:
        raise _unauthorized("token_expired", "Bearer token has expired.")
    except InvalidTokenError:
        raise _unauthorized("invalid_token", "Bearer token is invalid.")

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise _unauthorized("user_not_found", "Authenticated user no longer exists.")
    return user
