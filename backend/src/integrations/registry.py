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
    if instance.sync_dag_id is not None:
        clash = next(
            (
                p
                for p in INTEGRATION_REGISTRY.values()
                if p.sync_dag_id == instance.sync_dag_id
            ),
            None,
        )
        if clash is not None:
            raise RuntimeError(
                f"Duplicate sync_dag_id {instance.sync_dag_id!r}: claimed by both "
                f"'{clash.slug}' and '{instance.slug}'. sync_dag_id must be unique "
                "so registry.slug_for_dag_id() has exactly one answer."
            )
    INTEGRATION_REGISTRY[instance.slug] = instance
    return cls


def all_providers() -> list[IntegrationProvider]:
    return list(INTEGRATION_REGISTRY.values())


def get_provider(slug: str) -> IntegrationProvider | None:
    return INTEGRATION_REGISTRY.get(slug)


def slug_for_dag_id(dag_id: str) -> str | None:
    """Reverse lookup derived from IntegrationProvider.sync_dag_id — the
    single source of truth for the slug<->dag_id relationship (FEAT-144).
    Returns None for DAGs with no owning provider (e.g.
    analytics_processor), which callers treat as a no-op rather than an
    error."""
    for provider in INTEGRATION_REGISTRY.values():
        if provider.sync_dag_id == dag_id:
            return provider.slug
    return None
