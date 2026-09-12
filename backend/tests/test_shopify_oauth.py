"""Tests for the pure-function OAuth rules in integrations/personal/shopify_oauth.py.

Every function here is side-effect-free (no I/O, no DB, no HTTP), so the
tests are fully synchronous and require no mocking infrastructure. That
cleanliness is exactly what the module was designed for — these tests exist
to lock down the security-critical paths so a refactor cannot silently
widen the shop-domain allow-list or weaken the constant-time HMAC check.
"""

import hashlib
import hmac
import time

import pytest
from src.integrations.base import IntegrationError
from src.integrations.personal.shopify_oauth import (
    TIMESTAMP_SKEW_SECONDS,
    normalise_shop,
    validate_shop_domain,
    verify_callback,
    verify_hmac,
)


# ── normalise_shop ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  mystore.myshopify.com  ", "mystore.myshopify.com"),
        ("MYSTORE.MYSHOPIFY.COM", "mystore.myshopify.com"),
        ("https://mystore.myshopify.com", "mystore.myshopify.com"),
        ("http://mystore.myshopify.com/", "mystore.myshopify.com"),
        ("mystore.myshopify.com/", "mystore.myshopify.com"),
    ],
)
def test_normalise_shop_strips_scheme_slash_whitespace_and_casing(raw, expected):
    assert normalise_shop(raw) == expected


# ── validate_shop_domain — happy path ────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "mystore.myshopify.com",
        "a.myshopify.com",
        "my-store.myshopify.com",
        "ab.myshopify.com",
        # 60-char subdomain label is the maximum allowed
        "a" * 60 + ".myshopify.com",
    ],
)
def test_validate_shop_domain_accepts_valid_myshopify_domains(raw):
    result = validate_shop_domain(raw)
    assert result.endswith(".myshopify.com")


def test_validate_shop_domain_normalises_before_returning():
    result = validate_shop_domain("  MYSTORE.MYSHOPIFY.COM  ")
    assert result == "mystore.myshopify.com"


# ── validate_shop_domain — rejection (SSRF / injection guards) ───────────


@pytest.mark.parametrize(
    "raw",
    [
        # Non-.myshopify.com hosts — accepting these would let a caller
        # point our token-exchange POST at a host they control.
        "mystore.shopify.com",
        "mystore.example.com",
        "evil.com",
        "mystore.myshopify.com.evil.com",
        # Subdomain label too long (>60 chars)
        "a" * 61 + ".myshopify.com",
        # Leading/trailing hyphens in subdomain label
        "-mystore.myshopify.com",
        "mystore-.myshopify.com",
        # Uppercase after normalisation passes, but a bare IP must not
        "192.168.1.1.myshopify.com",
        # Empty / non-string
        "",
        None,
        123,
    ],
)
def test_validate_shop_domain_rejects_non_myshopify_hosts(raw):
    with pytest.raises(IntegrationError) as exc_info:
        validate_shop_domain(raw)
    assert exc_info.value.code == "invalid_shop_domain"


def test_validate_shop_domain_rejects_missing_value():
    with pytest.raises(IntegrationError) as exc_info:
        validate_shop_domain(None)
    assert exc_info.value.code == "invalid_shop_domain"


# ── verify_hmac ──────────────────────────────────────────────────────────


def _make_valid_hmac_params(secret: str = "my-secret") -> dict[str, str]:
    """Build a query-param dict with a valid HMAC the way Shopify would."""
    params = {"shop": "test.myshopify.com", "code": "abc123", "timestamp": "1700000000"}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    computed = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {**params, "hmac": computed}


def test_verify_hmac_accepts_a_valid_signature():
    params = _make_valid_hmac_params("secret")
    assert verify_hmac(params, "secret") is True


def test_verify_hmac_rejects_a_tampered_hmac_value():
    """A forged or corrupted HMAC must never pass — constant-time comparison
    must not short-circuit on the first differing byte.
    """
    params = _make_valid_hmac_params("secret")
    tampered = dict(params)
    tampered["hmac"] = "0" * len(params["hmac"])

    assert verify_hmac(tampered, "secret") is False


def test_verify_hmac_rejects_a_tampered_payload():
    """Changing any signed param must invalidate the HMAC, even if the
    hmac value itself is structurally valid-looking hex.
    """
    params = _make_valid_hmac_params("secret")
    tampered = dict(params)
    tampered["code"] = "evil"

    assert verify_hmac(tampered, "secret") is False


