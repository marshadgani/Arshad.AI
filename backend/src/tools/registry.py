"""Central registry of every Phase D tool.

Populated lazily — concrete Tool subclasses register themselves on import
via ``register(cls)``. The REST router and Phase B chat both consume this
map, keyed by ``Tool.name`` (the URL slug).

To add a new tool: import its module in ``__init__.py`` for the package
that owns it (e.g. ``tools/calendar/__init__.py``); the module imports
this file's ``register`` and uses it as a class decorator.
"""

from __future__ import annotations

from typing import TypeVar

from .base import Tool

TOOL_REGISTRY: dict[str, Tool] = {}

T = TypeVar("T", bound=type[Tool])


def register(cls: T) -> T:
    """Class decorator: instantiate and register a Tool subclass."""
    instance = cls()
    if instance.name in TOOL_REGISTRY:
        raise RuntimeError(f"Duplicate tool name in registry: {instance.name}")
    TOOL_REGISTRY[instance.name] = instance
    return cls


def get_tool(name: str) -> Tool | None:
    return TOOL_REGISTRY.get(name)
