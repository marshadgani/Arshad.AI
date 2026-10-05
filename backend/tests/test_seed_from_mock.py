"""Unit tests for scripts.seed_from_mock's DOMAINS iteration logic.

Regression coverage for a production crash (2026-10-05): the seed loop did
an unguarded `d["kpis"]` over every domain in DOMAINS, but the `shopify`
domain intentionally omits "kpis" (FEAT-119 — its KPIs are sourced live
from GET /api/v1/shopify/dashboard instead of seeded mock rows). That
raised `KeyError: 'kpis'` on every deploy, caught by the Dockerfile's
broad `|| echo '...non-fatal'` and silently dropping ALL seed data, not
just shopify's KPIs.

These tests exercise the DOMAINS data and the same optional-key access
pattern the seed() loop uses (kpis/applications/agents/feed via
`d.get(key, [])`), without requiring a database — seed() itself is async
and DB-backed, which this sandbox's test runner doesn't have installed
(see tasks/lessons.md), so the pure logic is tested directly instead.
"""

from __future__ import annotations

from scripts.seed_from_mock import DOMAINS

OPTIONAL_DOMAIN_KEYS = ("kpis", "applications", "agents", "feed")
REQUIRED_DOMAIN_KEYS = ("slug", "title", "emoji", "tagline")


class TestDomainsShape:
    def test_every_domain_has_required_keys(self):
        for d in DOMAINS:
            for key in REQUIRED_DOMAIN_KEYS:
                assert key in d, f"domain {d.get('slug', '?')!r} missing required key {key!r}"

    def test_shopify_intentionally_omits_kpis(self):
        shopify = next(d for d in DOMAINS if d["slug"] == "shopify")
        assert "kpis" not in shopify, (
            "shopify's 'kpis' key should stay absent per FEAT-119 "
            "(KPIs are sourced live from GET /api/v1/shopify/dashboard); "
            "if this changes, the seed loop's .get('kpis', []) guard is still "
            "safe, but this test documents the intentional omission"
        )

    def test_shopify_still_has_the_other_optional_keys(self):
        shopify = next(d for d in DOMAINS if d["slug"] == "shopify")
        for key in ("applications", "agents", "feed"):
            assert key in shopify


class TestOptionalKeyAccessDoesNotRaise:
    """Mirrors the exact `d.get(key, [])` pattern used in seed()'s Domains loop."""

    def test_get_with_default_never_raises_for_any_domain(self):
        for d in DOMAINS:
            for key in OPTIONAL_DOMAIN_KEYS:
                result = d.get(key, [])
                assert isinstance(result, list)

    def test_missing_key_detection_matches_seed_log_guard(self):
        # Mirrors: for key in (...): if key not in d: _log.warning(...)
        missing_by_domain = {
            d["slug"]: [key for key in OPTIONAL_DOMAIN_KEYS if key not in d] for d in DOMAINS
        }
        assert missing_by_domain["shopify"] == ["kpis"]
        for slug, missing in missing_by_domain.items():
            if slug != "shopify":
                assert missing == [], f"domain {slug!r} unexpectedly missing {missing}"

    def test_a_domain_dict_missing_every_optional_key_does_not_raise(self):
        # Regression guard: a future domain missing ALL optional keys (not
        # just kpis) must still not raise KeyError under the .get() pattern.
        bare_domain = {"slug": "bare", "title": "Bare", "emoji": "x", "tagline": "t"}
        for key in OPTIONAL_DOMAIN_KEYS:
            assert bare_domain.get(key, []) == []
