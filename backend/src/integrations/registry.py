"""INTEGRATION_REGISTRY[slug] = IntegrationProvider instance.

Populated at import time by @register decorators in personal/* and project/*.
"""

from __future__ import annotations

from typing import TypeVar

from .base import IntegrationProvider

INTEGRATION_REGISTRY: dict[str, IntegrationProvider] = {}

T = TypeVar("T", bound=IntegrationProvider)


def _require_revocation_declaration(instance: IntegrationProvider) -> None:
    """Refuse to register a provider that hasn't said what disconnect()
    does with the third party.

    This is the guard for a bug that has already happened once: a
    `_revoke_upstream()` hook was added to the base class with a no-op
    default, no provider ever overrode it, and the disconnect dialog went
    on promising every user that their credentials were "revoked with the
    provider". Nothing failed — which is precisely why it survived.

    Failing at import time (i.e. at app startup, and in any test that
    imports the registry) makes the omission impossible to ship: adding a
    provider now forces an explicit `revokes_via(...)` or
    `cannot_revoke(...)`, and whichever is chosen is the same value the
    UI renders. A wrong answer is still possible; a silent one is not.
    """
    declared = getattr(instance, "upstream_revocation", None)
    if declared is None:
        raise RuntimeError(
            f"{type(instance).__name__} (slug={instance.slug!r}) does not declare "
            "`upstream_revocation`. Every provider must state what disconnect() "
            "does with the third party, because the disconnect confirmation "
            "dialog shows it to the user verbatim. Set it to "
            "revokes_via('<the call disconnect() makes>') or "
            "cannot_revoke('<why not, and what the user must do instead>') "
            "— see integrations/base.py."
        )
    if declared.supported and not _has_revocation_mechanism(instance):
        raise RuntimeError(
            f"{type(instance).__name__} (slug={instance.slug!r}) declares "
            "upstream_revocation=revokes_via(...) but has no way to do it: it "
            "neither overrides _revoke_upstream() nor sets revoke_url. The "
            "declaration is what the disconnect dialog promises the user, so a "
            "claim with no implementation behind it is the exact false promise "
            "this check exists to prevent."
        )


def _has_revocation_mechanism(instance: IntegrationProvider) -> bool:
    """Whether `instance` can actually perform an upstream revocation.

    An override of `_revoke_upstream()` is necessary but not always
    sufficient. The two shared implementations —
    `OAuthIntegrationProvider`'s and the API-key factory's — are inherited
    by every provider built on them, but each returns early unless that
    provider also supplied the thing it needs (a `revoke_url`, a
    `revoke_key` callable). Both mark themselves with `requires_attr`
    naming that attribute, which is what tells "inherited a generic hook"
    apart from "actually configured it".
    """
    implementation = type(instance)._revoke_upstream
    if implementation is IntegrationProvider._revoke_upstream:
        return False
    required_attr = getattr(implementation, "requires_attr", None)
    if required_attr is None:
        return True
    return bool(getattr(instance, required_attr, None))


def register(cls: type[T]) -> type[T]:
    instance = cls()
    if instance.slug in INTEGRATION_REGISTRY:
        raise RuntimeError(
            f"Duplicate integration slug: {instance.slug} "
            f"(already registered as {type(INTEGRATION_REGISTRY[instance.slug]).__name__})"
        )
    _require_revocation_declaration(instance)
    INTEGRATION_REGISTRY[instance.slug] = instance
    return cls


def all_providers() -> list[IntegrationProvider]:
    return list(INTEGRATION_REGISTRY.values())


def get_provider(slug: str) -> IntegrationProvider | None:
    return INTEGRATION_REGISTRY.get(slug)
