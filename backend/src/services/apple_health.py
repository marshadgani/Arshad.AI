"""Shared Apple Health ingest primitives.

These three definitions are used by both the provider that mints ingest
tokens (integrations/personal/apple_health.py) and the endpoints that
authenticate and serve pushes (api/v1/apple_health.py).

They previously lived in the provider module, which forced the API layer to
import *upward* into a concrete provider implementation — and to do it with
function-body imports to dodge the resulting cycle. Hosting them in a
neutral module both layers can depend on removes the cycle, so the deferred
imports are no longer load-bearing and the token-hashing scheme still has
exactly one definition.

Nothing here touches biometric values. The hash function is one-way, and
the cache key only names a Redis slot.
"""

from __future__ import annotations

import hashlib

# How long a pushed snapshot stays readable before the card reports itself
# stale. See the HUMAN REVIEW FLAG in integrations/personal/apple_health.py:
# a short-TTL cache is the closest available analogue to Whoop's
# fetch-live-per-request model for a push-only source that cannot be
# re-pulled between Shortcut runs.
CACHE_TTL_SECONDS = 6 * 60 * 60


def hash_ingest_token(token: str) -> str:
    """SHA-256 of an ingest bearer token.

    The cleartext token is shown to the user exactly once at connect time
    and never stored: only this digest is persisted, and inbound pushes are
    authenticated by re-hashing the presented token and matching the digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def snapshot_cache_key(integration_id: str) -> str:
    """Redis key holding the latest pushed snapshot for one integration."""
    return f"apple_health:snapshot:{integration_id}"
