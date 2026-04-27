"""INTEGRATION_REGISTRY[slug] = IntegrationProvider instance.

Populated at import time by @register decorators in personal/* and project/*.
"""

from __future__ import annotations

from typing import TypeVar

from .base import IntegrationProvider

INTEGRATION_REGISTRY: dict[str, IntegrationProvider] = {}

T = TypeVar("T", bound=IntegrationProvider)


def register(cls: type[T]) -> type[T]:
    instance = cls()
    if instance.slug in INTEGRATION_REGISTRY:
        raise RuntimeError(
            f"Duplicate integration slug: {instance.slug} "
            f"(already registered as {type(INTEGRATION_REGISTRY[instance.slug]).__name__})"
        )
    INTEGRATION_REGISTRY[instance.slug] = instance
    return cls


def all_providers() -> list[IntegrationProvider]:
    return list(INTEGRATION_REGISTRY.values())


def get_provider(slug: str) -> IntegrationProvider | None:
    return INTEGRATION_REGISTRY.get(slug)
