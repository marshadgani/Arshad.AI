"""Unit tests for services/finance/brokers.py.

display_name_for's registry-miss fallback is exercised nowhere else: every
endpoint/service test uses the two real, registered slugs (upstox,
zerodha_kite), so the branch that keeps the always-200 contract intact when
BROKER_SLUGS and INTEGRATION_REGISTRY drift apart was previously untested.
"""

from __future__ import annotations

from src.services.finance import brokers


class TestDisplayNameFor:
    def test_registered_slug_returns_provider_display_name(self):
        assert brokers.display_name_for("upstox") != "upstox"

    def test_unregistered_slug_falls_back_to_the_slug_itself(self):
        # No provider will ever register under this slug -- simulates
        # BROKER_SLUGS listing a slug the registry doesn't know about.
        assert brokers.display_name_for("not_a_real_broker") == "not_a_real_broker"

    def test_broker_slugs_order_is_upstox_then_zerodha(self):
        # The wire contract (and BrokerageHoldings.test.tsx's ordering
        # assertions) depend on this exact, stable order.
        assert brokers.BROKER_SLUGS == ("upstox", "zerodha_kite")

    def test_currency_is_inr(self):
        assert brokers.CURRENCY == "INR"
