"""The brokerage catalogue: which slugs this feature covers, in what order,
how each is labelled, and what currency its figures are in.

Isolated into its own module so that INTEGRATION_REGISTRY -- the single
coupling from this feature into the wider integrations package -- has
exactly one import site. Adding a third broker is then a one-line change
here rather than an edit spread across the route and the assembler.
"""

from __future__ import annotations

from ...integrations.registry import INTEGRATION_REGISTRY

# Deterministic order -- brokers[] is always emitted upstox-then-zerodha_kite
# so the UI never reshuffles between loads and tests can index positionally.
BROKER_SLUGS: tuple[str, ...] = ("upstox", "zerodha_kite")

# Both registered providers are India-only by construction (see
# src/integrations/personal/upstox.py and zerodha_kite.py).
CURRENCY = "INR"


def display_name_for(slug: str) -> str:
    """The provider's human label, falling back to the slug itself.

    The fallback matters: a slug present in BROKER_SLUGS but absent from
    the registry must still render a card rather than raise -- this
    endpoint's contract is always-200.
    """
    provider = INTEGRATION_REGISTRY.get(slug)
    return provider.display_name if provider else slug
