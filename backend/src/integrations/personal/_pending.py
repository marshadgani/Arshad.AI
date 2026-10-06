"""Redis-backed single-use pending records for the personal OAuth attach flow.

After the anonymous callback from the provider fires (step 2 of the attach
flow), we cannot complete the link immediately — the browser is unauthenticated
at that point. Instead we park the encrypted authorization code in a short-lived
pending record that only the initiating user can consume in step 3.

Responsibilities of this module (and nothing else):
- Key naming for pending records.
- Writing a pending record (store_attach_pending).
- Reading without consuming (peek_attach_pending) — so a wrong user cannot
  accidentally burn a record that belongs to someone else.
- Atomically consuming a record once (consume_attach_pending).
- Decrypting the encrypted code out of a pending record (decrypt_pending_code).
"""

from __future__ import annotations

import base64
import json
import logging
import secrets

from ...auth.crypto import decrypt, encrypt
from ...middleware.cache import get_redis

_log = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 300


def pending_key(pending_id: str) -> str:
    return f"attach_pending:{pending_id}"


def _as_text(raw: str | bytes) -> str:
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


async def store_attach_pending(
    *, user_id: str, slug: str, oauth_provider: str, code: str
) -> str:
    pending_id = secrets.token_urlsafe(32)
    record = {
        "user_id": user_id,
        "slug": slug,
        "oauth_provider": oauth_provider,
        "code_enc": base64.b64encode(encrypt(code)).decode("ascii"),
    }
    redis = await get_redis()
    await redis.set(pending_key(pending_id), json.dumps(record), ex=PENDING_TTL_SECONDS)
    return pending_id


async def peek_attach_pending(pending_id: str) -> dict[str, str] | None:
    """Read (without deleting) a pending record, so a wrong user cannot burn it."""
    redis = await get_redis()
    raw = await redis.get(pending_key(pending_id))
    if not raw:
        return None
    try:
        record = json.loads(_as_text(raw))
    except json.JSONDecodeError:
        _log.error(
            "attach pending record is not valid JSON (id suffix %s)", pending_id[-6:]
        )
        return None
    needed = {"user_id", "slug", "oauth_provider", "code_enc"}
    if not isinstance(record, dict) or not needed.issubset(record):
        _log.error("attach pending record is malformed (id suffix %s)", pending_id[-6:])
        return None
    return {k: str(record[k]) for k in needed}


async def consume_attach_pending(pending_id: str) -> bool:
    """Single-use delete. True only for the caller that actually removed it."""
    redis = await get_redis()
    return bool(await redis.delete(pending_key(pending_id)))


def decrypt_pending_code(code_enc: str) -> str:
    return decrypt(base64.b64decode(code_enc))