def test_verify_hmac_rejects_wrong_secret():
    params = _make_valid_hmac_params("real-secret")
    assert verify_hmac(params, "wrong-secret") is False


def test_verify_hmac_returns_false_when_hmac_param_absent():
    params = {"shop": "test.myshopify.com", "code": "abc"}
    assert verify_hmac(params, "secret") is False


def test_verify_hmac_excludes_hmac_and_signature_from_canonical_string():
    """Shopify's spec excludes 'hmac' and 'signature' from signing scope.
    A request that includes a 'signature' field must still verify correctly
    — the signature field itself must not affect the computed HMAC.
    """
    params = _make_valid_hmac_params("secret")
    params["signature"] = "irrelevant-value"

    # The HMAC was computed without 'signature', so it must still be valid.
    assert verify_hmac(params, "secret") is True


# ── verify_callback ──────────────────────────────────────────────────────


def _valid_callback_params(secret: str = "s", shop: str = "test.myshopify.com") -> dict:
    ts = str(int(time.time()))
    base = {"shop": shop, "code": "c", "timestamp": ts}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(base.items()))
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {**base, "hmac": sig}


def test_verify_callback_passes_for_a_fresh_authentic_request():
    params = _valid_callback_params()
    # should not raise
    verify_callback(query_params=params, stored_shop="test.myshopify.com", client_secret="s")


def test_verify_callback_raises_on_invalid_hmac():
    params = _valid_callback_params()
    params["hmac"] = "bad"

    with pytest.raises(IntegrationError) as exc_info:
        verify_callback(query_params=params, stored_shop="test.myshopify.com", client_secret="s")
    assert exc_info.value.code == "invalid_hmac"


def test_verify_callback_raises_when_shop_does_not_match_stored_value():
    """After HMAC verification, the shop in the callback must equal the
    shop the user started the connect flow with (the Redis-stored value).
    A mismatch indicates either a CSRF attempt or a misconfigured redirect.
    """
    params = _valid_callback_params(shop="attacker.myshopify.com")

    with pytest.raises(IntegrationError) as exc_info:
        verify_callback(
            query_params=params,
            stored_shop="victim.myshopify.com",
            client_secret="s",
        )
    assert exc_info.value.code == "invalid_shop"


def test_verify_callback_raises_when_timestamp_is_too_old():
    stale_ts = int(time.time()) - (TIMESTAMP_SKEW_SECONDS + 10)
    secret = "s"
    shop = "test.myshopify.com"
    base = {"shop": shop, "code": "c", "timestamp": str(stale_ts)}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(base.items()))
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    params = {**base, "hmac": sig}

    with pytest.raises(IntegrationError) as exc_info:
        verify_callback(query_params=params, stored_shop=shop, client_secret=secret)
    assert exc_info.value.code == "timestamp_skew"


def test_verify_callback_accepts_timestamp_within_skew_window():
    """A timestamp 1 second inside the replay window must not be rejected."""
    secret = "s"
    shop = "test.myshopify.com"
    fresh_ts = int(time.time()) - (TIMESTAMP_SKEW_SECONDS - 1)
    base = {"shop": shop, "code": "c", "timestamp": str(fresh_ts)}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(base.items()))
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    params = {**base, "hmac": sig}

    # must not raise
    verify_callback(query_params=params, stored_shop=shop, client_secret=secret)


def test_verify_callback_treats_unparseable_timestamp_as_stale():
    """An unparseable timestamp must not bypass the replay-window check.
    It is treated as maximally stale rather than absent.
    """
    secret = "s"
    shop = "test.myshopify.com"
    base = {"shop": shop, "code": "c", "timestamp": "not-a-number"}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(base.items()))
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    params = {**base, "hmac": sig}

    with pytest.raises(IntegrationError) as exc_info:
        verify_callback(query_params=params, stored_shop=shop, client_secret=secret)
    assert exc_info.value.code == "timestamp_skew"


def test_verify_callback_skips_timestamp_check_when_param_absent():
    """A callback with no timestamp is accepted — Shopify's spec does not
    require it, and adding a mandatory timestamp would break installs that
    pre-date the field. The HMAC and shop check are still enforced.
    """
    secret = "s"
    shop = "test.myshopify.com"
    base = {"shop": shop, "code": "c"}
    canonical = "&".join(f"{k}={v}" for k, v in sorted(base.items()))
    sig = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    params = {**base, "hmac": sig}

    # must not raise
    verify_callback(query_params=params, stored_shop=shop, client_secret=secret)
