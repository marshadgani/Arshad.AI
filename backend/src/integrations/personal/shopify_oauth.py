"""Pure OAuth rules for the Shopify provider: shop-domain normalisation /
validation, and callback authenticity verification.

Split out of shopify.py so that:

  * the security-critical checks (HMAC signature, shop cross-check,
    timestamp skew) are exercisable without constructing a provider, a DB
    session, an HTTP client, or Redis;
  * shopify.py is left holding nothing but the OAuth lifecycle
    (connect -> complete_callback -> sync -> status).

Everything here is pure: no I/O, no DB, no HTTP, no environment reads. The
client secret is passed in by the caller rather than resolved from the
environment, so this module never becomes a second place that knows how
provider credentials are configured.

Error codes and messages are byte-for-byte what shopify.py raised inline
before the extraction — they are part of the OAuth callback's redirect
contract (integrations/routers.py forwards exc.code to the frontend as
?error=<code>), not incidental strings.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from typing import Any

from ..base import IntegrationError

# Shopify store domains: 1-60 chars, lowercase alphanumeric + internal
# hyphens, always under .myshopify.com. Custom/primary domains are
# deliberately rejected — only the canonical domain is a valid Admin API
# host, and accepting anything else would let a caller point token exchange
# at a host they control.
SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?\.myshopify\.com$")

TIMESTAMP_SKEW_SECONDS = 300  # 5 minutes

_SCHEME_RE = re.compile(r"^https?://")

# Excluded from the HMAC canonical string per Shopify's spec.
_UNSIGNED_PARAMS = ("hmac", "signature")


def normalise_shop(raw: str) -> str:
    """Strip whitespace, scheme, trailing slash and casing from user input."""
    value = raw.strip().lower()
    value = _SCHEME_RE.sub("", value)
    return value.rstrip("/")


def validate_shop_domain(raw: Any) -> str:
    """Normalise and validate a user-supplied store domain.

    Raises IntegrationError('invalid_shop_domain') rather than returning a
    sentinel: an unusable shop domain has no safe fallback, and the caller
    would only re-raise.
    """
    if not raw or not isinstance(raw, str):
        raise IntegrationError(
            "invalid_shop_domain", "A Shopify store domain is required."
        )
    shop = normalise_shop(raw)
    if not SHOP_DOMAIN_RE.match(shop):
        raise IntegrationError(
            "invalid_shop_domain",
            f"'{raw}' is not a valid *.myshopify.com domain.",
        )
    return shop


def verify_hmac(query_params: Mapping[str, str], client_secret: str) -> bool:
    """Shopify's canonical-string HMAC verification.

    Excludes both 'hmac' and 'signature'; remaining params are sorted by key
    and joined as k=v&k=v. Unknown extra params are included — Shopify signs
    everything it sends, so excluding unknowns would break legitimate
    callbacks. The comparison is constant-time.
    """
    provided = query_params.get("hmac", "")
    if not provided:
        return False
    pairs = {k: v for k, v in query_params.items() if k not in _UNSIGNED_PARAMS}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    computed = hmac.new(
        client_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, provided)


def verify_callback(
    *,
    query_params: Mapping[str, str],
    stored_shop: str,
    client_secret: str,
    now: float | None = None,
) -> None:
    """Assert that a Shopify OAuth callback is authentic, or raise.

    Check order is load-bearing and unchanged: signature first (nothing in
    the query string is trustworthy until the HMAC verifies), then the shop
    cross-check against the Redis-stored value, then replay-window skew.

    `now` is injectable purely so the skew branch is testable without
    freezing the clock globally; production callers omit it.
    """
    if not verify_hmac(query_params, client_secret):
        raise IntegrationError(
            "invalid_hmac", "Shopify callback signature verification failed."
        )

    if query_params.get("shop") != stored_shop:
        raise IntegrationError(
            "invalid_shop",
            "Callback shop domain does not match the connect request.",
        )

    raw_ts = query_params.get("timestamp")
    if not raw_ts:
        return
    try:
        skew = abs((now if now is not None else time.time()) - int(raw_ts))
    except ValueError:
        # An unparseable timestamp is treated as maximally stale rather than
        # as absent — a malformed value must not skip the replay window.
        skew = TIMESTAMP_SKEW_SECONDS + 1
    if skew > TIMESTAMP_SKEW_SECONDS:
        raise IntegrationError(
            "timestamp_skew", "Shopify callback timestamp is too old."
        )
