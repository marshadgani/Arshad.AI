"""Encrypted-envelope codec for a cached Apple Health snapshot.

The single owner of the at-rest *format*: prefix, AES-GCM ciphertext, and
base64 transport encoding. It knows nothing about Redis, keys, TTLs, HTTP,
or the database — give it a snapshot and it returns an opaque string;
give it a string and it returns a snapshot or None.

Splitting this out of the former flat services/apple_health.py means the
storage layer (snapshot_store.py) can change where a snapshot lives
without touching how it is sealed, and this file can be exercised with no
Redis at all.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ...auth.crypto import TokenDecryptError, decrypt, encrypt

if TYPE_CHECKING:
    from ...schemas.apple_health import AppleHealthSnapshot

_log = logging.getLogger(__name__)

# Written ahead of the base64 payload so a reader can tell apart a genuine
# v1 encrypted snapshot from (a) a pre-encryption cleartext value left over
# from a rolling deploy, or (b) ciphertext written under a different format
# in the future. Both collapse to "cache miss" on read rather than an
# undiagnosable decrypt failure.
SNAPSHOT_ENVELOPE_PREFIX = "AH1:"


def encode_snapshot(snapshot: "AppleHealthSnapshot") -> str:
    """AES-GCM encrypt a snapshot for storage.

    The shared Redis singleton uses decode_responses=True (middleware/
    cache.py), so raw AES-GCM bytes must be base64-encoded to an ASCII
    string before the caller's `redis_client.set`. Biometric values never
    touch Redis (or any other at-rest store) in cleartext.

    Raises RuntimeError when OAUTH_ENCRYPTION_KEY is unset or malformed
    (propagated from src.auth.crypto._load_key) — deliberately not caught
    here; the caller decides the HTTP consequence.
    """
    ciphertext = encrypt(snapshot.model_dump_json())
    return SNAPSHOT_ENVELOPE_PREFIX + base64.b64encode(ciphertext).decode("ascii")


def decode_snapshot(raw: str) -> "AppleHealthSnapshot | None":
    """Decrypt a stored snapshot, or return None for any unusable value.

    Every failure mode — missing/rotated-key ciphertext, corruption, a
    legacy cleartext value from before this format existed, or a payload
    that no longer matches AppleHealthSnapshot's schema — collapses to
    None so the caller has exactly one branch: a real snapshot, or a cache
    miss. Never raises.
    """
    from ...schemas.apple_health import AppleHealthSnapshot

    if not raw.startswith(SNAPSHOT_ENVELOPE_PREFIX):
        return None
    try:
        ciphertext = base64.b64decode(raw[len(SNAPSHOT_ENVELOPE_PREFIX) :])
        plaintext = decrypt(ciphertext)
        return AppleHealthSnapshot.model_validate_json(plaintext)
    except (TokenDecryptError, ValueError, RuntimeError, ValidationError) as exc:
        _log.warning(
            "apple_health.decode_snapshot: unreadable cached snapshot (%s) — "
            "treating as cache miss",
            type(exc).__name__,
        )
        return None
