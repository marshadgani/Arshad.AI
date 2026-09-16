"""Cross-layer utilities with zero project imports.

Modules here MUST NOT import from backend.src.* — that is what makes them
safely importable from any layer (integrations, services, agents, api)
without risking an import cycle. See utils/errors.py's module docstring.
"""
