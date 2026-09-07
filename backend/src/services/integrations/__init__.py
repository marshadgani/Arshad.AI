"""Shared, slug-parameterised integration lifecycle helpers.

Extracted from src/services/whoop/state.py so a second live-data provider
(Shopify) does not have to re-derive the same subtle status-transition
rules. See state.py for the extraction contract: whoop/state.py becomes a
thin binding over this module, and its behaviour must not change.
"""
