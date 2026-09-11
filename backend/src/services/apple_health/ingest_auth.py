"""Ingest-token minting and verification.

The two halves of one scheme, kept together so they cannot drift:

    hash_ingest_token()  used by the provider at connect time to store a
                         digest instead of the cleartext token.
    authenticate()       used by the ingest endpoint to resolve an inbound
                         push back to its Integration.

`authenticate()` previously lived in the router as `_authenticate_ingest_
token`, which put a two-query database lookup and an authentication policy
inside the HTTP layer. The router now states the wire contract (a header
comes in, an Integration comes out or a 401 does) and this module owns the
rule.

The cleartext token is never stored, logged, or returned by anything here.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.errors import http_error
from ...models.integration import Integration, IntegrationIngestToken


def hash_ingest_token(token: str) -> str:
    """SHA-256 of an ingest bearer token.

    The cleartext token is shown to the user exactly once at connect time
    and never stored: only this digest is persisted, and inbound pushes are
    authenticated by re-hashing the presented token and matching the digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_value(authorization: str | None) -> str:
    """Extract the bearer credential, or raise 401.

    Split out so the "is this even a bearer header" check is not tangled
    with the database lookup that follows it.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise http_error(
            401, "missing_ingest_token", "Authorization: Bearer <token> is required."
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise http_error(401, "missing_ingest_token", "Ingest token was empty.")
    return token


async def authenticate(
    authorization: str | None, db: AsyncSession
) -> tuple[Integration, IntegrationIngestToken]:
    """Resolve the Integration an inbound push belongs to, or raise 401.

    The presented token is re-hashed and matched against the stored digest;
    the cleartext value is never stored or logged anywhere past this
    comparison. Every failure past the header check returns the same generic
    401 code so the response cannot be used to distinguish "no such token"
    from "revoked" from "integration disconnected".
    """
    token = _bearer_value(authorization)

    token_row = await db.scalar(
        select(IntegrationIngestToken).where(
            IntegrationIngestToken.token_hash == hash_ingest_token(token),
            IntegrationIngestToken.revoked_at.is_(None),
        )
    )
    if token_row is None:
        raise http_error(
            401, "invalid_ingest_token", "Ingest token is invalid or revoked."
        )

    integration = await db.scalar(
        select(Integration).where(Integration.id == token_row.integration_id)
    )
    if integration is None or integration.status == "disconnected":
        raise http_error(401, "invalid_ingest_token", "Integration is disconnected.")

    return integration, token_row
