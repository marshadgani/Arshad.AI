"""HS256 JWTs signed with SECRET_KEY.

Tokens carry a single claim — the user's UUID — plus standard ``exp`` and ``iat``.
24-hour expiry by default (override via JWT_EXPIRY_HOURS).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

_ALGORITHM = "HS256"


def _secret() -> str:
    secret = os.getenv("SECRET_KEY")
    if not secret or secret == "change-me":
        raise RuntimeError("SECRET_KEY is unset or still 'change-me'")
    return secret


def _expiry_hours() -> int:
    return int(os.getenv("JWT_EXPIRY_HOURS", "24"))


def encode_jwt(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_expiry_hours())).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_jwt(token: str) -> uuid.UUID:
    """Returns the user_id from a valid token. Raises InvalidTokenError on failure."""
    payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    sub = payload.get("sub")
    if not sub:
        raise InvalidTokenError("missing sub claim")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise InvalidTokenError("sub claim is not a UUID") from exc


__all__ = ["encode_jwt", "decode_jwt", "ExpiredSignatureError", "InvalidTokenError"]
