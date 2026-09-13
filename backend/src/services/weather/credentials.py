"""The single seam between the weather read model and the stored
OpenWeatherMap API key, mirroring ``shopify/tokens.py`` and
``whoop/tokens.py``.

OpenWeatherMap is an ``personal_apikey`` integration: the key is a static
secret with no refresh flow, so this is a row read plus a decrypt. It is
still its own module rather than a private helper on the orchestrator so
that ``service.py`` — which owns the decision tree — does not also need to
know the credential table, the encryption primitive, or how "connected but
no key on file" is represented.

Returning ``None`` rather than raising keeps the caller's tree flat: a
missing key is one more ordinary branch of the tile's state machine, not an
exception the always-200 endpoint would have to catch.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.crypto import TokenDecryptError, decrypt
from ...models.integration import ApiKeyCredential, Integration

_log = logging.getLogger(__name__)


async def load_api_key(integration: Integration, db: AsyncSession) -> str | None:
    """The decrypted key for an active integration, or None if the row has
    no usable stored credential.

    ``TokenDecryptError`` (corrupted ciphertext, or a since-rotated
    ``OAUTH_ENCRYPTION_KEY`` — CLAUDE.md documents rotation as a known
    lockout cause) is caught here rather than left to escape. It is a
    permanent failure of the same shape as "no credential row", so it must
    reach the needs_reauth branch the codebase already reserves for
    `token_decryption_failed`; escaping, it would hit service.py's generic
    handler and render the `degraded` tile instead, which claims a
    transient fault that will self-heal when this one never can.
    """
    creds = await db.scalar(
        select(ApiKeyCredential).where(
            ApiKeyCredential.integration_id == integration.id
        )
    )
    if creds is None:
        # Anomalous — an active integration always stores a key, so this is
        # an incomplete disconnect or a failed connect, worth investigating.
        _log.warning(
            "Integration %s (slug=%s) is active but has no ApiKeyCredential "
            "row — treating as needs_reauth.",
            integration.id,
            integration.slug,
        )
        return None
    try:
        return decrypt(creds.encrypted_key)
    except TokenDecryptError:
        _log.error(
            "Integration %s (slug=%s) has an undecryptable stored API key "
            "(corrupted ciphertext or a rotated OAUTH_ENCRYPTION_KEY) — "
            "treating as needs_reauth so the user can reconnect.",
            integration.id,
            integration.slug,
            exc_info=True,
        )
        return None
