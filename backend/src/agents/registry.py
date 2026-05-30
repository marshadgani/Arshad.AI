"""Central registry of every Phase E agent.

Populated by the ``@register`` class decorator on each Agent subclass.
The gateway, REST router, and (eventually) Phase B chat all consume
``AGENT_REGISTRY``, keyed by ``slug = f"{domain}_{name}"``.

Importing the per-domain sub-packages (in `routers.py`) triggers the
decorators at module load time.
"""

from __future__ import annotations

from typing import TypeVar

from .base import Agent

AGENT_REGISTRY: dict[str, Agent] = {}

T = TypeVar("T", bound=type[Agent])


def register(cls: T) -> T:
    instance = cls()
    if instance.slug in AGENT_REGISTRY:
        raise RuntimeError(f"Duplicate agent slug: {instance.slug}")
    AGENT_REGISTRY[instance.slug] = instance
    return cls


def get(domain: str, name: str) -> Agent | None:
    return AGENT_REGISTRY.get(f"{domain}_{name}")
