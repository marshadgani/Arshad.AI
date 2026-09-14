"""Pure token-shape rules for the Plaid provider.

Split out of plaid.py for the same reason shopify_oauth.py was split out of
shopify.py: the checks that decide whether a user-supplied credential is
acceptable are exercisable without constructing a provider, a DB session, an
HTTP client, or an environment.

Everything here is pure: no I/O, no DB, no HTTP, no environment reads. The
deployment's configured Plaid environment is passed in by the caller rather
than read from os.environ, so this module never becomes a second place that
knows how the backend is configured — plaid_client.py owns that.

Error codes and messages are byte-for-byte what plaid.py raised inline
before the extraction; `code` is part of the /connect error contract the
frontend switches on, not an incidental string.
"""

from __future__ import annotations

from ..base import IntegrationError

# A real Plaid access_token is ~70 chars ("access-<env>-" + a UUID). The cap
# is deliberately loose, but it exists: without it /connect accepts an
# arbitrarily large body, AES-GCM-encrypts it and writes it to a BYTEA column
# forever. A bound at the trust boundary is cheaper than an unbounded write.
MAX_ACCESS_TOKEN_CHARS = 512

ACCESS_TOKEN_PREFIXES = (
    "access-sandbox-",
    "access-development-",
    "access-production-",
)


def validate_access_token(key: str, *, configured_env: str) -> str:
    """Validate a directly-pasted Plaid access_token's shape.

    `key` is expected already stripped and non-empty (require_api_key's
    contract). Checks length, the documented `access-<env>-...` prefix, and that the
    env segment matches `configured_env` — a mismatched env is guaranteed to
    fail every subsequent call, since the API base URL is derived from that
    same env. Never logs or includes any slice of `key` in the raised error
    message.
    """
    if len(key) > MAX_ACCESS_TOKEN_CHARS:
        raise IntegrationError(
            "invalid_access_token_format",
            f"A Plaid access_token is at most {MAX_ACCESS_TOKEN_CHARS} "
            "characters. Check that you pasted only the token.",
        )

    prefix = next((p for p in ACCESS_TOKEN_PREFIXES if key.startswith(p)), None)
    if prefix is None:
        raise IntegrationError(
            "invalid_access_token_format",
            "A Plaid access_token must start with 'access-sandbox-', "
            "'access-development-', or 'access-production-'. If you pasted "
            "a public_token (public-...), send it as {public_token} instead.",
        )

    env = prefix.removeprefix("access-").removesuffix("-")
    if env != configured_env:
        raise IntegrationError(
            "plaid_env_mismatch",
            f"This access_token is for the '{env}' environment, but this "
            f"backend is configured for PLAID_ENV='{configured_env}'.",
        )

    remainder = key[len(prefix) :]
    if not remainder or any(
        c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in remainder
    ):
        raise IntegrationError(
            "invalid_access_token_format",
            "A Plaid access_token must not contain whitespace or control "
            "characters after its environment prefix.",
        )

    return key
